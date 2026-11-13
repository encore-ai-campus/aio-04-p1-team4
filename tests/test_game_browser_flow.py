"""Real Chromium + Node + FastAPI; only external restaurant lookup is stubbed."""
import json
import shutil
import socket
import subprocess
import threading
import time
from pathlib import Path
from unittest.mock import AsyncMock, patch

import httpx
import uvicorn
from playwright.sync_api import sync_playwright

from app.database import Database, MenuCatalog
from app.main import app
import games.app as games_proxy


def free_port():
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def select_game(page, name):
    if page.url.split('?',1)[0].rstrip('/').endswith('/play'):
        page.locator('.stage-dock [data-shell="game"]').click()
    page.locator(f'[data-game="{name}"]').click()
    page.wait_for_url('**/games/play*')


def test_games_use_backend_candidates_and_search_only_after_confirmation(tmp_path, monkeypatch):
    root = Path(__file__).resolve().parents[1]
    api_port, node_port = free_port(), free_port()
    api_url, node_url = f"http://127.0.0.1:{api_port}", f"http://127.0.0.1:{node_port}"
    database = Database(f"sqlite:///{(tmp_path / 'browser.db').as_posix()}")
    database.init_schema()
    from test_db_first_flow import add_place
    with database.session_factory.begin() as session:
        add_place(session, "test-place", price=8000, latitude=37.48, longitude=126.88)
    monkeypatch.setattr(app.state, "database", database)
    monkeypatch.setattr(games_proxy, "NODE_ORIGIN", node_url)
    import os
    env = {**os.environ, "PORT": str(node_port), "HOST": "127.0.0.1", "BACKEND_ORIGIN": api_url,
           "ROOM_STORE_FILE": str(tmp_path / "rooms.json")}
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=api_port, log_level="error"))
    thread = threading.Thread(target=server.run, daemon=True)
    node = None
    thread.start()
    try:
        for _ in range(100):
            if server.started:
                break
            time.sleep(.05)
        assert server.started
        node = subprocess.Popen([shutil.which("node"), "games/server.mjs"], cwd=root, env=env,
                                stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
        for _ in range(100):
            try:
                if httpx.get(node_url + "/api/network").status_code == 200:
                    break
            except httpx.HTTPError:
                time.sleep(.05)
        settings = {"budget": 9000, "time": 30, "distance": 500, "people": 1,
                    "categories": ["중식"], "origin": {"latitude": 37.48, "longitude": 126.88}}
        lookup = AsyncMock(return_value={"items": [], "has_more": False})
        with patch("app.clients.kakao.KakaoClient.search_restaurants", lookup), sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page(reduced_motion="reduce", viewport={"width": 1440, "height": 1000})
            errors = []
            page.on("pageerror", lambda e: errors.append(str(e)) if 'ViewTransition' not in str(e) else None)
            page.add_init_script("sessionStorage.setItem('lunchrun-games-settings'," + json.dumps(json.dumps(settings)) + ");")
            page.route('https://dapi.kakao.com/**', lambda route: route.fulfill(content_type='application/javascript', body=(root/'tests/map-sdk-stub.js').read_text(encoding='utf-8')))
            page.goto(api_url + "/games/")
            page.wait_for_function("document.querySelector('#candidate-count').textContent === '1개'")
            page.locator('[data-mode="solo"]').click()
            page.wait_for_function("document.querySelector('#candidate-count').textContent === '1개'")
            select_game(page, 'random')
            page.locator('[data-action="play"]').click()
            page.wait_for_function("document.querySelector('#game-badge').textContent !== 'SURPRISE ME'")
            lookup.assert_not_awaited()
            for game in ["gacha", "draw", "ticket"]:
                select_game(page, game)
                if game == "gacha":
                    page.locator('[data-action="play"]').click()
                    page.locator('[data-action="open-capsule"]').first.click()
                else:
                    page.locator('[data-draw="0"]' if game == "draw" else '[data-ticket="0"]').click()
                page.wait_for_selector('.result-title')
                assert page.locator('.result-title').inner_text() == "짜장면"
                lookup.assert_not_awaited()
                if game != "ticket":
                    page.locator('[data-action="again"]').click()
            page.route('**/api/recommendations', lambda route: route.fulfill(
                status=503, content_type='application/json', body=json.dumps({'detail': 'search temporarily unavailable'})))
            page.locator('[data-action="find"]').click()
            page.wait_for_url('**/map/**')
            page.wait_for_function("document.querySelector('#search-status')?.textContent === 'search temporarily unavailable'")
            assert page.evaluate('window.LunchRunState.read().menu.id') == 'noodle'
            page.unroute('**/api/recommendations')
            page.locator('#map-conditions').evaluate('f=>f.requestSubmit()')
            page.wait_for_function("document.querySelector('#search-status')?.textContent && document.querySelector('#search-status').textContent !== 'DB에서 메뉴·가격·영업 조건에 맞는 식당 조회 중…'")
            lookup.assert_not_awaited()
            page.goto(api_url+'/games/')
            page.goto(api_url+'/games/play')
            page.wait_for_selector('.result-title')
            page.locator('.stage-dock [data-shell="game"]').click()
            page.locator('[data-mode="group"]').click()
            select_game(page, 'roulette')
            page.wait_for_function("document.querySelector('#candidate-count').textContent === '1개'")
            page.locator('[data-entry="0"]').fill("피자")
            page.locator('[data-action="play"]').click()
            assert page.locator('#toast').inner_text() == "현재 조건의 후보 메뉴명만 입력해주세요."
            for i in range(2):
                page.locator(f'[data-entry="{i}"]').fill("짜장면")
            page.locator('[data-action="play"]').click()
            page.wait_for_selector('.result-title')
            assert page.locator('.result-title').inner_text() == "짜장면"
            page.locator('[data-action="again"]').click()
            select_game(page, 'ladder')
            page.locator('[data-ladder-start="0"]').click()
            page.wait_for_function("document.querySelectorAll('[data-ladder-start]:disabled').length > 0 || !!document.querySelector('.result-title')")
            page.wait_for_function("!document.querySelector('.play-board').getAttribute('aria-busy') || document.querySelector('.play-board').getAttribute('aria-busy') === 'false'")
            if not page.locator('.result-title').count():
                page.locator('[data-ladder-start="1"]').click()
            page.wait_for_selector('.result-title')
            assert page.locator('.result-title').inner_text() == "짜장면"
            page.locator('[data-action="again"]').click()
            page.evaluate("()=>{window.LunchRunState.setMenu({id:'noodle',name:'짜장면'});}")
            page.goto(api_url+'/map/?search=1')
            page.wait_for_function("document.querySelector('#search-status')?.textContent && document.querySelector('#search-status').textContent !== 'DB에서 메뉴·가격·영업 조건에 맞는 식당 조회 중…'")
            lookup.assert_not_awaited()
            page.screenshot(path=str(tmp_path / 'game-restaurants.png'), full_page=True)
            # Verify list/real-coordinate overlay wiring and cached result restoration.
            page.evaluate('''()=>{const s=window.LunchRunState.read();window.LunchRunState.setRestaurants({
                restaurants:[{id:'verified-1',name:'검증식당',lat:37.481,lng:126.881,address:'서울 테스트로',phone:'02-000-0000',menu_name:'짜장면',price:8000,place_url:'https://place.map.kakao.com/1'}],
                candidate_restaurants:[{id:'candidate-1',name:'확인필요식당',lat:37.482,lng:126.882,address:'서울 후보로',price:null,warnings:['가격 확인 불가']}]
            },s.contextRevision,s.menu.id);}''')
            page.reload()
            page.wait_for_selector('.backend-map-pin[aria-label="검증식당"]')
            assert page.locator('#count').inner_text() == '추천 1 · 확인 필요 1'
            assert '이전 조회 결과' in page.locator('#search-status').inner_text()
            page.locator('[data-restaurant="candidate-1"]').click()
            assert '가격 미확인' in page.locator('[data-restaurant="candidate-1"]').inner_text()
            assert '서울 후보로' in page.locator('.restaurant-details').inner_text()
            page.locator('.backend-map-pin[aria-label="검증식당"]').click()
            assert '8,000원' in page.locator('[data-restaurant="verified-1"]').inner_text()
            assert page.locator('[data-restaurant="verified-1"]').get_attribute('aria-pressed') == 'true'
            page.locator('#random').click()
            page.wait_for_function("document.querySelector('#search-status').textContent.startsWith('선택 완료!')")
            assert page.evaluate('window.LunchRunState.read().selectedRestaurantId') == 'verified-1'
            page.route('**/map/api/restaurants/verified-1', lambda route: route.fulfill(content_type='application/json', body=json.dumps({
                'id':'verified-1','open_status':'open','checked_at':None,'menus':[{'name':'짜장면','price':8000,'price_status':'known'}],
                'business_hours':[{'day':0,'holiday':False,'start':'09:00','end':'21:00','next_day':False,'last_order':'20:30'}]})))
            page.locator('[data-restaurant="verified-1"]').click()
            page.wait_for_function("document.querySelector('.restaurant-hours')?.textContent.includes('09:00 ~ 21:00')")
            page.route('**/map/api/walking-route',lambda route: route.fulfill(content_type='application/json',body=json.dumps({
                'distance':200,'duration':180,'paths':[[[126.88,37.48],[126.881,37.481]]],'steps':['직진']})))
            page.locator('#confirm-route').click()
            page.wait_for_function("window.LunchRunState.read().route?.distance === 200")
            assert '도보 약 3분' in page.locator('#search-status').inner_text()
            assert '200m' in page.locator('.route-focus-summary').inner_text()
            page.locator('#random').click()
            assert page.evaluate('window.LunchRunState.read().route') is None
            page.screenshot(path=str(tmp_path / 'map-connected.png'), full_page=True)
            assert not errors, errors
            browser.close()
        # The actual Node room endpoint must obtain the same server candidate ID.
        room = httpx.post(node_url + "/api/rooms", json={"nickname": "host", "filters": {
            "location": "현재 위치", "origin": [37.48, 126.88], "budget": 9000,
            "time": 30, "distance": 500, "categories": ["중식"]}})
        assert room.status_code == 201, room.text
        auth = room.json()
        view = httpx.get(node_url + "/api/rooms/" + auth["code"], headers={"Authorization": "Bearer " + auth["token"]}).json()
        assert [m["id"] for m in view["menus"]] == ["noodle"]
        assert view["filters"]["categories"] == ["중식"]
        httpx.post(node_url + '/api/rooms/' + auth['code'] + '/join', json={'nickname':'candidate-check'})
        with database.session_factory.begin() as session:
            session.get(MenuCatalog, 'noodle').active = False
        rejected = httpx.post(node_url + '/api/rooms/' + auth['code'] + '/start',
                              headers={'Authorization':'Bearer ' + auth['token']}, json={'round':1})
        assert rejected.status_code == 409
        assert '후보가 바뀌었습니다' in rejected.json()['error']
    finally:
        if node:
            node.terminate()
            node.wait(timeout=10)
        server.should_exit = True
        thread.join(timeout=10)
        database.dispose()
