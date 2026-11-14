"""Gemini v2 최근 문맥 전달과 형식 오류 1회 재요청 검증."""

import json
import unittest

import httpx

from app.clients.gemini import GeminiClient
from app.config import Settings
from app.schemas import Conditions
from app.database.seed import DEFAULT_MENU_CATALOG


MENUS = [dict(item) for item in DEFAULT_MENU_CATALOG]


def completion(content):
    return {"choices": [{"finish_reason": "stop", "message": {"content": content}}]}


class GeminiContextTests(unittest.IsolatedAsyncioTestCase):
    async def test_history_targets_and_pending_are_sent_as_data(self):
        requests = []

        def handler(request):
            requests.append(json.loads(request.content))
            return httpx.Response(
                200,
                json=completion(json.dumps({
                    "intent": "ask_restaurant_detail",
                    "restaurant_id": "r1",
                    "requested_detail": "price",
                    "condition_patch": {},
                })),
            )

        client = GeminiClient(
            Settings(map_api_key="map", gemini_api_key="gemini"),
            transport=httpx.MockTransport(handler),
        )
        result = await client.interpret(
            "첫 번째 가격은?",
            Conditions(),
            500,
            MENUS,
            "noodle",
            conversation_history=[{
                "user_message": "짜장면 식당 찾아줘",
                "assistant_message": "식당을 찾았어요.",
            }],
            restaurants=[{"id": "r1", "name": "테스트 식당", "price": 8000}],
            pending_action={"kind": "select_restaurant", "restaurant_ids": ["r1"]},
        )
        assert result.restaurant_id == "r1"
        context = json.loads(requests[0]["messages"][1]["content"])
        assert context["conversation_history"][0]["user"] == "짜장면 식당 찾아줘"
        assert context["recent_restaurants"] == [{"id": "r1", "name": "테스트 식당"}]
        assert "price" not in context["recent_restaurants"][0]
        assert context["pending_action"]["kind"] == "select_restaurant"

    async def test_invalid_first_response_is_retried_once_without_echoing_it(self):
        bodies = []

        def handler(request):
            body = json.loads(request.content)
            bodies.append(body)
            if len(bodies) == 1:
                return httpx.Response(200, json=completion("PRIVATE_INVALID_RAW"))
            return httpx.Response(
                200,
                json=completion(json.dumps({"intent": "reroll_menu", "condition_patch": {}})),
            )

        client = GeminiClient(
            Settings(map_api_key="map", gemini_api_key="gemini"),
            transport=httpx.MockTransport(handler),
        )
        result = await client.interpret("다른 메뉴", Conditions(), 500, MENUS)
        assert result.intent == "reroll_menu"
        assert len(bodies) == 2
        assert "PRIVATE_INVALID_RAW" not in json.dumps(bodies[1], ensure_ascii=False)
        assert "Schema" in bodies[1]["messages"][-1]["content"]
