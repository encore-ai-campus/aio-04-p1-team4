"""2단계: 최초 실행에 필요한 대표 메뉴 카탈로그를 중복 없이 등록한다."""

from __future__ import annotations

import re

from sqlalchemy import select
from sqlalchemy.orm import Session

from .models import MenuAlias, MenuCatalog


# price_hint는 주변 식당 정보가 없을 때 예산 후보를 좁히는 기준값이다.
# 실제 식당 가격은 반드시 menu 테이블의 확인 가격을 사용한다.
DEFAULT_MENU_CATALOG = (
    dict(id="bibimbap", name="비빔밥", cuisine="한식", price_hint=9000,
         search_keyword="비빔밥", description="밥에 여러 재료를 곁들여 비벼 먹는 한식 메뉴예요.",
         aliases=("비빔밥",)),
    dict(id="kimchi", name="김치찌개", cuisine="한식", price_hint=9500,
         search_keyword="김치찌개", description="김치를 중심으로 끓인 따뜻한 한식 찌개예요.",
         aliases=("김치찌개",)),
    dict(id="tofu", name="두부 채소 덮밥", cuisine="한식", price_hint=8500,
         search_keyword="두부 덮밥", description="두부와 채소를 밥에 곁들이는 메뉴예요. 실제 재료는 매장 확인이 필요해요.",
         aliases=("두부 채소 덮밥", "두부덮밥")),
    dict(id="noodle", name="짜장면", cuisine="중식", price_hint=8000,
         search_keyword="짜장면", description="춘장 소스를 면에 곁들이는 중식 메뉴예요.",
         aliases=("짜장면", "자장면")),
    dict(id="spicynoodle", name="짬뽕", cuisine="중식", price_hint=10000,
         search_keyword="짬뽕", description="국물과 면을 함께 먹는 중식 메뉴예요.",
         aliases=("짬뽕",)),
    dict(id="cutlet", name="돈가스", cuisine="일식", price_hint=11000,
         search_keyword="돈가스", description="튀긴 돼지고기 커틀릿을 중심으로 한 메뉴예요.",
         aliases=("돈가스", "돈까스")),
    dict(id="udon", name="우동", cuisine="일식", price_hint=8500,
         search_keyword="우동", description="굵은 면을 국물 또는 소스와 함께 먹는 메뉴예요.",
         aliases=("우동",)),
    dict(id="pasta", name="크림 파스타", cuisine="양식", price_hint=12000,
         search_keyword="크림 파스타", description="크림 계열 소스를 면과 함께 먹는 양식 메뉴예요.",
         aliases=("크림 파스타", "까르보나라")),
    dict(id="salad", name="병아리콩 샐러드", cuisine="샐러드", price_hint=9500,
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
