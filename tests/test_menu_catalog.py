"""2단계 메뉴 카탈로그 초기화와 실제 DB 우선 추첨 테스트."""

from pathlib import Path

from sqlalchemy import func, select

from app.database import Database, Menu, MenuAlias, MenuCatalog, PlaceDetailStatus, Restaurant
from app.database.seed import seed_menu_catalog
from app.menu_catalog import choose_menu, menu_candidates


def database_for(tmp_path: Path) -> Database:
    """각 테스트가 독립된 SQLite 파일과 기본 카탈로그를 사용하게 한다."""

    database = Database(f"sqlite:///{(tmp_path / 'catalog.db').as_posix()}")
    database.init_schema()
    return database


def add_restaurant(
    session,
    restaurant_id: str,
    *,
    latitude: float,
    longitude: float,
    menu_name: str,
    price: int,
) -> None:
    """실제 메뉴 우선순위 검증에 필요한 최소 식당 정보를 저장한다."""

    restaurant = Restaurant(
        id=restaurant_id,
        name=f"식당 {restaurant_id}",
        category_name="음식점 > 일식",
        cuisine="일식",
        latitude=latitude,
        longitude=longitude,
        address="서울 테스트로 1",
        place_url=f"https://place.map.kakao.com/{restaurant_id}",
        detail_status=PlaceDetailStatus(menu_status="success", hours_status="pending"),
    )
    restaurant.menus.append(
        Menu(
            name=menu_name,
            normalized_name=menu_name,
            price=price,
            price_status="known",
        )
    )
    session.add(restaurant)


def test_seed_is_idempotent_and_aliases_are_unique(tmp_path: Path):
    database = database_for(tmp_path)
    try:
        with database.session_factory.begin() as session:
            # 서버가 재시작된 상황처럼 시드를 다시 실행해도 행이 늘어나지 않아야 한다.
            assert seed_menu_catalog(session) == 0
        with database.session_factory() as session:
            assert session.scalar(select(func.count()).select_from(MenuCatalog)) == 10
            alias_count = session.scalar(select(func.count()).select_from(MenuAlias))
            unique_count = session.scalar(select(func.count(func.distinct(MenuAlias.normalized_name))))
            assert alias_count == unique_count
    finally:
        database.dispose()


def test_verified_nearby_menu_has_priority_and_alias_matches(tmp_path: Path):
    database = database_for(tmp_path)
    try:
        with database.session_factory.begin() as session:
            # 돈까스 표기도 돈가스 카탈로그 별칭으로 연결된다.
            add_restaurant(
                session,
                "near",
                latitude=37.4801,
                longitude=126.8801,
                menu_name="수제 왕돈까스",
                price=10500,
            )
            # 반경 밖 식당의 더 싼 메뉴는 후보 근거에 포함하지 않는다.
            add_restaurant(
                session,
                "far",
                latitude=37.5000,
                longitude=126.9000,
                menu_name="돈가스",
                price=7000,
            )

        with database.session_factory() as session:
            candidates = menu_candidates(
                session,
                latitude=37.48,
                longitude=126.88,
                radius_m=500,
                budget=12000,
                cuisine="일식",
            )
        assert [item.id for item in candidates] == ["cutlet"]
        assert candidates[0].source == "database"
        assert candidates[0].price_verified is True
        assert candidates[0].verified_price == 10500
        assert candidates[0].nearby_restaurant_count == 1
    finally:
        database.dispose()


def test_catalog_fallback_respects_budget_cuisine_and_exclusion(tmp_path: Path):
    database = database_for(tmp_path)
    try:
        with database.session_factory() as session:
            candidates = menu_candidates(
                session,
                latitude=37.48,
                longitude=126.88,
                radius_m=500,
                budget=9000,
                cuisine="중식",
            )
            excluded = choose_menu(
                session,
                latitude=37.48,
                longitude=126.88,
                radius_m=500,
                budget=9000,
                cuisine="중식",
                excluded_menu_ids={"noodle"},
            )
        assert [item.id for item in candidates] == ["noodle"]
        assert candidates[0].source == "catalog"
        assert candidates[0].price_verified is False
        assert candidates[0].verified_price is None
        assert excluded is None
    finally:
        database.dispose()


def test_invalid_conditions_are_rejected(tmp_path: Path):
    database = database_for(tmp_path)
    try:
        with database.session_factory() as session:
            try:
                menu_candidates(
                    session,
                    latitude=37.48,
                    longitude=126.88,
                    radius_m=1000,
                    budget=10000,
                )
            except ValueError as error:
                assert "50~500m" in str(error)
            else:
                raise AssertionError("범위 밖 반경이 거부되지 않았습니다.")
    finally:
        database.dispose()
