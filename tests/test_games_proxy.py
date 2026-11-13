"""Verify that the backend serves the standalone game through /games."""

import unittest
from unittest.mock import patch

import httpx
from fastapi.testclient import TestClient

from app.main import app


class StubProxyClient:
    def __init__(self, response=None, error=None):
        self.response = response or httpx.Response(
            200, content=b"game response", headers={"content-type": "text/plain"}
        )
        self.error = error
        self.request_args = None

    async def request(self, method, url, **kwargs):
        self.request_args = (method, url, kwargs)
        if self.error:
            raise self.error
        return self.response


class GamesProxyTests(unittest.TestCase):
    def setUp(self):
        # 6단계: 배포 주소 설정과 독립적으로 프록시 전달 규칙만 검증한다.
        origin_patch=patch('games.app.NODE_ORIGIN','http://127.0.0.1:4174')
        origin_patch.start()
        self.addCleanup(origin_patch.stop)
        self.original_proxy_client = getattr(app.state, "proxy_client", None)
        self.proxy_client = StubProxyClient()
        app.state.proxy_client = self.proxy_client
        self.client = TestClient(app)
        self.addCleanup(self.client.close)
        self.addCleanup(self._restore_proxy_client)

    def _restore_proxy_client(self):
        if self.original_proxy_client is None:
            del app.state.proxy_client
        else:
            app.state.proxy_client = self.original_proxy_client

    def test_games_root_redirect_preserves_query(self):
        response = self.client.get("/games?room=123456", follow_redirects=False)
        self.assertEqual(response.status_code, 307)
        self.assertEqual(response.headers["location"], "/games/?room=123456")

    def test_games_root_proxies_node_page(self):
        response = self.client.get("/games/")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.content, b"game response")
        method, url, kwargs = self.proxy_client.request_args
        self.assertEqual((method, url), ("GET", "http://127.0.0.1:4174/"))
        self.assertEqual(kwargs["headers"]["x-forwarded-prefix"], "/games")

    def test_games_api_forwards_path_query_headers_and_body(self):
        response = self.client.post(
            "/games/api/rooms?source=invite",
            content=b'{"nickname":"guest"}',
            headers={"content-type": "application/json", "authorization": "Bearer token"},
        )
        self.assertEqual(response.status_code, 200)
        method, url, kwargs = self.proxy_client.request_args
        self.assertEqual(
            (method, url),
            ("POST", "http://127.0.0.1:4174/api/rooms?source=invite"),
        )
        self.assertEqual(kwargs["content"], b'{"nickname":"guest"}')
        self.assertEqual(kwargs["headers"]["authorization"], "Bearer token")
        self.assertEqual(kwargs["headers"]["x-forwarded-prefix"], "/games")

    def test_node_unavailable_returns_gateway_error(self):
        app.state.proxy_client = StubProxyClient(error=httpx.ConnectError("offline"))
        response = self.client.get("/games/")
        self.assertEqual(response.status_code, 502)
        self.assertIn("Node.js 서버가 실행 중인지", response.json()["detail"])


if __name__ == "__main__":
    unittest.main()
