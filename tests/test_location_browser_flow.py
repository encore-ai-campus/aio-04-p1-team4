"""Location button -> native mocked Geolocation/search -> game, with real HTTP routes."""
import json
import os
import shutil
import subprocess
import threading
import time
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import AsyncMock, patch
from zoneinfo import ZoneInfo

import httpx
import uvicorn
from playwright.sync_api import sync_playwright

from app.database import Database
from app.main import app
import games.app as games_proxy
from test_game_browser_flow import free_port


def test_location_from_home_to_games_and_reselection(tmp_path, monkeypatch):
    root = Path(__file__).resolve().parents[1]
    api_port, node_port = free_port(), free_port()
    api_url, node_url = f"http://127.0.0.1:{api_port}", f"http://127.0.0.1:{node_port}"
    database = Database(f"sqlite:///{(tmp_path / 'locations.db').as_posix()}")
    monkeypatch.setattr(app.state, 'database', database)
    monkeypatch.setattr(games_proxy, 'NODE_ORIGIN', node_url)
    server = uvicorn.Server(uvicorn.Config(app, host='127.0.0.1', port=api_port, log_level='error'))
    thread = threading.Thread(target=server.run, daemon=True)
    node = None
    thread.start()
    place = {'lat': 37.49, 'lng': 126.89, 'name': '검색한 식사 출발점', 'address': '서울 검색로 10', 'source': 'place'}
    address = {**place, 'lat': 37.50, 'name': '서울 검색로 20', 'address': '서울 검색로 20', 'source': 'address'}
    try:
        for _ in range(100):
            if server.started:
                break
            time.sleep(.05)
        assert server.started
        env = {**os.environ, 'PORT': str(node_port), 'HOST': '127.0.0.1', 'BACKEND_ORIGIN': api_url,
               'ROOM_STORE_FILE': str(tmp_path / 'rooms.json')}
        node = subprocess.Popen([shutil.which('node'), 'games/server.mjs'], cwd=root, env=env,
                                stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
        for _ in range(100):
            try:
                if httpx.get(node_url + '/api/network').status_code == 200:
                    break
            except httpx.HTTPError:
                time.sleep(.05)
        reverse = AsyncMock(return_value={'address': '서울 현재위치로 1'})
        search = AsyncMock(return_value={'items': [place], 'has_more': False})
        addresses = AsyncMock(return_value={'items': [address], 'has_more': False})
        with patch('app.clients.kakao.KakaoClient.reverse_address', reverse), \
             patch('app.clients.kakao.KakaoClient.search_places', search), \
             patch('app.clients.kakao.KakaoClient.search_addresses', addresses), sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            context = browser.new_context(permissions=['geolocation'], geolocation={'latitude': 37.48, 'longitude': 126.88},
                                          viewport={'width': 1516, 'height': 1038}, reduced_motion='reduce')
            page = context.new_page()
            errors, candidates = [], []
            page.on('pageerror', lambda e: errors.append(str(e)))
            page.on('request', lambda r: candidates.append(r.post_data_json) if r.url.endswith('/api/menus/candidates') else None)
            page.goto(api_url)
            reverse.assert_not_awaited()
            page.locator('#location').click()
            page.locator('[data-location-current]').click()
            page.wait_for_function("!document.querySelector('.lr-location-dialog').open")
            reverse.assert_awaited_once_with(37.48, 126.88)
            assert '서울 현재위치로 1' in page.locator('#location').get_attribute('title')
            # Use the existing controls rather than injecting the homepage state.
            page.locator('[data-action="go:budget"]').click()
            page.locator('#budget-input').fill('9000')
            page.locator('[data-action="apply-budget"]').click()
            page.locator('[data-category="중식"]').click()
            page.locator('[data-action="go:time"]').click()
            end = datetime.now(ZoneInfo('Asia/Seoul')) + timedelta(minutes=30)
            page.locator('#period').select_option('PM' if end.hour >= 12 else 'AM')
            page.locator('#end-hour').fill(str(end.hour % 12 or 12))
            page.locator('#end-minute').fill(str(end.minute))
            page.locator('[data-action="apply-time"]').click()
            page.locator('[data-action="go:backend-games"]').click()
            page.wait_for_url('**/games/')
            page.wait_for_function("document.querySelector('#candidate-count').textContent === '1개'")
            assert candidates[-1]['location']['lat'] == 37.48
            assert candidates[-1]['location']['source'] == 'geolocation'
            assert '서울 현재위치로 1' in page.locator('.location-note').inner_text()
            assert page.locator('#location option').count() == 0
            # Select a menu so changing location must invalidate it.
            page.locator('[data-mode="solo"]').click()
            page.wait_for_function("document.querySelector('#candidate-count').textContent === '1개'")
            page.locator('[data-action="play"]').click()
            page.locator('[data-action="open-capsule"]').first.click()
            page.wait_for_selector('.result-title')
            # Same-tab reload and browser back must keep the selected menu and context.
            before_reload = page.evaluate('window.LunchRunState.read()')
            page.reload()
            page.wait_for_selector('.result-title')
            assert page.locator('.result-title').inner_text() == '짜장면'
            assert page.evaluate('window.LunchRunState.read().conditions.deadline') == before_reload['conditions']['deadline']
            page.go_back()
            page.wait_for_selector('[data-action="go:backend-games"]')
            assert page.locator('#location').get_attribute('title') == '서울 현재위치로 1'
            assert page.locator('[data-action="go:budget"]').inner_text() == '9,000원'
            assert page.evaluate('window.LunchRunState.read().menu.id') == 'noodle'
            page.locator('[data-action="go:backend-games"]').click()
            page.wait_for_selector('.result-title')
            assert page.locator('.result-title').inner_text() == '짜장면'
            page.locator('#location').click()
            page.locator('[data-location-query]').fill('식사 출발점')
            page.locator('[data-location-submit]').click()
            page.locator('.lr-location-result').click()
            page.wait_for_function("document.querySelector('#location').textContent === '검색한 식사 출발점'")
            page.wait_for_function("document.querySelector('#candidate-count').textContent === '1개'")
            assert candidates[-1]['location'] == place
            assert page.locator('.result-title').count() == 0
            # Permission denial and timeout keep the previously selected place.
            for code, message in [(1, '권한'), (2, '확인할 수'), (3, '초과')]:
                page.evaluate('(code)=>{navigator.geolocation.getCurrentPosition=(ok,fail)=>fail({code});}', code)
                page.locator('#location').click()
                page.locator('[data-location-current]').click()
                page.wait_for_function('(text)=>document.querySelector("[data-location-status]").textContent.includes(text)', arg=message)
                assert page.locator('#location').inner_text() == place['name']
                page.locator('[data-location-close]').click()
            # A late native callback must not overwrite an explicit address selection.
            page.evaluate('()=>{navigator.geolocation.getCurrentPosition=(ok)=>{window.lateLocation=ok;};}')
            page.locator('#location').click()
            page.locator('[data-location-current]').click()
            page.locator('[data-location-kind="address"]').click()
            page.locator('[data-location-query]').fill('서울 검색로 20')
            page.locator('[data-location-submit]').click()
            page.locator('.lr-location-result').click()
            page.evaluate('window.lateLocation({coords:{latitude:35,longitude:129,accuracy:10}})')
            page.wait_for_function("document.querySelector('#candidate-count').textContent === '1개'")
            assert page.locator('#location').inner_text() == address['name']
            assert candidates[-1]['location'] == address
            # Reverse failure must still allow the acquired coordinates.
            page.route('**/api/locations/reverse', lambda route: route.fulfill(status=503, content_type='application/json', body='{}'))
            page.evaluate('()=>{navigator.geolocation.getCurrentPosition=(ok)=>ok({coords:{latitude:37.51,longitude:126.91,accuracy:20}});}')
            page.locator('#location').click()
            page.locator('[data-location-current]').click()
            page.wait_for_function("!document.querySelector('.lr-location-dialog').open")
            page.wait_for_function("document.querySelector('#candidate-count').textContent === '1개'")
            assert candidates[-1]['location']['lat'] == 37.51
            assert '37.51000' in page.locator('.location-note').inner_text()
            page.locator('#location').click()
            page.screenshot(path=str(tmp_path / 'location-picker.png'), full_page=True)
            page.locator('[data-location-close]').click()
            # Leaving during a restaurant search aborts it; a later context change clears its menu.
            page.locator('[data-action="play"]').click()
            page.locator('[data-action="open-capsule"]').first.click()
            page.wait_for_selector('.result-title')
            held = []
            page.evaluate('''()=>{const original=window.fetch;window.fetch=(url,options)=>{
                if(String(url).endsWith('/api/recommendations'))options.signal.addEventListener('abort',()=>sessionStorage.setItem('test:search-aborted','yes'));
                return original(url,options);
            };}''')
            page.route('**/api/recommendations', lambda route: held.append(route))
            page.add_init_script('''const original=window.fetch;window.fetch=(url,options)=>{if(String(url).endsWith('/api/recommendations'))options.signal.addEventListener('abort',()=>sessionStorage.setItem('test:search-aborted','yes'));return original(url,options);};''')
            page.route('https://dapi.kakao.com/**', lambda route: route.fulfill(content_type='application/javascript', body=(root/'tests/map-sdk-stub.js').read_text(encoding='utf-8')))
            page.locator('[data-action="find"]').click()
            page.wait_for_url('**/map/**')
            page.wait_for_function("document.querySelector('#search-status').textContent.includes('검증 중')")
            page.goto(api_url)
            assert page.evaluate("sessionStorage.getItem('test:search-aborted')") == 'yes'
            assert page.evaluate('window.LunchRunState.read().menu.id') == 'noodle'
            page.locator('[data-category="한식"]').click()
            assert page.evaluate('window.LunchRunState.read().menu') is None
            assert page.evaluate('window.LunchRunState.read().restaurants') == []
            for route in held:
                route.fulfill(status=200, content_type='application/json', body=json.dumps({'restaurants': [{'id': 'late-old-result'}]}))
            assert page.evaluate('window.LunchRunState.read().restaurants') == []
            assert not errors, errors
            # Direct game access cannot silently request candidates at a preset station.
            fresh = context.new_page()
            direct_requests = []
            fresh.on('request', lambda r: direct_requests.append(r.url) if r.url.endswith('/api/menus/candidates') else None)
            fresh.goto(api_url + '/games/')
            fresh.wait_for_function("document.querySelector('#toast').textContent.includes('먼저 출발 위치')")
            assert fresh.locator('#location').inner_text() == '위치 설정'
            assert not direct_requests
            fresh.close()
            browser.close()
    finally:
        if node:
            node.terminate()
            node.wait(timeout=10)
        server.should_exit = True
        thread.join(timeout=10)
        database.dispose()
