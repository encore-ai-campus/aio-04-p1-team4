"""4단계 v2 의도·대상 계약과 세션 문맥 입력 검증."""

import json

import pytest
from pydantic import ValidationError

from app.chat_policy import (
    EXAMPLES_FILE,
    REPLIES_FILE,
    SYSTEM_PROMPT_FILE,
    build_interpretation_messages,
    load_replies,
    parse_interpretation,
)
from app.database.seed import DEFAULT_MENU_CATALOG


# 운영 코드는 DB를 읽고, 파일 단위 테스트만 같은 초기화 원본을 가벼운 입력으로 사용한다.
MENUS = [dict(item) for item in DEFAULT_MENU_CATALOG]


MENU_IDS = {item["id"] for item in MENUS}
RESTAURANT_IDS = {"restaurant-1", "restaurant-2"}


def test_v2_files_and_examples_follow_latest_contract():
    # 삭제한 채식·맵기 필터를 제안하지 않는 최신 프롬프트만 사용한다.
    assert SYSTEM_PROMPT_FILE.name == "system_v4.txt"
    assert REPLIES_FILE.name == "replies_v4.json"
    assert "restaurant" in load_replies()
    examples = json.loads(EXAMPLES_FILE.read_text(encoding="utf-8"))
    for example in examples:
        parsed = parse_interpretation(
            json.dumps(example["expected"], ensure_ascii=False),
            MENU_IDS,
            RESTAURANT_IDS,
        )
        assert parsed.intent == example["expected"]["intent"]


def test_removed_diet_and_spicy_conditions_are_rejected():
    # 화면에서 삭제한 조건이 모델의 변경안으로 다시 들어오지 않게 한다.
    for patch in ({"diet": "vegan"}, {"spicy": False}):
        with pytest.raises(ValidationError):
            parse_interpretation(
                json.dumps({"intent": "change_conditions", "condition_patch": patch}),
                MENU_IDS,
            )


def test_new_intents_require_known_targets_and_matching_fields():
    valid = parse_interpretation(
        json.dumps({
            "intent": "ask_restaurant_detail",
            "restaurant_id": "restaurant-1",
            "requested_detail": "price",
            "condition_patch": {},
        }),
        MENU_IDS,
        RESTAURANT_IDS,
    )
    assert valid.restaurant_id == "restaurant-1"

    invalid = [
        {"intent": "ask_restaurant_detail", "restaurant_id": "unknown", "requested_detail": "price"},
        {"intent": "ask_restaurant_detail", "restaurant_id": "restaurant-1"},
        {"intent": "recommend_menu", "restaurant_id": "restaurant-1"},
        {"intent": "reroll_menu", "menu_id": "noodle"},
        {"intent": "ask_menu_detail"},
        {"intent": "recommend_menu", "search_after_change": True},
        {"intent": "change_conditions", "condition_patch": {"budget": 9000}, "restaurant_id": "restaurant-1"},
    ]
    for value in invalid:
        with pytest.raises(ValidationError):
            parse_interpretation(json.dumps(value), MENU_IDS, RESTAURANT_IDS)


def test_context_contains_only_latest_ten_turns_and_safe_place_identity():
    history = [
        {"user_message": f"질문 {index}", "assistant_message": f"답변 {index}"}
        for index in range(12)
    ]
    messages = build_interpretation_messages(
        "첫 번째 가격은?",
        {"budget": 12000, "cuisine": "전체"},
        500,
        MENUS,
        "noodle",
        conversation_history=history,
        restaurants=[{"id": "restaurant-1", "name": "예시 식당", "price": 8000}],
        pending_action={"kind": "select_restaurant", "restaurant_ids": ["restaurant-1"]},
    )
    context = json.loads(messages[1]["content"])
    assert len(context["conversation_history"]) == 10
    assert context["conversation_history"][0]["user"] == "질문 2"
    assert context["selected_menu"] == {"id": "noodle", "name": "짜장면"}
    assert context["recent_restaurants"] == [{"id": "restaurant-1", "name": "예시 식당"}]
    assert "price" not in context["recent_restaurants"][0]
    assert "lat" not in context and "lng" not in context and "location" not in context
    assert "첫 번째 가격은?" not in messages[0]["content"]


def test_condition_change_and_clarification_are_not_mixed():
    with pytest.raises(ValidationError):
        parse_interpretation(
            json.dumps({
                "intent": "clarify",
                "clarification_kind": "radius",
                "condition_patch": {"radius_m": 300},
            }),
            MENU_IDS,
        )
    parsed = parse_interpretation(
        json.dumps({
            "intent": "change_conditions",
            "condition_patch": {"radius_m": 300},
            "search_after_change": True,
        }),
        MENU_IDS,
    )
    assert parsed.search_after_change is True
