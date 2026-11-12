"""SQLite schema, foreign-key enforcement, and cascade behavior."""

from datetime import time
from pathlib import Path
from unittest.mock import patch

from alembic import command
from alembic.config import Config
from sqlalchemy import inspect, select, text

from app.database import (
    BusinessHours,
    Database,
    Menu,
    MenuAlias,
    MenuCatalog,
    PlaceDetailStatus,
    Restaurant,
)
from app.database.seed import seed_menu_catalog
from app.config import Settings
from app.operations import readiness_report


def test_sqlite_schema_and_foreign_key_cascade(tmp_path: Path):
    database = Database(f"sqlite:///{(tmp_path / 'test.db').as_posix()}")
    try:
        database.init_schema()
        inspector = inspect(database.engine)
        assert set(inspector.get_table_names()) == {
            "business_hours",
            "menu",
            "menu_alias",
            "menu_catalog",
            "place_detail_status",
            "restaurant",
        }

        # 최초 스키마 생성 시 추천용 기본 카탈로그와 별칭도 함께 준비된다.
        with database.session_factory() as session:
            assert len(session.scalars(select(MenuCatalog)).all()) == 10
            assert len(session.scalars(select(MenuAlias)).all()) >= 10

        with database.engine.connect() as connection:
            assert connection.execute(text("PRAGMA foreign_keys")).scalar_one() == 1
            assert connection.execute(text("PRAGMA journal_mode")).scalar_one() == "wal"

        with database.session_factory.begin() as session:
            restaurant = Restaurant(
                id="test-kakao-id",
                name="테스트 식당",
                category_name="음식점 > 한식",
                cuisine="한식",
                latitude=37.48,
                longitude=126.88,
                address="서울 테스트로 1",
                place_url="https://place.map.kakao.com/test-kakao-id",
            )
            restaurant.menus.append(
                Menu(
                    name="김치찌개",
                    normalized_name="김치찌개",
                    price=9000,
                    price_status="known",
                )
            )
            restaurant.business_hours.append(
                BusinessHours(
                    day_of_week=0,
                    holiday=False,
                    start_time=time(11, 0),
                    end_time=time(15, 0),
                    sequence=0,
                )
            )
            restaurant.detail_status = PlaceDetailStatus(
                menu_status="success", hours_status="success"
            )
            session.add(restaurant)

        with database.session_factory.begin() as session:
            stored = session.get(Restaurant, "test-kakao-id")
            assert stored is not None
            session.delete(stored)

        with database.session_factory() as session:
            assert session.scalar(select(Menu.id)) is None
            assert session.scalar(select(BusinessHours.id)) is None
            assert session.scalar(select(PlaceDetailStatus.restaurant_id)) is None
    finally:
        database.dispose()


def alembic_config(database_url: str) -> Config:
    """프로젝트 설정 파일을 사용하되 테스트 DB URL만 안전하게 주입한다."""

    config = Config(str(Path(__file__).parents[1] / "alembic.ini"))
    config.attributes["database_url"] = database_url
    return config


def test_alembic_upgrade_creates_schema_matching_models(tmp_path: Path):
    url = f"sqlite:///{(tmp_path / 'migration.db').as_posix()}"
    config = alembic_config(url)
    command.upgrade(config, "head")
    database = Database(url)
    try:
        names = set(inspect(database.engine).get_table_names())
        assert names == {
            "alembic_version",
            "business_hours",
            "menu",
            "menu_alias",
            "menu_catalog",
            "place_detail_status",
            "restaurant",
        }
        # 초기 마이그레이션과 현재 ORM 모델 사이에 새 변경사항이 없어야 한다.
        command.check(config)
        with database.session_factory.begin() as session:
            assert seed_menu_catalog(session) == 10
    finally:
        database.dispose()


def test_existing_create_all_database_can_be_stamped_without_data_loss(tmp_path: Path):
    url = f"sqlite:///{(tmp_path / 'existing.db').as_posix()}"
    database = Database(url)
    try:
        database.init_schema()
        command.stamp(alembic_config(url), "head")
        with database.session_factory() as session:
            assert len(session.scalars(select(MenuCatalog)).all()) == 10
            version = session.execute(text("SELECT version_num FROM alembic_version")).scalar_one()
            assert version == "0005_server_only_rls"
    finally:
        database.dispose()


def test_readiness_checks_database_catalog_browser_and_configuration(tmp_path: Path):
    database = Database(f"sqlite:///{(tmp_path / 'ready.db').as_posix()}")
    database.init_schema()
    settings = Settings(map_api_key="kakao", groq_api_key="groq")
    try:
        with patch("app.operations._playwright_browser_available", return_value=True):
            report, status = readiness_report(database, settings)
        assert status == 200
        assert report["status"] == "ready"
        assert report["checks"]["menu_catalog_count"] == 10

        with patch("app.operations._playwright_browser_available", return_value=False):
            report, status = readiness_report(database, settings)
        assert status == 503
        assert report["status"] == "not_ready"
        assert report["checks"]["playwright_chromium"] is False
    finally:
        database.dispose()


def test_food_type_migration_preserves_rows_aliases_and_inactive_state(tmp_path):
    url = f"sqlite:///{(tmp_path / 'old_catalog.db').as_posix()}"
    config = alembic_config(url)
    command.upgrade(config, "0001_initial_schema")
    database = Database(url)
    try:
        with database.engine.begin() as connection:
            for key, cuisine in [('old-fish', '일식'), ('old-salad', '샐러드')]:
                connection.execute(text(
                    "INSERT INTO menu_catalog (id,name,normalized_name,cuisine,search_keyword,description,price_hint,active) "
                    "VALUES (:id,:id,:id,:cuisine,:id,'설명',9000,false)"
                ), {'id': key, 'cuisine': cuisine})
            connection.execute(text(
                "INSERT INTO menu_alias (menu_catalog_id,name,normalized_name) VALUES ('old-fish','별칭','별칭')"
            ))
        command.upgrade(config, "head")
        with database.session_factory() as session:
            fish = session.get(MenuCatalog, 'old-fish')
            assert fish.cuisine == '일식/회'
            assert not fish.active
            assert fish.price_hint == 9000
            assert fish.description == '설명'
            assert [row.name for row in fish.aliases] == ['별칭']
            assert session.get(MenuCatalog, 'old-salad').cuisine == '기타'
        with database.engine.connect() as connection:
            assert connection.execute(text('PRAGMA foreign_key_check')).all() == []
        command.check(config)
    finally:
        database.dispose()
