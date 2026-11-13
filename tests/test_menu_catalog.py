"""2단계 메뉴 카탈로그 초기화와 실제 DB 우선 추첨 테스트."""

from pathlib import Path
from datetime import time
from app.database import BusinessHours
import pytest

from sqlalchemy import func, select

from app.database import Database, Menu, MenuAlias, MenuCatalog, PlaceDetailStatus, Restaurant
from app.database.seed import seed_menu_catalog
from app.database.seed import sync_menu_catalog, DEFAULT_MENU_CATALOG
from app.menu_catalog import choose_menu, menu_candidates
from app.food_types import FOOD_TYPE_MAPPING, catalog_food_type, matches_food_type
from app.food_types import CATALOG_FOOD_TYPES
from app.schemas import Conditions
from app.chat_policy import ConditionPatch


def database_for(tmp_path: Path) -> Database:
    """각 테스트가 독립된 SQLite 파일과 기본 카탈로그를 사용하게 한다."""

    database = Database(f"sqlite:///{(tmp_path / 'catalog.db').as_posix()}")
    database.init_schema()
    return database


def test_manual_seed_sync_updates_disables_and_reactivates(tmp_path):
    database = database_for(tmp_path)
    try:
        item = {**DEFAULT_MENU_CATALOG[0], 'description': '수정한 설명', 'aliases': ('새별칭',)}
        with database.session_factory.begin() as session:
            result = sync_menu_catalog(session, [item])
            assert result['deactivated'] == 9
        with database.session_factory() as session:
            row = session.get(MenuCatalog, item['id'])
            assert row.description == '수정한 설명'
            assert [alias.name for alias in row.aliases] == ['새별칭']
            assert not session.get(MenuCatalog, 'noodle').active
        with database.session_factory.begin() as session:
            sync_menu_catalog(session)
        with database.session_factory() as session:
            assert session.get(MenuCatalog, 'noodle').active
        with pytest.raises(ValueError):
            with database.session_factory.begin() as session:
                sync_menu_catalog(session, [item, item])
    finally:
        database.dispose()


def test_sync_accepts_all_catalog_food_types(tmp_path):
    database = database_for(tmp_path)
    try:
        items = [dict(DEFAULT_MENU_CATALOG[0], id=f'group-{i}', name=f'메뉴{i}',
                      cuisine=group, aliases=(f'별칭{i}',))
                 for i, group in enumerate(CATALOG_FOOD_TYPES)]
        with database.session_factory.begin() as session:
            assert sync_menu_catalog(session, items)['inserted'] == 14
        with database.session_factory() as session:
            rows = session.scalars(select(MenuCatalog).where(MenuCatalog.active.is_(True))).all()
            assert {row.cuisine for row in rows} == set(CATALOG_FOOD_TYPES)
            assert all(catalog_food_type(row.cuisine) == row.cuisine for row in rows)
        with pytest.raises(ValueError):
            with database.session_factory.begin() as session:
                sync_menu_catalog(session, [dict(items[0], cuisine='전체')])
    finally:
        database.dispose()


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
        detail_status=PlaceDetailStatus(menu_status="success", hours_status="success"),
    )
    restaurant.menus.append(
        Menu(
            name=menu_name,
            normalized_name=menu_name,
            menu_catalog_id='bibimbap' if menu_name=='비빔밥' else 'cutlet',
            price=price,
            price_status="known",
        )
    )
    restaurant.business_hours = [BusinessHours(day_of_week=d, holiday=False, start_time=time(0), end_time=time(0), ends_next_day=True) for d in range(7)]
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


def test_verified_nearby_menu_uses_explicit_catalog_link(tmp_path: Path):
    database = database_for(tmp_path)
    try:
        with database.session_factory.begin() as session:
            # 적재 시 확정한 FK로 연결하며 조회할 때 이름을 추측하지 않는다.
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
                cuisine="일식/회",
            )
        assert [item.id for item in candidates] == ["cutlet"]
        assert candidates[0].source == "database"
        assert candidates[0].price_verified is True
        assert candidates[0].verified_price == 10500
        assert candidates[0].nearby_restaurant_count == 1
    finally:
        database.dispose()


def test_empty_database_never_falls_back_to_seed_prices(tmp_path: Path):
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
        assert candidates == []
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


@pytest.mark.parametrize("label,raw", [
    (label, raw) for label, values in FOOD_TYPE_MAPPING.items() for raw in values
])
def test_each_industry_alias_matches_selected_group(label, raw):
    # CSV를 읽지 않고 명시적인 OR 매핑과 Pydantic 허용값의 일치를 검사한다.
    assert matches_food_type(label, raw)
    assert matches_food_type(label, f"음식점 > {raw} > 테스트 지점")
    assert Conditions(cuisine=label).cuisine == label
    assert ConditionPatch(cuisine=label).cuisine == label


def test_all_overlap_and_legacy_catalog_mapping():
    assert matches_food_type("전체", None)
    assert matches_food_type("치킨", "호프/통닭")
    assert matches_food_type("술집", "호프/통닭")
    assert not matches_food_type("한식", "중식")
    assert not matches_food_type("기타", "분류되지않은값")
    assert catalog_food_type("일식") == "일식/회"
    assert catalog_food_type("샐러드") == "기타"


def test_restaurant_industry_controls_verified_menu_candidates(tmp_path: Path):
    database = database_for(tmp_path)
    try:
        with database.session_factory.begin() as session:
            add_restaurant(session, "canteen", latitude=37.48, longitude=126.88,
                           menu_name="비빔밥", price=7000)
            session.flush()
            restaurant = session.get(Restaurant, "canteen")
            # 한식 대표 메뉴를 파는 도시락집도 도시락 선택에서 실제 근거로 사용할 수 있다.
            restaurant.cuisine = "도시락"
            restaurant.category_name = "음식점 > 도시락"
        with database.session_factory() as session:
            candidates = menu_candidates(
                session, latitude=37.48, longitude=126.88, radius_m=500,
                budget=8000, cuisine="도시락/구내식당",
            )
        assert [item.id for item in candidates] == ["bibimbap"]
        assert candidates[0].cuisine == "한식"  # 대표 메뉴 업종과 매장 업종을 구분
        assert candidates[0].source == "database"
    finally:
        database.dispose()
