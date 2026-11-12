"""2단계: 실제 식당 메뉴를 우선하는 랜덤 메뉴 후보 조회 서비스."""

from __future__ import annotations

import math
import random
import re
from dataclasses import asdict, dataclass
from typing import Literal, Protocol

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from .database.models import MenuCatalog, Restaurant
from .food_types import FOOD_TYPE_MAPPING, catalog_food_type, matches_food_type


class ChoiceSource(Protocol):
    """테스트에서 고정 난수 생성기를 주입하기 위한 최소 인터페이스."""

    def choice(self, sequence): ...


@dataclass(frozen=True, slots=True)
class MenuCandidate:
    """화면과 이후 추천 흐름에 전달할 대표 메뉴 후보."""

    id: str
    name: str
    cuisine: str
    search_keyword: str
    description: str
    source: Literal["database", "catalog"]
    price_verified: bool
    verified_price: int | None
    price_hint: int | None
    nearby_restaurant_count: int

    def to_dict(self) -> dict:
        """FastAPI 응답에 바로 사용할 수 있는 기본 자료형으로 변환한다."""

        return asdict(self)


def normalize_catalog_name(value: str) -> str:
    """띄어쓰기·문장부호·대소문자 차이를 제거해 메뉴와 별칭을 비교한다."""

    return re.sub(r"[^0-9a-z가-힣]+", "", value.casefold())


def _distance_m(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    """두 WGS84 좌표의 직선거리를 하버사인 공식으로 계산한다."""

    lat1_r, lat2_r = math.radians(lat1), math.radians(lat2)
    delta_lat = math.radians(lat2 - lat1)
    delta_lng = math.radians(lng2 - lng1)
    arc = (
        math.sin(delta_lat / 2) ** 2
        + math.cos(lat1_r) * math.cos(lat2_r) * math.sin(delta_lng / 2) ** 2
    )
    return 2 * 6_371_008.8 * math.asin(math.sqrt(min(1.0, max(0.0, arc))))


def _validate(latitude: float, longitude: float, radius_m: int, budget: int, cuisine: str) -> None:
    """서비스를 API 밖에서 호출해도 잘못된 추천 조건을 먼저 차단한다."""

    if not math.isfinite(latitude) or not -90 <= latitude <= 90:
        raise ValueError("위도 범위를 확인해 주세요.")
    if not math.isfinite(longitude) or not -180 <= longitude <= 180:
        raise ValueError("경도 범위를 확인해 주세요.")
    if type(radius_m) is not int or not 50 <= radius_m <= 500:
        raise ValueError("검색 반경은 50~500m 정수여야 합니다.")
    if type(budget) is not int or not 1000 <= budget <= 100000:
        raise ValueError("예산은 1,000~100,000원 정수여야 합니다.")
    if cuisine not in FOOD_TYPE_MAPPING:
        raise ValueError("지원하는 음식 종류를 확인해 주세요.")


def _catalog_match(catalogs: list[MenuCatalog], actual_name: str) -> MenuCatalog | None:
    """실제 메뉴명에 대표 이름이나 별칭이 포함되는 첫 카탈로그를 찾는다."""

    actual_key = normalize_catalog_name(actual_name)
    for catalog in catalogs:
        names = {catalog.normalized_name, *(alias.normalized_name for alias in catalog.aliases)}
        if any(name and name in actual_key for name in names):
            return catalog
    return None


def menu_candidates(
    session: Session,
    *,
    latitude: float,
    longitude: float,
    radius_m: int,
    budget: int,
    cuisine: str = "전체",
    excluded_menu_ids: set[str] | None = None,
) -> list[MenuCandidate]:
    """실제 확인 메뉴를 우선하고 없을 때만 카탈로그 기준 후보를 반환한다."""

    _validate(latitude, longitude, radius_m, budget, cuisine)
    excluded = excluded_menu_ids or set()
    catalogs = list(
        session.scalars(
            select(MenuCatalog)
            .where(MenuCatalog.active.is_(True))
            .options(selectinload(MenuCatalog.aliases))
            .order_by(MenuCatalog.name)
        ).all()
    )
    catalogs = [
        item for item in catalogs
        if item.id not in excluded
    ]
    if not catalogs:
        return []

    # 실제 메뉴와 수집 상태를 한 번에 읽어 식당별 추가 쿼리를 만들지 않는다.
    restaurants = session.scalars(
        select(Restaurant).options(
            selectinload(Restaurant.menus),
            selectinload(Restaurant.detail_status),
        )
    ).all()
    evidence: dict[str, dict[str, object]] = {}
    for restaurant in restaurants:
        # 실제 근거는 식당 업태를 기준으로 선택한다. 도시락집의 비빔밥도 후보가 된다.
        raw_cuisine = restaurant.cuisine or restaurant.category_name
        if not matches_food_type(cuisine, raw_cuisine):
            continue
        if _distance_m(latitude, longitude, restaurant.latitude, restaurant.longitude) > radius_m:
            continue
        if restaurant.detail_status is None or restaurant.detail_status.menu_status != "success":
            continue
        for menu in restaurant.menus:
            if menu.price_status != "known" or menu.price is None or menu.price > budget:
                continue
            catalog = _catalog_match(catalogs, menu.normalized_name or menu.name)
            if catalog is None:
                continue
            item = evidence.setdefault(catalog.id, {"prices": [], "restaurants": set()})
            item["prices"].append(menu.price)
            item["restaurants"].add(restaurant.id)

    if evidence:
        # 실제 근거가 하나라도 있으면 카탈로그 기준 후보를 섞지 않는다.
        return [
            MenuCandidate(
                id=catalog.id,
                name=catalog.name,
                cuisine=cuisine if cuisine != "전체" else catalog_food_type(catalog.cuisine),
                search_keyword=catalog.search_keyword,
                description=catalog.description,
                source="database",
                price_verified=True,
                verified_price=min(evidence[catalog.id]["prices"]),
                price_hint=catalog.price_hint,
                nearby_restaurant_count=len(evidence[catalog.id]["restaurants"]),
            )
            for catalog in catalogs
            if catalog.id in evidence
        ]

    # 주변 상세정보가 부족할 때만 기준 가격으로 후보를 좁히며 실제 가격으로 표시하지 않는다.
    return [
        MenuCandidate(
            id=catalog.id,
            name=catalog.name,
            cuisine=catalog_food_type(catalog.cuisine),
            search_keyword=catalog.search_keyword,
            description=catalog.description,
            source="catalog",
            price_verified=False,
            verified_price=None,
            price_hint=catalog.price_hint,
            nearby_restaurant_count=0,
        )
        for catalog in catalogs
        if catalog.price_hint is not None and catalog.price_hint <= budget
        and (cuisine == "전체" or catalog_food_type(catalog.cuisine) == cuisine)
    ]


def choose_menu(
    session: Session,
    *,
    latitude: float,
    longitude: float,
    radius_m: int,
    budget: int,
    cuisine: str = "전체",
    excluded_menu_ids: set[str] | None = None,
    rng: ChoiceSource | None = None,
) -> MenuCandidate | None:
    """조건 후보 중 하나를 고르며 후보가 없으면 None을 반환한다."""

    candidates = menu_candidates(
        session,
        latitude=latitude,
        longitude=longitude,
        radius_m=radius_m,
        budget=budget,
        cuisine=cuisine,
        excluded_menu_ids=excluded_menu_ids,
    )
    if not candidates:
        return None
    chooser = rng or random.SystemRandom()
    return chooser.choice(candidates)
