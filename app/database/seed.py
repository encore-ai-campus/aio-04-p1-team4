"""2단계: 최초 실행에 필요한 대표 메뉴 카탈로그를 중복 없이 등록한다."""

from __future__ import annotations

import re

from sqlalchemy import select
from sqlalchemy.orm import Session

from .models import MenuAlias, MenuCatalog
from ..food_types import CATALOG_FOOD_TYPES


# price_hint는 주변 식당 정보가 없을 때 예산 후보를 좁히는 기준값이다.
# 실제 식당 가격은 반드시 menu 테이블의 확인 가격을 사용한다.
DEFAULT_MENU_CATALOG = (
    dict(id="bibimbap", name="비빔밥", cuisine="한식", price_hint=9000,
         search_keyword="비빔밥", description="밥에 여러 재료를 곁들여 비벼 먹는 한식 메뉴예요.",
         aliases=("비빔밥",)),
    dict(id="kimchi", name="김치찌개", cuisine="한식", price_hint=9500,
         search_keyword="김치찌개", description="김치를 중심으로 끓인 따뜻한 한식 찌개예요.",
         aliases=("김치찌개",)),
    dict(id="tofu", name="된장찌개", cuisine="한식", price_hint=8500,
         search_keyword="두부 덮밥", description="두부와 채소를 밥에 곁들이는 메뉴예요. 실제 재료는 매장 확인이 필요해요.",
         aliases=("두부 채소 덮밥", "두부덮밥")),
    dict(id="noodle", name="짜장면", cuisine="중식", price_hint=8000,
         search_keyword="짜장면", description="춘장 소스를 면에 곁들이는 중식 메뉴예요.",
         aliases=("짜장면", "자장면")),
    dict(id="spicynoodle", name="짬뽕", cuisine="중식", price_hint=10000,
         search_keyword="짬뽕", description="국물과 면을 함께 먹는 중식 메뉴예요.",
         aliases=("짬뽕",)),
    dict(id="cutlet", name="돈가스", cuisine="일식/회", price_hint=11000,
         search_keyword="돈가스", description="튀긴 돼지고기 커틀릿을 중심으로 한 메뉴예요.",
         aliases=("돈가스", "돈까스")),
    dict(id="udon", name="우동", cuisine="일식/회", price_hint=8500,
         search_keyword="우동", description="굵은 면을 국물 또는 소스와 함께 먹는 메뉴예요.",
         aliases=("우동",)),
    dict(id="pasta", name="크림 파스타", cuisine="양식", price_hint=12000,
         search_keyword="크림 파스타", description="크림 계열 소스를 면과 함께 먹는 양식 메뉴예요.",
         aliases=("크림 파스타", "까르보나라")),
    dict(id="salad", name="병아리콩 샐러드", cuisine="기타", price_hint=9500,
         search_keyword="병아리콩 샐러드", description="병아리콩과 채소를 중심으로 구성한 샐러드예요.",
         aliases=("병아리콩 샐러드", "콩 샐러드")),
    dict(id="pizza", name="치즈 피자", cuisine="양식", price_hint=13000,
         search_keyword="치즈 피자", description="치즈를 중심으로 한 피자 메뉴예요.",
         aliases=("치즈 피자",)),
)


def _key(value: str) -> str:
    """띄어쓰기와 문장부호 차이를 제거해 별칭 중복을 판정한다."""

    return re.sub(r"[^0-9a-z가-힣]+", "", value.casefold())


def seed_menu_catalog(session: Session) -> int:
    """누락된 기본 메뉴와 별칭만 추가하고 기존 운영 데이터는 덮어쓰지 않는다."""

    inserted = 0
    known_aliases = set(session.scalars(select(MenuAlias.normalized_name)).all())
    for item in DEFAULT_MENU_CATALOG:
        catalog = session.get(MenuCatalog, item["id"])
        if catalog is None:
            catalog = MenuCatalog(
                id=item["id"],
                name=item["name"],
                normalized_name=_key(item["name"]),
                cuisine=item["cuisine"],
                search_keyword=item["search_keyword"],
                description=item["description"],
                price_hint=item["price_hint"],
                active=True,
            )
            session.add(catalog)
            inserted += 1

        # 같은 초기화가 반복돼도 전역 고유 별칭은 한 번만 저장한다.
        for alias_name in item["aliases"]:
            normalized = _key(alias_name)
            if normalized in known_aliases:
                continue
            session.add(
                MenuAlias(
                    catalog=catalog,
                    name=alias_name,
                    normalized_name=normalized,
                )
            )
            known_aliases.add(normalized)
    return inserted


def sync_menu_catalog(session: Session, items=None) -> dict[str, int]:
    """목록을 검증한 뒤 동기화한다. 커밋·롤백은 호출자의 트랜잭션이 담당한다.

    이 DB의 대표 메뉴 카탈로그 전체를 seed.py가 관리한다. 식당에서 수집한
    Menu 행은 건드리지 않는다. 삭제한 대표 메뉴는 active=False로 남긴다.
    """
    items = list(DEFAULT_MENU_CATALOG if items is None else items)
    if not items:
        raise ValueError("빈 목록은 전체 비활성화 방지를 위해 허용하지 않습니다.")
    ids, names, aliases = set(), set(), set()
    for item in items:
        for key, limit in (("id", 40), ("name", 100), ("search_keyword", 100), ("description", 500)):
            value = item.get(key)
            if not isinstance(value, str) or not value.strip() or len(value) > limit:
                raise ValueError(f"메뉴 {item.get('id')}: {key} 값을 확인하세요.")
        if item['id'] in ids or _key(item['name']) in names:
            raise ValueError("메뉴 ID 또는 이름이 중복됩니다.")
        # 동일한 공통 목록으로 DB CHECK와 수동 메뉴 편집을 검증한다.
        if item.get('cuisine') not in CATALOG_FOOD_TYPES:
            raise ValueError("카탈로그 저장 분류를 확인하세요: " + ', '.join(CATALOG_FOOD_TYPES))
        price = item.get('price_hint')
        if price is not None and (type(price) is not int or price < 0):
            raise ValueError("기준가격은 음수가 아닌 정수 또는 None이어야 합니다.")
        values = item.get('aliases')
        if not isinstance(values, (tuple, list)):
            raise ValueError("aliases는 목록 또는 튜플이어야 합니다.")
        for alias in values:
            if not isinstance(alias, str) or len(alias) > 100 or not _key(alias):
                raise ValueError("별칭 값을 확인하세요.")
            if _key(alias) in aliases:
                raise ValueError("별칭이 중복됩니다.")
            aliases.add(_key(alias))
        ids.add(item['id'])
        names.add(_key(item['name']))

    rows = {row.id: row for row in session.scalars(select(MenuCatalog)).all()}
    result = dict(inserted=0, updated=0, deactivated=0)
    # 별칭을 먼저 비워 flush하여 다른 메뉴로 이동한 별칭의 고유키 충돌을 피한다.
    for row in rows.values():
        row.aliases.clear()
    session.flush()
    for item in items:
        row = rows.get(item['id'])
        if row is None:
            row = MenuCatalog(id=item['id'])
            session.add(row)
            result['inserted'] += 1
        else:
            result['updated'] += 1
        for key in ('name', 'cuisine', 'search_keyword', 'description', 'price_hint'):
            setattr(row, key, item[key])
        row.normalized_name = _key(item['name'])
        row.active = True
        row.aliases = [MenuAlias(name=value, normalized_name=_key(value)) for value in item['aliases']]
    for menu_id, row in rows.items():
        if menu_id not in ids and row.active:
            row.active = False
            result['deactivated'] += 1
    session.flush()
    return result


if __name__ == '__main__':
    # 사용자가 명시적으로 실행할 때 추가·수정·비활성화를 함께 반영한다.
    import json
    import os
    from dotenv import load_dotenv
    from .session import Database
    from ..config import ENV_FILE, DEFAULT_DATABASE_URL

    load_dotenv(ENV_FILE, override=False)
    database = Database(os.environ.get('DATABASE_URL', DEFAULT_DATABASE_URL))
    try:
        # 테이블은 Alembic 또는 앱 초기화로 먼저 준비한다.
        with database.session_factory.begin() as session:
            result = sync_menu_catalog(session)
        print(json.dumps(result, ensure_ascii=False))
    finally:
        database.dispose()
