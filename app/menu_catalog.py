"""2단계: 실제 식당 메뉴를 우선하는 랜덤 메뉴 후보 조회 서비스."""

from __future__ import annotations

import math
import random
from dataclasses import asdict, dataclass, field
from typing import Literal, Protocol

from sqlalchemy.orm import Session

from .food_types import FOOD_TYPE_MAPPING


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
    verified_price_max: int | None = None
    serving_unverified: bool = True
    serving_status: str = "unverified"
    warnings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        """FastAPI 응답에 바로 사용할 수 있는 기본 자료형으로 변환한다."""

        return asdict(self)


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
    """DB에서 동일 조건을 통과한 실제 식당 상품만 추첨 후보로 사용한다."""
    _validate(latitude, longitude, radius_m, budget, cuisine)
    from .db_recommendations import qualifying_products, candidate_payloads
    products = qualifying_products(session, latitude=latitude, longitude=longitude,
        radius_m=radius_m, budget=budget, cuisine=cuisine, excluded_menu_ids=excluded_menu_ids)
    return [MenuCandidate(**item) for item in candidate_payloads(products)]


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
