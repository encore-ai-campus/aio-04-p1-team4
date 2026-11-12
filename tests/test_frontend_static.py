from fastapi.testclient import TestClient

from app.main import app


def test_frontend_and_its_relative_assets_are_served_from_root():
    client = TestClient(app)
    try:
        for path in (
            "/",
            "/styles.css",
            "/bundle.js",
            "/assets/logo.svg",
            "/assets/screens/01-conditions.png",
            "/gallery.html",
            "/config.json",
            "/api/public-config",
        ):
            response = client.get(path)
            assert response.status_code == 200, path
    finally:
        client.close()


def test_frontend_config_uses_demo_mode_without_caching():
    client = TestClient(app)
    try:
        response = client.get("/config.json")
        assert response.json() == {"apiBase": ""}
        assert response.headers["cache-control"] == "no-store"
    finally:
        client.close()
