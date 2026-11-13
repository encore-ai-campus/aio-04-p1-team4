"""실제 브라우저에서 홈 → 게임 → 지도와 역순 탐색을 검증한다."""
import os
import shutil
import subprocess
import threading
import time
from pathlib import Path
from unittest.mock import AsyncMock, patch

import httpx
import uvicorn
from playwright.sync_api import sync_playwright, expect

from app.main import app
from app.chat_policy import QuestionInterpretation
import games.app as games_proxy
from test_db_first_flow import database, add_place
from test_game_browser_flow import free_port, select_game


def test_db_home_game_map_and_back(database, tmp_path, monkeypatch):
    with database.session_factory.begin() as s:
        add_place(s)
    root = Path(__file__).resolve().parents[1]
    port, node_port = free_port(), free_port()
    origin, node_origin = f'http://127.0.0.1:{port}', f'http://127.0.0.1:{node_port}'
    monkeypatch.setattr(app.state, 'database', database)
    monkeypatch.setattr(games_proxy, 'NODE_ORIGIN', node_origin)
    server = uvicorn.Server(uvicorn.Config(app, host='127.0.0.1', port=port, log_level='error'))
    thread = threading.Thread(target=server.run, daemon=True)
    node = None
    thread.start()
    try:
        for _ in range(100):
            if server.started: break
            time.sleep(.05)
        assert server.started
        node = subprocess.Popen([shutil.which('node'), 'games/server.mjs'], cwd=root,
            env={**os.environ, 'PORT':str(node_port), 'HOST':'127.0.0.1',
                'BACKEND_ORIGIN':origin, 'ROOM_STORE_FILE':str(tmp_path/'rooms.json')},
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        for _ in range(100):
            try:
                if httpx.get(node_origin+'/api/network').status_code == 200: break
            except httpx.HTTPError: pass
            time.sleep(.05)
        external = AsyncMock(side_effect=AssertionError('external restaurant lookup forbidden'))
        interpretation = AsyncMock(return_value=QuestionInterpretation(intent='recommend_menu'))
        # 5단계: 추가 설명 호출은 실제 API를 쓰지 않는다.
        with patch('app.clients.groq.GroqClient.compose_answer',AsyncMock(side_effect=RuntimeError('narration_stub'))), patch('app.clients.kakao.KakaoClient.search_restaurants', external), patch('app.clients.groq.GroqClient.interpret', interpretation), sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page(reduced_motion='reduce', viewport={'width':1440,'height':1000})
            errors = []
            page.on('pageerror', lambda e:errors.append(str(e)) if 'ViewTransition' not in str(e) else None)
            page.route('https://dapi.kakao.com/**', lambda r:r.fulfill(content_type='application/javascript',
                body=(root/'tests/map-sdk-stub.js').read_text(encoding='utf-8')))
            page.goto(origin+'/')
            page.evaluate("""() => {LunchRunState.setContext({location:{lat:37.5,lng:127,name:'시험 위치',source:'place'},conditions:{budget:9000,cuisine:'중식',deadline:Date.now()+30*60000}});dispatchEvent(new PopStateEvent('popstate'));}""")
            assert page.locator('#db-menu-preview').count() == 0
            page.locator('#screen [data-action="go:backend-games"]').click()
            page.wait_for_url('**/games/**')
            expect(page.locator('#candidate-count')).to_have_text('1개')
            page.locator('[data-mode="solo"]').click()
            select_game(page, 'gacha')
            page.locator('[data-action="play"]').click()
            page.locator('[data-action="open-capsule"]').first.click()
            expect(page.locator('.result-title')).to_have_text('짜장면')
            # 6단계: 검증하지 않는 인분/판매 상태를 확인됐다고 표시하지 않는다.
            expect(page.locator('.result-stats')).not_to_contain_text('인분 미확인')
            expect(page.locator('.result-stats')).not_to_contain_text('1인분 확인')
            page.locator('[data-action="find"]').click()
            page.wait_for_url('**/map/**')
            expect(page.locator('#restaurant-list')).to_contain_text('one')
            expect(page.locator('#restaurant-list')).not_to_contain_text('인분 미확인')
            page.go_back()
            page.wait_for_url('**/games/**')
            page.go_back()
            page.wait_for_url(origin+'/games/')
            page.go_back()
            page.wait_for_url(origin+'/')
            assert page.locator('#db-menu-preview').count() == 0
            page.locator('#screen [data-action="go:ai"]').click()
            page.wait_for_url(origin+'/ai')
            expect(page.locator('.lr-chat textarea')).to_be_enabled()
            page.locator('.lr-chat textarea').fill('메뉴')
            page.locator('.lr-chat textarea').press('Shift+Enter')
            assert page.locator('.lr-chat textarea').input_value() == '메뉴\n'
            page.locator('.lr-chat textarea').fill('메뉴 추천해줘')
            page.locator('.lr-chat textarea').press('Enter')
            expect(page.locator('.lr-chat-message')).to_have_count(2)
            expect(page.locator('.lr-chat textarea')).to_be_enabled()
            assert page.locator('.lr-chat-menu').count() == 0
            assert page.evaluate('LunchRunState.read().menu.id') == 'noodle'
            interpretation.return_value = QuestionInterpretation(intent='search_restaurants')
            page.locator('.lr-chat textarea').fill('식당 찾아줘')
            page.locator('.lr-chat textarea').press('Enter')
            expect(page.locator('.lr-chat-message')).to_have_count(4)
            expect(page.locator('.lr-chat textarea')).to_be_enabled()
            expect(page.locator('.lr-chat-message').last).not_to_contain_text('인분 미확인')
            assert page.evaluate('LunchRunState.read().restaurants.length') == 1
            page.reload()
            page.wait_for_url(origin+'/ai')
            expect(page.locator('.lr-chat textarea')).to_be_enabled()
            expect(page.locator('.lr-chat-message')).to_have_count(4)
            assert page.evaluate('LunchRunState.read().menu.id') == 'noodle'
            assert page.evaluate('location.hash') == ''
            page.locator('.brand').click()
            page.wait_for_url(origin+'/')
            expect(page.locator('[data-action="go:budget"]')).to_have_text('9,000원')
            # 이전 북마크도 새 경로로 정규화한다.
            page.goto(origin+'/#ai')
            page.wait_for_url(origin+'/ai')
            expect(page.locator('.lr-chat textarea')).to_be_enabled()
            page.goto(origin+'/#games')
            page.wait_for_url(origin+'/games/')
            expect(page.locator('#candidate-count')).to_have_text('1개')
            external.assert_not_called()
            assert errors == []
            browser.close()
    finally:
        if node:
            node.terminate()
            node.wait(timeout=10)
        server.should_exit = True
        thread.join(timeout=10)
