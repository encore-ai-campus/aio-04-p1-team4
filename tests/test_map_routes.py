"""지도 라우팅·정적 자원·키 분리·경로 API 연결을 외부 호출 없이 검증한다."""

import unittest
from html.parser import HTMLParser
from types import SimpleNamespace
from unittest.mock import patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.config import Settings
from app.map_routes import PROJECT_ROOT, router, walking


class AssetParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.assets = []

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == "script" and attrs.get("src"):
            self.assets.append(attrs["src"])
        if tag == "link" and attrs.get("rel") == "stylesheet":
            self.assets.append(attrs["href"])


class MapRouteTests(unittest.TestCase):
    def setUp(self):
        app = FastAPI()
        app.state.settings = Settings(
            map_api_key="test-private-rest-key",
            kakao_javascript_key="test-public-js-key",
        )
        app.include_router(router)
        from fastapi.staticfiles import StaticFiles
        app.mount('/static', StaticFiles(directory=PROJECT_ROOT / 'frontend'), name='static')
        self.client = TestClient(app)
        self.addCleanup(self.client.close)

    def test_map_redirect_and_all_page_assets(self):
        response = self.client.get("/map", follow_redirects=False)
        self.assertEqual(response.status_code, 307)
        self.assertEqual(response.headers["location"], "/map/")
        for page in ("/map/", "/map/menu-catalog.html"):
            response = self.client.get(page)
            self.assertEqual(response.status_code, 200)
            self.assertIn("text/html", response.headers["content-type"])
            parser = AssetParser()
            parser.feed(response.text)
            self.assertTrue(parser.assets)
            for asset in parser.assets:
                if asset.startswith(("https://", "http://")):
                    continue
                with self.subTest(asset=asset):
                    self.assertEqual(self.client.get(asset if asset.startswith('/') else "/map/" + asset).status_code, 200)

    def test_only_public_key_is_exposed(self):
        response = self.client.get("/map/config.json")
        self.assertEqual(response.json(), {"javascriptKey": "test-public-js-key"})
        self.assertEqual(response.headers["cache-control"], "no-store")
        self.assertNotIn("test-private-rest-key", response.text)

    def test_non_web_files_and_missing_assets_are_not_served(self):
        for asset in ("serve.py", "walk_routes.py", ".env", "missing.js", "pj.code-workspace"):
            with self.subTest(asset=asset):
                self.assertEqual(self.client.get("/map/" + asset).status_code, 404)

    def test_walking_route_reuses_server_key_and_result(self):
        body = {
            "origin": {"lat": 37.48, "lng": 126.88},
            "destination": {"lat": 37.49, "lng": 126.89},
        }
        result = {"distance": 100, "duration": 90, "paths": [], "steps": []}
        with patch.object(walking, "walking_route", return_value=result) as route:
            response = self.client.post(
                "/map/api/walking-route", json=body, headers={"Origin": "http://testserver"}
            )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), result)
        route.assert_called_once_with(body, PROJECT_ROOT, api_key="test-private-rest-key")

    def test_walking_errors_and_invalid_input(self):
        response = self.client.post("/map/api/walking-route", json={})
        self.assertEqual(response.status_code, 400)
        self.assertIn("error", response.json())
        self.assertEqual(
            self.client.post("/map/api/walking-route", json=[]).status_code, 422
        )
        with patch.object(walking, "walking_route", side_effect=walking.RouteError("unavailable", 503)):
            response = self.client.post("/map/api/walking-route", json={})
        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.json(), {"error": "unavailable"})

    def test_other_origins_cannot_request_routes(self):
        with patch.object(walking, "walking_route") as route:
            response = self.client.post(
                "/map/api/walking-route", json={}, headers={"Origin": "https://other.example"}
            )
        self.assertEqual(response.status_code, 403)
        route.assert_not_called()
