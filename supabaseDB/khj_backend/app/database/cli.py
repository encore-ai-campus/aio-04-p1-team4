"""요청한 7개 테이블을 Alembic으로 만들고 JSON 자료를 저장·조회한다."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import re

from alembic import command
from alembic.config import Config
from sqlalchemy import func, inspect, or_, select, text
from sqlalchemy.orm import selectinload

from . import BusinessHours, Database, Menu, MenuAlias, MenuCatalog, PlaceDetailStatus, Restaurant
from .seed import seed_menu_catalog

ROOT = Path(__file__).resolve().parents[2]
TABLES = [MenuCatalog, MenuAlias, Restaurant, Menu, BusinessHours, PlaceDetailStatus]


def initialize(path: Path) -> dict:
    path.parent.mkdir(parents=True, exist_ok=True)
    return initialize_url(f'sqlite:///{path.as_posix()}')


def initialize_url(database_url: str) -> dict:
    database = Database(database_url)
    config = Config(str(ROOT / 'alembic.ini'))
    config.set_main_option('script_location', str(ROOT / 'alembic'))
    config.set_main_option('prepend_sys_path', str(ROOT))
    config.attributes['database_url'] = database.engine.url.render_as_string(hide_password=False)
    try:
        tables=inspect(database.engine).get_table_names()
        if 'restaurant' in tables and 'alembic_version' not in tables:
            raise RuntimeError('기존 식당 테이블의 마이그레이션 이력을 먼저 확인해주세요.')
        command.upgrade(config, 'head')
        with database.session_factory.begin() as session:
            added = seed_menu_catalog(session)
        return {'database': database.engine.dialect.name, 'catalog_added': added, **summary(database)}
    finally:
        database.dispose()


def summary(database: Database) -> dict:
    with database.session_factory() as session:
        counts = {model.__tablename__: session.scalar(select(func.count()).select_from(model)) for model in TABLES}
        version = session.execute(text('SELECT version_num FROM alembic_version')).scalar_one()
    return {'tables': inspect(database.engine).get_table_names(), 'counts': counts, 'alembic_version': version}


def load_json(database: Database, path: Path) -> dict:
    """카카오 documents는 기본정보로, 별도 details는 실제 메뉴·시간으로 저장한다."""
    from ..collectors import RawBusinessDay, RawMenu, RawPlacePage
    from ..place_details import parse_place_page
    from ..repositories import save_place_details, save_restaurants

    payload = json.loads(path.read_text(encoding='utf-8-sig'))
    if not isinstance(payload, dict) or not isinstance(payload.get('documents'), list):
        raise ValueError('documents 배열이 있는 JSON 파일이 필요합니다.')
    candidates = []
    for item in payload['documents']:
        rid = str(item['id'])
        if not rid.isascii() or not rid.isdecimal():
            raise ValueError('restaurant.id에는 확인된 숫자 형식의 카카오 장소 ID만 저장합니다.')
        candidates.append({'id': rid, 'name': item['place_name'], 'lat': float(item['y']), 'lng': float(item['x']),
                           'address': item.get('road_address_name') or item.get('address_name', ''),
                           'category': item.get('category_name', ''), 'category_group_code': item.get('category_group_code', 'FD6'),
                           'place_url': f'https://place.map.kakao.com/{rid}'})

    detail = payload.get('details')
    normalized = None
    attempted_at = None
    if detail is not None:
        if str(detail['restaurant_id']) not in {r['id'] for r in candidates}:
            raise ValueError('details.restaurant_id가 documents의 카카오 ID와 일치해야 합니다.')
        attempted_at = datetime.fromisoformat(detail['checked_at'].replace('Z', '+00:00'))
        if attempted_at.tzinfo is None or attempted_at.utcoffset() is None:
            raise ValueError('checked_at에는 +09:00 또는 Z 시간대를 포함하세요.')
        attempted_at = attempted_at.astimezone(timezone.utc)
        if not all(isinstance(detail.get(k), bool) for k in ['menu_section_present', 'hours_section_present']):
            raise ValueError('상세 영역 확인 여부는 true/false여야 합니다.')
        menus = detail.get('menus', [])
        days = detail.get('business_days', [])
        if not all(isinstance(m.get('name'), str) and isinstance(m.get('price_text'), str) for m in menus):
            raise ValueError('메뉴의 name과 price_text는 문자열이어야 합니다.')
        if not all(isinstance(d.get('day_text'), str) and isinstance(d.get('details'), list)
                   and all(isinstance(line, str) for line in d['details']) for d in days):
            raise ValueError('business_days에는 day_text와 details 문자열 배열이 필요합니다.')
        normalized = parse_place_page(RawPlacePage(
            menu_section_present=detail['menu_section_present'], hours_section_present=detail['hours_section_present'],
            menus=tuple(RawMenu(name=m['name'], price_text=m['price_text']) for m in menus),
            business_days=tuple(RawBusinessDay(day_text=d['day_text'], details=tuple(d['details'])) for d in days)))

    with database.session_factory() as session:
        result = {'restaurants': save_restaurants(session, candidates).model_dump()}
        if normalized is not None:
            result['details'] = save_place_details(session, str(detail['restaurant_id']), normalized, attempted_at=attempted_at)
        return result


def restaurant_detail(database: Database, rid: str) -> dict | None:
    def utc(value):
        if value is None:
            return None
        return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)
    with database.session_factory() as session:
        row = session.scalar(select(Restaurant).where(Restaurant.id == rid).options(
            selectinload(Restaurant.menus), selectinload(Restaurant.business_hours), selectinload(Restaurant.detail_status)))
        if row is None:
            return None
        status = row.detail_status
        return {'id': row.id, 'name': row.name, 'latitude': row.latitude, 'longitude': row.longitude,
                'address': row.address, 'place_url': row.place_url,
                'menus': [{'name': m.name, 'normalized_name': m.normalized_name, 'price': m.price, 'price_status': m.price_status} for m in row.menus],
                'business_hours': [{'day_of_week': h.day_of_week, 'holiday': h.holiday, 'start_time': h.start_time,
                                    'end_time': h.end_time, 'ends_next_day': h.ends_next_day, 'sequence': h.sequence} for h in sorted(row.business_hours, key=lambda h:(h.day_of_week,h.sequence))],
                'detail_status': None if status is None else {'menu_status': status.menu_status, 'hours_status': status.hours_status,
                    'last_attempt_at': utc(status.last_attempt_at), 'last_success_at': utc(status.last_success_at)}}


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description='SQLite DB 초기화와 카카오 식당·상세정보 저장 및 조회')
    parser.add_argument('--db', type=Path, default=ROOT / 'data/lunchrun.db', help='SQLite 파일 경로')
    commands = parser.add_subparsers(dest='action', required=True)
    commands.add_parser('init', help='Alembic 마이그레이션 및 기본 추천 메뉴 등록')
    commands.add_parser('summary', help='테이블별 행 수와 마이그레이션 버전')
    loader = commands.add_parser('load-json', help='카카오 응답 및 확인된 상세정보 JSON 저장')
    loader.add_argument('path', type=Path)
    show = commands.add_parser('show', help='카카오 ID로 식당·메뉴·영업시간 조회')
    show.add_argument('id')
    search = commands.add_parser('search', help='식당명 검색')
    search.add_argument('keyword')
    catalog = commands.add_parser('catalog', help='대표 메뉴 또는 별칭 검색')
    catalog.add_argument('keyword')
    args = parser.parse_args(argv)
    path = args.db.expanduser().resolve()
    if args.action == 'init':
        result = initialize(path)
    else:
        if not path.is_file():
            parser.error('DB가 없습니다. 먼저 init 명령을 실행하세요.')
        database = Database(f'sqlite:///{path.as_posix()}')
        try:
            if args.action == 'summary':
                result = summary(database)
            elif args.action == 'load-json':
                result = load_json(database, args.path)
            elif args.action == 'show':
                result = restaurant_detail(database, args.id)
            else:
                with database.session_factory() as session:
                    if args.action == 'search':
                        result = [{'id': r.id, 'name': r.name, 'address': r.address} for r in session.scalars(
                            select(Restaurant).where(Restaurant.name.contains(args.keyword, autoescape=True)).limit(20))]
                    else:
                        key = re.sub(r'[^0-9a-z가-힣]+', '', args.keyword.casefold())
                        result = [{'id': r.id, 'name': r.name, 'cuisine': r.cuisine, 'price_hint': r.price_hint} for r in session.scalars(
                            select(MenuCatalog).outerjoin(MenuAlias).where(MenuCatalog.active.is_(True),
                            or_(MenuCatalog.normalized_name == key, MenuAlias.normalized_name == key))).unique()]
        finally:
            database.dispose()
    print(json.dumps(result, ensure_ascii=False, indent=2, default=str))
    return 0
