"""Real browser/HTTP/backend policy; Groq interpretation/narration and Kakao are stubbed."""
import json
import os
import shutil
import subprocess
import threading
import time
from pathlib import Path

import httpx
import uvicorn
from playwright.sync_api import sync_playwright, expect

from app.main import app
from app.chat_policy import QuestionInterpretation
import games.app as games_proxy
import test_recommendations as recommendations
from test_game_browser_flow import free_port, select_game


def test_chat_home_game_conditions_session_and_map(tmp_path, monkeypatch):
    boundary = recommendations.RecommendationTests()
    boundary.setUp()
    # 5단계: 성공한 답변 구성이 실제 화면과 저장 대화에 표시되는 경로도 검증한다.
    boundary.narrate.side_effect=lambda context:{'content':json.dumps({'paragraphs':[
        {'opening':'확인한 내용을 정리해드릴게요.','fact_ids':list(range(len(context['facts']))),'closing':''}
    ]},ensure_ascii=False)}
    boundary.search.return_value = {'items': [{**recommendations.ITEM, 'category':'음식점 > 중식'}], 'has_more':False}
    root = Path(__file__).resolve().parents[1]
    api_port, node_port = free_port(), free_port()
    origin, node_origin = f'http://127.0.0.1:{api_port}', f'http://127.0.0.1:{node_port}'
    monkeypatch.setattr(games_proxy, 'NODE_ORIGIN', node_origin)
    server = uvicorn.Server(uvicorn.Config(app, host='127.0.0.1', port=api_port, log_level='error'))
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    node = None
    try:
        for _ in range(100):
            if server.started:
                break
            time.sleep(.05)
        assert server.started
        node = subprocess.Popen([shutil.which('node'), 'games/server.mjs'], cwd=root,
            env={**os.environ, 'PORT': str(node_port), 'HOST': '127.0.0.1', 'BACKEND_ORIGIN': origin,
                 'ROOM_STORE_FILE': str(tmp_path/'rooms.json')},
            stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
        for _ in range(100):
            try:
                if httpx.get(node_origin+'/api/network').status_code == 200:
                    break
            except httpx.HTTPError:
                time.sleep(.05)
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page(viewport={'width': 1516, 'height': 1038}, reduced_motion='reduce')
            errors, requests = [], []
            page.on('pageerror', lambda e: errors.append(str(e)))
            page.on('request', lambda r: requests.append(r.post_data_json) if r.url.endswith('/api/chat/stream') else None)
            page.goto(origin)
            page.evaluate("""() => {LunchRunState.setContext({location:{lat:37.48,lng:126.88,name:'예시 위치',source:'place'},conditions:{budget:9000,cuisine:'중식',deadline:Date.now()+30*60000}});window.dispatchEvent(new PopStateEvent('popstate'));}""")
            page.reload()
            page.goto(origin+'/ai')
            expect(page.locator('.lr-chat textarea')).to_be_enabled()

            def send(text, plan):
                async def interpret(*_args, **_kwargs):
                    # GroqClient normally validates IDs inside its DB-catalog scope.
                    # The stub bypasses only that external-client boundary.
                    return QuestionInterpretation.model_validate(plan, context={
                        'menu_ids': {m['id'] for m in _args[3]},
                        'restaurant_ids': {r['id'] for r in (_kwargs.get('restaurants', []) + _kwargs.get('candidate_restaurants', []))},
                    })
                boundary.interpret.side_effect = interpret
                count = page.locator('.lr-chat-message').count()
                page.locator('.lr-chat textarea').fill(text)
                page.locator('.lr-chat button[type=submit]').click()
                expect(page.locator('.lr-chat textarea')).to_be_enabled(timeout=20000)
                expect(page.locator('.lr-chat-message')).to_have_count(count+2)

            boundary.interpret.return_value = QuestionInterpretation(intent='recommend_menu')
            page.locator('.lr-chat textarea').fill('메뉴')
            page.locator('.lr-chat textarea').press('Shift+Enter')
            assert page.locator('.lr-chat textarea').input_value() == '메뉴\n'
            page.locator('.lr-chat textarea').fill('메뉴 추천해줘')
            page.locator('.lr-chat textarea').press('Enter')
            expect(page.locator('.lr-chat-message')).to_have_count(2)
            expect(page.locator('.lr-chat textarea')).to_be_enabled()
            assert page.evaluate('LunchRunState.read().menu.id') == 'noodle'
            assert '확인한 내용을 정리해드릴게요.' in page.locator('.lr-chat-message').last.inner_text()
            boundary.search.assert_not_awaited()
            assert requests[-1]['conditions']['cuisine'] == '중식'
            assert requests[-1]['menu_id'] is None

            # 4단계: 상대 반경과 명시 반경을 별도 적용 버튼 없이 바로 반영한다.
            send('반경을 줄여줘', {'intent':'change_conditions', 'radius_adjustment':'decrease'})
            assert page.evaluate('LunchRunState.read().conditions.radius_m') == 450
            send('반경을 100m로 바꿔줘', {'intent':'change_conditions', 'condition_patch':{'radius_m':100}})
            assert page.evaluate('LunchRunState.read().conditions.radius_m') == 100
            assert page.evaluate('LunchRunState.read().menu.id') == 'noodle'
            expect(page.locator('[data-chat-apply]')).to_have_count(0)
            boundary.search.assert_not_awaited()

            # New local conditions remain authoritative after a completed server change.
            send('예산을 1만원으로', {'intent':'change_conditions', 'condition_patch':{'budget':10000}})
            page.evaluate('LunchRunState.setContext({conditions:{budget:11000}})')
            expect(page.locator('[data-chat-apply]')).to_have_count(0)
            assert page.evaluate('LunchRunState.read().conditions.budget') == 11000
            # Restore server turns without overwriting the newer local budget.
            page.reload()
            expect(page.locator('.lr-chat textarea')).to_be_enabled()
            expect(page.locator('.lr-chat-message')).to_have_count(8)
            assert page.evaluate('LunchRunState.read().conditions.budget') == 11000

            # Games use the exact same conversation and preserve their surrounding UI.
            page.goto(origin+'/games/')
            page.locator('[data-shell=ai]').click()
            expect(page.locator('.lr-chat textarea')).to_be_enabled()
            expect(page.locator('.lr-chat-message')).to_have_count(8)
            page.evaluate('LunchRunState.setContext({conditions:{budget:9000}})')
            send('메뉴 추천해줘', {'intent':'recommend_menu'})
            boundary.search.assert_not_awaited()
            send('이 메뉴 식당 찾아줘', {'intent':'search_restaurants'})
            boundary.search.assert_not_awaited()
            assert requests[-1]['radius_m'] == 100
            assert requests[-1]['menu_id'] == 'noodle'
            assert page.evaluate('LunchRunState.read().searchedAt')
            expect(page.locator('.lr-chat-map')).to_be_visible()
            saved_session = page.request.get(origin+'/api/chat/session').json()
            assert 'test-place' in saved_session['restaurant_ids'] + saved_session['candidate_restaurant_ids'], saved_session
            # Follow-up facts come from DB-backed session IDs, never model prose.
            send('가격 알려줘', {'intent':'ask_restaurant_detail','restaurant_id':'test-place','requested_detail':'price'})
            assert '8,000' in page.locator('.lr-chat-message').last.inner_text()
            assert boundary.interpret.call_args.kwargs['restaurants'][0]['id'] == 'test-place'
            page.goto(origin+'/ai')
            expect(page.locator('.lr-chat-map')).to_be_visible()
            page.locator('.lr-chat-map').click()
            page.wait_for_url('**/games/')
            page.locator('[data-shell="restaurants"]').click()
            page.wait_for_url('**/map/**')
            page.go_back()
            assert page.url == origin+'/games/'
            page.go_back()
            assert page.url.startswith(origin+'/ai')
            assert not errors
            page.screenshot(path=str(tmp_path/'chat-games.png'), full_page=True)
            browser.close()
    finally:
        if node:
            node.terminate()
            node.wait(timeout=10)
        server.should_exit = True
        thread.join(timeout=10)
        boundary.tearDown()
