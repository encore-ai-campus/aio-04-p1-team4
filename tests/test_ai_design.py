"""원본 AI 화면 외형과 실제 DB 대화 흐름을 데스크톱·모바일에서 확인한다."""
import asyncio
import json
import threading
import time
from functools import partial
from http.server import ThreadingHTTPServer
from pathlib import Path
from unittest.mock import AsyncMock, patch

import uvicorn
from playwright.sync_api import sync_playwright, expect

from app.main import app
from app.chat_policy import QuestionInterpretation
from test_db_first_flow import database, add_place
from test_game_browser_flow import free_port
from test_home_design import ReferenceHandler


def test_ai_design_db_conversation_proposal_and_recovery(database, monkeypatch):
    root=Path(__file__).resolve().parents[1]
    with database.session_factory.begin() as session: add_place(session)
    monkeypatch.setattr(app.state,'database',database)
    port=free_port()
    origin=f'http://127.0.0.1:{port}'
    server=uvicorn.Server(uvicorn.Config(app,host='127.0.0.1',port=port,log_level='error'))
    worker=threading.Thread(target=server.run,daemon=True)
    source=Path('C:/temp/aio-04-p1-team4/frontend')
    reference=ThreadingHTTPServer(('127.0.0.1',0),partial(ReferenceHandler,directory=str(source))) if source.is_dir() else None
    reference_worker=threading.Thread(target=reference.serve_forever,daemon=True) if reference else None
    output=root/'output/frontend_merge_stage4'
    output.mkdir(parents=True,exist_ok=True)
    plan={'intent':'recommend_menu'}

    async def interpret(*args,**kwargs):
        await asyncio.sleep(.03)
        return QuestionInterpretation.model_validate(plan,context={
            'menu_ids':{m['id'] for m in args[3]},
            'restaurant_ids':{r['id'] for r in kwargs.get('restaurants',[])+kwargs.get('candidate_restaurants',[])}})

    worker.start()
    if reference_worker: reference_worker.start()
    try:
        for _ in range(100):
            if server.started: break
            time.sleep(.05)
        assert server.started
        external=AsyncMock(side_effect=AssertionError('restaurant search forbidden'))
        with patch('app.clients.groq.GroqClient.interpret',side_effect=interpret),patch('app.clients.kakao.KakaoClient.search_restaurants',external),sync_playwright() as p:
            browser=p.chromium.launch(headless=True)
            for label,size in [('desktop',{'width':1516,'height':1038}),('mobile',{'width':390,'height':844})]:
                page=browser.new_page(viewport=size,reduced_motion='reduce')
                page.route('https://fonts.googleapis.com/**',lambda route:route.abort())
                page.route('https://fonts.gstatic.com/**',lambda route:route.abort())
                if reference:
                    page.goto(f'http://127.0.0.1:{reference.server_port}/#ai')
                    expect(page.locator('.ai-chat')).to_be_visible()
                    page.screenshot(path=str(output/f'reference-{label}.png'),full_page=True)
                errors=[]
                page.on('pageerror',lambda error:errors.append(str(error)))
                page.goto(origin)
                page.evaluate("""() => {LunchRunState.setContext({location:{lat:37.5,lng:127,name:'시험 위치',source:'place'},conditions:{budget:9000,cuisine:'중식',deadline:Date.now()+30*60000}});dispatchEvent(new PopStateEvent('popstate'));}""")
                page.locator('#screen [data-action="go:ai"]').click()
                page.wait_for_url(origin+'/ai')
                expect(page.locator('.lr-chat textarea')).to_be_enabled()
                page.screenshot(path=str(output/f'merged-empty-{label}.png'),full_page=True)

                def send(text, next_plan):
                    plan.clear();plan.update(next_plan)
                    count=page.locator('.lr-chat-message').count()
                    page.locator('.lr-chat textarea').fill(text)
                    page.locator('.lr-chat textarea').press('Enter')
                    expect(page.locator('.lr-chat-message')).to_have_count(count+2,timeout=15000)
                    expect(page.locator('.lr-chat textarea')).to_be_enabled()

                page.locator('.lr-chat textarea').fill('메뉴')
                page.locator('.lr-chat textarea').press('Shift+Enter')
                assert page.locator('.lr-chat textarea').input_value()=='메뉴\n'
                send('메뉴 추천해줘',{'intent':'recommend_menu'})
                expect(page.locator('.lr-chat-menu')).to_contain_text('짜장면')
                expect(page.locator('.lr-chat-menu')).to_contain_text('인분 미확인')
                send('식당 찾아줘',{'intent':'search_restaurants'})
                assert page.evaluate('LunchRunState.read().restaurants.length')==1
                send('그 식당 가격 알려줘',{'intent':'ask_restaurant_detail','restaurant_id':'one','requested_detail':'price'})
                expect(page.locator('.lr-chat-message').last).to_contain_text('7,000원')
                page.screenshot(path=str(output/f'merged-thread-{label}.png'),full_page=True)
                send('예산을 만원으로 바꿔줘',{'intent':'change_conditions','condition_patch':{'budget':10000}})
                expect(page.locator('.lr-chat-proposal')).to_be_visible()
                assert page.evaluate('LunchRunState.read().conditions.budget')==9000
                page.screenshot(path=str(output/f'merged-proposal-{label}.png'),full_page=True)
                page.locator('[data-chat-apply]').click()
                assert page.evaluate('LunchRunState.read().conditions.budget')==10000
                assert page.evaluate('LunchRunState.read().menu') is None
                assert page.evaluate('LunchRunState.read().restaurants')==[]
                send('다시 추천해줘',{'intent':'recommend_menu'})
                send('이 메뉴 식당 조회',{'intent':'search_restaurants'})
                page.reload()
                expect(page.locator('.lr-chat textarea')).to_be_enabled()
                expect(page.locator('.lr-chat-message')).to_have_count(12)
                assert page.evaluate('LunchRunState.read().conditions.budget')==10000
                assert page.locator('.lr-chat-map').get_attribute('href')=='/games/'
                if label=='desktop':
                    panel=page.locator('#screen').bounding_box()
                    dock=page.locator('#dock').bounding_box()
                    footer=page.locator('.app footer').bounding_box()
                    form=page.locator('.lr-chat-form').bounding_box()
                    assert panel['x']+panel['width']<dock['x']
                    assert form['y']+form['height']<footer['y']
                else:
                    assert page.evaluate('document.documentElement.scrollWidth')<=size['width']
                page.route('**/api/chat/stream',lambda route:route.fulfill(status=503,content_type='application/json',body=json.dumps({'detail':'잠시 후 다시 시도해주세요.'})))
                page.locator('.lr-chat textarea').fill('재시도 확인')
                page.locator('.lr-chat textarea').press('Enter')
                expect(page.locator('[data-chat-retry]')).to_be_visible()
                page.screenshot(path=str(output/f'merged-error-{label}.png'),full_page=True)
                page.unroute('**/api/chat/stream')
                plan.clear();plan.update({'intent':'recommend_menu'})
                page.locator('[data-chat-retry]').click()
                expect(page.locator('.lr-chat textarea')).to_be_enabled()
                expect(page.locator('[data-chat-retry]')).to_have_count(0)
                held=[]
                page.route('**/api/chat/stream',lambda route:held.append(route))
                page.locator('.lr-chat textarea').fill('취소 확인')
                page.locator('.lr-chat textarea').press('Enter')
                expect(page.locator('[data-chat-cancel]')).to_be_visible()
                page.screenshot(path=str(output/f'merged-loading-{label}.png'),full_page=True)
                page.locator('[data-chat-cancel]').click()
                expect(page.locator('.lr-chat-status')).to_contain_text('취소')
                expect(page.locator('.lr-chat textarea')).to_be_enabled()
                assert page.evaluate('LunchRunState.read().menu.id')=='noodle'
                for route in held:
                    try: route.abort()
                    except Exception: pass
                page.unroute('**/api/chat/stream')
                assert errors==[]
                page.close()
            external.assert_not_called()
            browser.close()
    finally:
        if reference:
            reference.shutdown();reference.server_close();reference_worker.join(timeout=5)
        server.should_exit=True
        worker.join(timeout=10)
