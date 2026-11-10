"""3단계 메모리 세션, 최근 10턴과 HttpOnly 쿠키 연결 테스트."""

import json
import logging
import unittest
from tempfile import TemporaryDirectory
from unittest.mock import AsyncMock, patch

from fastapi.testclient import TestClient

from app.chat_sessions import (
    SESSION_COOKIE_NAME,
    ChatSessionState,
    InMemoryChatSessionStore,
    PendingAction,
    new_session_id,
    valid_session_id,
)
from app.database import Database
from app.main import app
from app.rate_limit import InMemoryChatRateLimiter
from app.observability import JsonFormatter, request_id_context
from app.schemas import Conditions, SelectedLocation


LOCATION = SelectedLocation(
    lat=37.48,
    lng=126.88,
    name="예시 위치",
    source="place",
)


def response_for(menu_id: str = "noodle") -> dict:
    """세션에 저장할 최소 추천 응답을 실제 API 구조와 맞춘다."""

    return {
        "text": "추천 결과입니다.",
        "suggested_patch": None,
        "result": {
            "menu": {"id": menu_id, "name": "짜장면"},
            "restaurants": [{"id": "recommended-1"}],
            "candidate_restaurants": [{"id": "candidate-1"}],
        },
    }


class MemorySessionTests(unittest.IsolatedAsyncioTestCase):
    async def test_keeps_ten_turns_and_current_state_separately(self):
        store = InMemoryChatSessionStore()
        session_id = new_session_id()
        for index in range(12):
            await store.record_exchange(
                session_id,
                user_message=f"질문 {index}",
                assistant_message=f"답변 {index}",
                conditions=Conditions(budget=9000),
                location=LOCATION,
                radius_m=300,
                requested_menu_id=None,
                response=response_for(),
            )

        state = await store.get(session_id)
        self.assertIsNotNone(state)
        self.assertEqual(len(state.turns), 10)
        self.assertEqual(state.turns[0].user_message, "질문 2")
        self.assertEqual(state.turns[-1].assistant_message, "답변 11")
        self.assertEqual(state.selected_menu_id, "noodle")
        self.assertEqual(state.restaurant_ids, ["recommended-1"])
        self.assertEqual(state.candidate_restaurant_ids, ["candidate-1"])
        self.assertEqual(state.conditions.budget, 9000)
        self.assertEqual(state.radius_m, 300)
        self.assertEqual(state.version, 12)

    async def test_sessions_are_isolated_and_pending_action_is_preserved(self):
        store = InMemoryChatSessionStore()
        first, second = new_session_id(), new_session_id()
        state = ChatSessionState(
            pending_action=PendingAction(
                kind="change_radius",
                original_message="반경을 줄여줘",
                current_value=500,
            )
        )
        await store.put(first, state)

        loaded = await store.get(first)
        self.assertEqual(loaded.pending_action.kind, "change_radius")
        self.assertIsNone(await store.get(second))
        # 반환값을 바꿔도 저장소 원본이 변하지 않는지 확인한다.
        loaded.pending_action = None
        self.assertIsNotNone((await store.get(first)).pending_action)

    async def test_expired_memory_session_is_removed(self):
        now = [100.0]
        store = InMemoryChatSessionStore(ttl_seconds=60, clock=lambda: now[0])
        session_id = new_session_id()
        await store.put(session_id, ChatSessionState())
        self.assertIsNotNone(await store.get(session_id))
        now[0] = 161.0
        self.assertIsNone(await store.get(session_id))

    async def test_rate_limiter_separates_sessions_and_reports_retry(self):
        now = [100.0]
        limiter = InMemoryChatRateLimiter(2, 3, clock=lambda: now[0])
        self.assertTrue((await limiter.check("first")).allowed)
        self.assertTrue((await limiter.check("first")).allowed)
        blocked = await limiter.check("first")
        self.assertFalse(blocked.allowed)
        self.assertGreaterEqual(blocked.retry_after, 1)
        self.assertTrue((await limiter.check("second")).allowed)
        now[0] += 61
        self.assertTrue((await limiter.check("first")).allowed)
        daily = await limiter.check("first")
        self.assertFalse(daily.allowed)

    async def test_json_log_uses_request_id_and_ignores_unapproved_fields(self):
        formatter = JsonFormatter()
        token = request_id_context.set("request-test-id")
        try:
            record = logging.LogRecord(
                "lunchrun.test",
                logging.INFO,
                __file__,
                1,
                "safe_event",
                (),
                None,
            )
            record.event = "test"
            record.api_key = "secret-key"
            record.latitude = 37.48
            record.question = "민감 질문"
            payload = json.loads(formatter.format(record))
        finally:
            request_id_context.reset(token)
        self.assertEqual(payload["request_id"], "request-test-id")
        self.assertNotIn("api_key", payload)
        self.assertNotIn("latitude", payload)
        self.assertNotIn("question", payload)


class ChatSessionApiTests(unittest.TestCase):
    def setUp(self):
        self.original_database = app.state.database
        self.original_store = app.state.chat_sessions
        self.original_limiter = app.state.chat_rate_limiter
        self.temp_directory = TemporaryDirectory()
        self.database = Database(
            f"sqlite:///{self.temp_directory.name.replace(chr(92), '/')}/session.db"
        )
        self.database.init_schema()
        app.state.database = self.database
        app.state.chat_sessions = InMemoryChatSessionStore()
        app.state.chat_rate_limiter = InMemoryChatRateLimiter(100, 1000)
        self.chat_patcher = patch("app.services.chat", new_callable=AsyncMock)
        self.chat = self.chat_patcher.start()
        self.chat.return_value = response_for()
        self.client = TestClient(app)

    def tearDown(self):
        self.client.close()
        self.chat_patcher.stop()
        app.state.database = self.original_database
        app.state.chat_sessions = self.original_store
        app.state.chat_rate_limiter = self.original_limiter
        self.database.dispose()
        self.temp_directory.cleanup()

    def test_chat_sets_cookie_and_session_can_be_restored(self):
        response = self.client.post(
            "/api/chat",
            json={
                "message": "식당 추천해줘",
                "location": LOCATION.model_dump(),
                "radius_m": 500,
                "menu_id": "noodle",
            },
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["session_version"], 1)
        cookie = self.client.cookies.get(SESSION_COOKIE_NAME)
        self.assertIsNotNone(valid_session_id(cookie))
        self.assertIn("HttpOnly", response.headers["set-cookie"])
        self.assertIn("SameSite=lax", response.headers["set-cookie"])

        restored = self.client.get("/api/chat/session")
        self.assertEqual(restored.status_code, 200)
        self.assertEqual(restored.headers["cache-control"], "no-store")
        data = restored.json()
        self.assertTrue(data["exists"])
        self.assertEqual(data["turns"][0]["user_message"], "식당 추천해줘")
        self.assertEqual(data["selected_menu"]["id"], "noodle")
        self.assertEqual(data["restaurant_ids"], ["recommended-1"])
        self.assertEqual(data["candidate_restaurant_ids"], ["candidate-1"])

    def test_invalid_cookie_is_replaced(self):
        # TestClient가 서버 쿠키와 같은 범위에서 변조 쿠키를 보내도록 도메인을 맞춘다.
        self.client.cookies.set(
            SESSION_COOKIE_NAME,
            "not-a-valid-session",
            domain="testserver.local",
            path="/",
        )
        response = self.client.post(
            "/api/chat",
            json={
                "message": "메뉴 추천해줘",
                "location": LOCATION.model_dump(),
                "radius_m": 500,
            },
        )
        self.assertEqual(response.status_code, 200)
        self.assertIsNotNone(
            valid_session_id(self.client.cookies.get(SESSION_COOKIE_NAME))
        )

    def test_second_chat_receives_previous_session_state(self):
        body = {
            "message": "첫 질문",
            "location": LOCATION.model_dump(),
            "radius_m": 500,
            "menu_id": "noodle",
        }
        self.client.post("/api/chat", json=body)
        self.chat.reset_mock()
        self.client.post("/api/chat", json={**body, "message": "두 번째 질문"})
        conversation_state = self.chat.await_args.args[-1]
        self.assertEqual(len(conversation_state.turns), 1)
        self.assertEqual(conversation_state.turns[0].user_message, "첫 질문")
        self.assertEqual(conversation_state.selected_menu_id, "noodle")

    def test_chat_rate_limit_returns_retry_header_before_external_call(self):
        app.state.chat_rate_limiter = InMemoryChatRateLimiter(1, 10)
        body = {
            "message": "첫 요청",
            "location": LOCATION.model_dump(),
            "radius_m": 500,
        }
        self.assertEqual(self.client.post("/api/chat", json=body).status_code, 200)
        self.chat.reset_mock()
        response = self.client.post(
            "/api/chat", json={**body, "message": "두 번째 요청"}
        )
        self.assertEqual(response.status_code, 429)
        self.assertEqual(response.headers["X-Error-Code"], "chat_rate_limit")
        self.assertIn("Retry-After", response.headers)
        self.chat.assert_not_awaited()

    def test_request_id_and_body_size_guard(self):
        response = self.client.get("/api/health", headers={"X-Request-ID": "invalid"})
        self.assertEqual(response.status_code, 200)
        self.assertIsNotNone(valid_session_id(response.headers["X-Request-ID"]))

        oversized = self.client.post(
            "/api/chat",
            content="x" * 70_000,
            headers={"Content-Type": "application/json"},
        )
        self.assertEqual(oversized.status_code, 413)
        self.chat.assert_not_awaited()

    def test_readiness_endpoint_preserves_safe_report_and_status(self):
        report = {
            "status": "not_ready",
            "database_backend": "sqlite",
            "checks": {"playwright_chromium": False},
        }
        with patch("app.api.readiness_report", return_value=(report, 503)):
            response = self.client.get("/api/readiness?refresh=true")
        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.json(), report)
        self.assertEqual(response.headers["Cache-Control"], "no-store")
