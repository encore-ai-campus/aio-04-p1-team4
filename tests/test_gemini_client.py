"""실제 네트워크 없이 Gemini 요청·오류·응답 검증을 검사합니다."""
import json
import unittest

import httpx

from app.clients.gemini import GeminiClient, GeminiError
from app.config import Settings
from app.schemas import Conditions
from app.database.seed import DEFAULT_MENU_CATALOG


MENUS = [dict(item) for item in DEFAULT_MENU_CATALOG]


def completion(content=None, finish="stop"):
    # 테스트용 응답만 생성하고 실제 키나 사용자 질문은 기록하지 않습니다.
    if content is None:
        content = json.dumps({"intent":"recommend_menu", "condition_patch":{}})
    return {"choices":[{"finish_reason":finish,"message":{"content":content}}]}


class GeminiClientTests(unittest.IsolatedAsyncioTestCase):
    def settings(self, **kwargs):
        return Settings(map_api_key="fake-map", gemini_api_key="fake-gemini", **kwargs)

    async def invoke(self, handler, settings=None):
        client = GeminiClient(settings or self.settings(), transport=httpx.MockTransport(handler))
        return await client.interpret("점심 추천", Conditions(), 500, MENUS)

    async def test_request_and_validated_response(self):
        def handler(request):
            body = json.loads(request.content)
            self.assertEqual(request.headers["Authorization"], "Bearer fake-gemini")
            self.assertEqual(str(request.url), GeminiClient.URL)
            self.assertEqual(body["max_completion_tokens"], 2048)
            self.assertEqual(body["response_format"], {"type":"json_object"})
            self.assertNotIn("reasoning_effort", body)
            self.assertNotIn("include_reasoning", body)
            context = json.loads(body["messages"][1]["content"])
            self.assertNotIn("location", context)
            self.assertEqual(context["radius_m"], 500)
            return httpx.Response(200, json=completion())
        self.assertEqual((await self.invoke(handler)).intent, "recommend_menu")

    async def test_missing_key_never_calls_upstream(self):
        def handler(request):
            self.fail("키가 없으면 호출하면 안 됩니다.")
        settings = Settings(map_api_key="fake-map")
        with self.assertRaises(GeminiError) as error:
            await self.invoke(handler, settings)
        self.assertEqual(error.exception.code, "gemini_config")
        self.assertNotIn("fake-gemini", repr(self.settings()))

    async def test_status_errors_sanitized_without_retry(self):
        for status, code in [(401,"gemini_auth"),(403,"gemini_permission"),(429,"gemini_rate_limit"),
                             (400,"gemini_request"),(404,"gemini_model"),(500,"gemini_upstream"),(302,"gemini_upstream")]:
            calls = []
            def handler(request):
                calls.append(request)
                return httpx.Response(status, json={"error":"private-secret"})
            with self.subTest(status=status), self.assertRaises(GeminiError) as error:
                await self.invoke(handler)
            self.assertEqual(error.exception.code, code)
            self.assertNotIn("private-secret", str(error.exception))
            self.assertEqual(len(calls), 1)

    async def test_timeout_and_connection(self):
        for kind, code in [(httpx.ReadTimeout,"gemini_timeout"),(httpx.ConnectError,"gemini_connection")]:
            def handler(request):
                raise kind("private-secret", request=request)
            with self.subTest(code=code), self.assertRaises(GeminiError) as error:
                await self.invoke(handler)
            self.assertEqual(error.exception.code, code)
            self.assertNotIn("private-secret", str(error.exception))

    async def test_bad_payload_and_token_truncation(self):
        malformed = [
            {},
            {"choices":[]},
            completion("not-json"),
            completion(json.dumps({"intent":"explain_menu","menu_id":"unknown"})),
            completion(json.dumps({"intent":"recommend_menu","restaurants":[]})),
            completion(finish="tool_calls"),
        ]
        for data in malformed:
            calls = []
            def handler(request):
                calls.append(request)
                return httpx.Response(200, json=data)
            with self.subTest(data=data):
                result = await self.invoke(handler)
                # 형식 오류를 두 번 받아도 검색 실행 대신 안전한 확인 의도로 낮춘다.
                self.assertEqual(result.intent, "clarify")
                self.assertEqual(result.clarification_kind, "ambiguous")
                self.assertEqual(len(calls), 2)

        calls = []
        with self.assertRaises(GeminiError) as error:
            await self.invoke(
                lambda request: (
                    calls.append(request)
                    or httpx.Response(200, json=completion(finish="length"))
                )
            )
        self.assertEqual(error.exception.code, "gemini_truncated")
        self.assertEqual(len(calls), 1)
