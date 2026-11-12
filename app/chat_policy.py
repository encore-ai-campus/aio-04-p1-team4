"""4단계: 대화 문맥을 포함한 Groq 실행 계획과 가드레일 계약."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationInfo, field_validator, model_validator


POLICY_DIR = Path(__file__).resolve().parent / "prompts"
SYSTEM_PROMPT_FILE = POLICY_DIR / "system_v2.txt"
EXAMPLES_FILE = POLICY_DIR / "examples_v2.json"
REPLIES_FILE = POLICY_DIR / "replies_v3.json"


def load_replies() -> dict[str, str]:
    """코드가 적용하는 최신 v2 안내문 키와 문자열 범위를 검사한다."""

    replies = json.loads(REPLIES_FILE.read_text(encoding="utf-8"))
    required = {
        "ambiguous", "radius", "budget", "location", "unsupported", "conflict",
        "menu", "restaurant", "out_of_scope", "notice",
    }
    if not isinstance(replies, dict) or set(replies) != required:
        raise ValueError("v2 답변 안내문의 항목을 확인해 주세요.")
    if any(not isinstance(value, str) or not value.strip() or len(value) > 500
           for value in replies.values()):
        raise ValueError("안내문은 1~500자의 문자열이어야 합니다.")
    return replies


class ConditionPatch(BaseModel):
    """사용자가 명확히 지정한 변경값만 담는 조건 부분 수정."""

    model_config = ConfigDict(extra="forbid", strict=True)
    minutes: int | None = Field(default=None, ge=10, le=120)
    budget: int | None = Field(default=None, ge=1000, le=100000)
    cuisine: Literal["전체", "한식", "중식", "일식", "양식", "샐러드"] | None = None
    diet: Literal["any", "vegetarian", "vegan"] | None = None
    spicy: bool | None = None
    radius_m: int | None = Field(default=None, ge=50, le=500)


class QuestionInterpretation(BaseModel):
    """Groq가 제안할 수 있는 실행 계획. 실제 식당 사실은 포함하지 않는다."""

    model_config = ConfigDict(extra="forbid", strict=True)
    intent: Literal[
        "recommend_menu", "reroll_menu", "search_restaurants", "ask_menu_detail",
        "ask_restaurant_detail", "change_conditions", "clarify", "out_of_scope",
        # 기존 테스트와 단계 전환 중 입력만 허용하며 v2 프롬프트는 생성하지 않는다.
        "explain_menu",
    ]
    menu_id: str | None = Field(default=None, max_length=40)
    restaurant_id: str | None = Field(default=None, max_length=40)
    requested_detail: Literal["price", "hours", "address", "menu", "reason"] | None = None
    condition_patch: ConditionPatch = Field(default_factory=ConditionPatch)
    search_after_change: bool = False
    clarification: str | None = Field(default=None, min_length=1, max_length=200)
    clarification_kind: Literal[
        "ambiguous", "radius", "budget", "location", "unsupported", "conflict",
        "menu", "restaurant",
    ] | None = None

    @field_validator("menu_id")
    @classmethod
    def known_menu(cls, value: str | None, info: ValidationInfo) -> str | None:
        """현재 활성 카탈로그에 없는 메뉴 ID 생성을 거부한다."""

        if value is not None and value not in (info.context or {}).get("menu_ids", set()):
            raise ValueError("현재 메뉴 카탈로그에 없는 ID입니다.")
        return value

    @field_validator("restaurant_id")
    @classmethod
    def known_restaurant(cls, value: str | None, info: ValidationInfo) -> str | None:
        """현재 세션의 추천·후보 목록 밖 식당을 임의로 선택하지 못하게 한다."""

        allowed = (info.context or {}).get("restaurant_ids", set())
        if value is not None and value not in allowed:
            raise ValueError("현재 대화의 식당 목록에 없는 ID입니다.")
        return value

    @model_validator(mode="after")
    def consistent_plan(self):
        """의도와 대상·조건·상세질문 필드가 서로 모순되지 않게 한다."""

        has_patch = bool(self.condition_patch.model_dump(exclude_none=True))
        if has_patch != (self.intent == "change_conditions"):
            raise ValueError("조건 변경 의도와 변경 항목이 일치해야 합니다.")
        if self.search_after_change and self.intent != "change_conditions":
            raise ValueError("변경 후 검색은 조건 변경 의도에서만 사용할 수 있습니다.")

        menu_intents = {"search_restaurants", "ask_menu_detail", "explain_menu"}
        if self.menu_id is not None and self.intent not in menu_intents:
            raise ValueError("이 의도에는 메뉴 ID를 지정할 수 없습니다.")
        if self.intent in {"ask_menu_detail", "explain_menu"} and self.menu_id is None:
            raise ValueError("설명할 메뉴 ID가 필요합니다.")

        if self.intent == "ask_restaurant_detail":
            if self.restaurant_id is None or self.requested_detail is None:
                raise ValueError("식당 상세질문에는 식당과 조회 항목이 필요합니다.")
        elif self.restaurant_id is not None or self.requested_detail is not None:
            raise ValueError("식당 대상과 상세 항목은 식당 상세질문에서만 사용합니다.")

        if self.intent == "clarify":
            if self.clarification_kind is None and not (
                self.clarification and self.clarification.strip()
            ):
                raise ValueError("확인할 질문 유형이 필요합니다.")
        elif self.clarification is not None or self.clarification_kind is not None:
            raise ValueError("확인 정보는 clarify 의도에서만 허용합니다.")
        return self


def parse_interpretation(raw: str, menu_ids: set[str],
                         restaurant_ids: set[str] | None = None) -> QuestionInterpretation:
    """중복 키·비표준 숫자를 먼저 차단한 뒤 Pydantic 의미 검증을 수행한다."""

    def unique_keys(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError("중복된 JSON 키입니다.")
            result[key] = value
        return result

    def reject_constant(_value):
        raise ValueError("유한한 JSON 숫자만 허용합니다.")

    json.loads(raw, object_pairs_hook=unique_keys, parse_constant=reject_constant)
    return QuestionInterpretation.model_validate_json(
        raw,
        context={"menu_ids": menu_ids, "restaurant_ids": restaurant_ids or set()},
    )


def _history(value: list[dict] | None) -> list[dict[str, str]]:
    """Groq에는 검증 가능한 문자열의 최신 10턴만 데이터로 전달한다."""

    result: list[dict[str, str]] = []
    for item in (value or [])[-10:]:
        if not isinstance(item, dict):
            continue
        user = item.get("user_message")
        assistant = item.get("assistant_message")
        if isinstance(user, str) and isinstance(assistant, str):
            result.append({"user": user[:500], "assistant": assistant[:1000]})
    return result


def _places(value: list[dict] | None) -> list[dict[str, str]]:
    """식당 사실 대신 대상 식별에 필요한 ID와 이름만 Groq에 전달한다."""

    result: list[dict[str, str]] = []
    for item in (value or [])[:15]:
        if isinstance(item, dict) and isinstance(item.get("id"), str) \
                and isinstance(item.get("name"), str):
            result.append({"id": item["id"], "name": item["name"][:200]})
    return result


def build_interpretation_messages(
    message: str,
    conditions: dict,
    radius_m: int,
    menus: list[dict],
    selected_menu_id: str | None = None,
    *,
    conversation_history: list[dict] | None = None,
    restaurants: list[dict] | None = None,
    candidate_restaurants: list[dict] | None = None,
    pending_action: dict | None = None,
) -> list[dict]:
    """v2 시스템 지침과 세션 문맥을 서로 다른 메시지로 구성한다."""

    examples = json.loads(EXAMPLES_FILE.read_text(encoding="utf-8"))
    system = SYSTEM_PROMPT_FILE.read_text(encoding="utf-8")
    system += "\n출력 JSON Schema:\n" + json.dumps(
        QuestionInterpretation.model_json_schema(), ensure_ascii=False
    )
    system += "\n해석 예시:\n" + json.dumps(examples, ensure_ascii=False)
    selected = next(
        ({"id": menu["id"], "name": menu["name"]}
         for menu in menus if menu.get("id") == selected_menu_id),
        None,
    )
    context = {
        "question": message,
        "conversation_history": _history(conversation_history),
        "current_conditions": conditions,
        "radius_m": radius_m,
        "selected_menu": selected,
        "recent_restaurants": _places(restaurants),
        "candidate_restaurants": _places(candidate_restaurants),
        "pending_action": pending_action,
        "menus": [{"id": menu["id"], "name": menu["name"]} for menu in menus],
    }
    return [
        {"role": "system", "content": system},
        {"role": "user", "content": json.dumps(context, ensure_ascii=False)},
    ]
