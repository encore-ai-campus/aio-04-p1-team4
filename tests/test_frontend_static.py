from fastapi.testclient import TestClient

from app.main import app


def test_frontend_and_its_relative_assets_are_served_from_root():
    client = TestClient(app)
    try:
        for path in (
            "/",
            "/conditions",
            "/ai",
            "/budget",
            "/time",
            "/distance",
            "/people",
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


def test_plain_routes_redirect_legacy_paths_and_keep_api_boundaries():
    with TestClient(app) as client:
        assert client.get('/conditions', follow_redirects=False).headers['location'] == '/'
        assert client.get('/restaurants', follow_redirects=False).headers['location'] == '/map/'
        assert client.get('/route', follow_redirects=False).headers['location'] == '/map/'
        assert '<base href="/"' in client.get('/ai').text
        assert client.get('/api/not-an-endpoint').status_code == 404
        assert client.get('/not-an-app-page').status_code == 404


def test_frontend_config_uses_demo_mode_without_caching():
    client = TestClient(app)
    try:
        response = client.get("/config.json")
        assert response.json() == {"apiBase": ""}
        assert response.headers["cache-control"] == "no-store"
    finally:
        client.close()
