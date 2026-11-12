from sqlalchemy import select, func

from app.database import Database, Restaurant, Menu, PlaceDetailStatus
from app.database.cli import initialize
from supabase_manage import copy_verified


def test_postgres_url_uses_psycopg_tls_and_bounded_connect_timeout():
    database=Database('postgresql://user:password@localhost:5432/postgres')
    try:
        assert database.engine.url.drivername=='postgresql+psycopg'
        assert database.engine.url.query['sslmode']=='require'
        assert database.engine.url.query['connect_timeout']=='8'
    finally: database.dispose()


def test_transfer_excludes_legacy_rows_and_does_not_overwrite_destination(tmp_path):
    for name in ('source','target'): initialize(tmp_path/f'{name}.db')
    source=Database(f'sqlite:///{(tmp_path/"source.db").as_posix()}')
    target=Database(f'sqlite:///{(tmp_path/"target.db").as_posix()}')
    try:
        with source.session_factory.begin() as session:
            for rid,provenance in [('1','kakao_api'),('2',None)]:
                row=Restaurant(id=rid,name='식당'+rid,basic_source=provenance,latitude=37.4,longitude=126.8,address='서울',place_url=f'https://place.map.kakao.com/{rid}')
                row.detail_status=PlaceDetailStatus(menu_status='success',menu_source_url=row.place_url)
                row.menus=[Menu(name='김치찌개',normalized_name='김치찌개',price=9000,price_status='known')]
                session.add(row)
        assert copy_verified(source,target)['copied_restaurants']==1
        assert copy_verified(source,target)['existing_skipped']==1
        with target.session_factory() as session:
            assert session.scalar(select(func.count()).select_from(Restaurant))==1
            assert session.scalar(select(func.count()).select_from(Menu))==1
            assert session.get(Restaurant,'2') is None
    finally:
        source.dispose();target.dispose()
