"""화면 음식 종류와 수집된 업태 이름을 연결하는 공통 규칙.

CSV 파일을 읽지 않는다. 원본 카카오 분류는 보존하고 조회 시 OR 조건으로 비교한다.
"""

from typing import Literal


FoodType = Literal[
    "전체", "한식", "중식", "일식/회", "양식", "분식", "패스트푸드",
    "치킨", "도시락/구내식당", "뷔페식", "냉면", "고기", "카페/빵", "술집", "기타",
]

FOOD_TYPE_MAPPING: dict[str, tuple[str, ...]] = {
    "전체": (),
    "한식": ("한식",),
    "중식": ("중국식", "중식"),
    "일식/회": ("일식", "횟집"),
    "양식": ("경양식", "패밀리레스트랑", "양식"),
    "분식": ("분식",),
    "패스트푸드": ("패스트푸드",),
    "치킨": ("통닭(치킨)", "호프/통닭", "치킨"),
    "도시락/구내식당": ("김밥(도시락)", "도시락", "구내식당"),
    "뷔페식": ("뷔페식", "뷔페"),
    "냉면": ("냉면집",),
    "고기": ("식육(숯불구이)",),
    "카페/빵": ("까페", "카페"),
    "술집": ("감성주점", "호프/통닭", "라이브카페", "정종/대포집/소주방", "술집"),
    "기타": ("기타", "외국음식전문점(인도,태국등)", "퓨전요리"),
}

# '전체'는 검색 조건일 뿐 개별 메뉴의 저장 분류는 아니다.
CATALOG_FOOD_TYPES = tuple(label for label in FOOD_TYPE_MAPPING if label != "전체")
CATALOG_CUISINE_CHECK = "cuisine IN (" + ", ".join(
    repr(label) for label in CATALOG_FOOD_TYPES
) + ")"


def matches_food_type(selected: str, raw_cuisine: str | None) -> bool:
    """카카오의 '음식점 > 중식 > 중국요리' 또는 단일 업태명을 비교한다."""

    if selected not in FOOD_TYPE_MAPPING:
        return False
    if selected == "전체":
        return True
    parts = [part.strip() for part in (raw_cuisine or "").split(">") if part.strip()]
    if parts and parts[0] == "음식점":
        parts = parts[1:]
    # 상세분류와 프랜차이즈 이름이 상위 음식 종류를 덮어쓰지 않게 첫 분류만 사용한다.
    return bool(parts and parts[0] in FOOD_TYPE_MAPPING[selected])


def catalog_food_type(raw: str) -> str:
    """이전 카탈로그 행을 수정하지 않고 새 화면 분류로 변환한다."""

    if raw in CATALOG_FOOD_TYPES:
        return raw
    if raw == "샐러드":
        # 독립 선택지가 제거되어 기존 샐러드 대표 메뉴는 기타에 포함한다.
        return "기타"
    return next(
        (label for label in FOOD_TYPE_MAPPING if label != "전체" and matches_food_type(label, raw)),
        "기타",
    )
