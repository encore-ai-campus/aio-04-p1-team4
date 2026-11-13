"""게임 선택/실행의 일반 경로와 원본 디자인을 실제 브라우저로 검증한다."""
import os
import shutil
import subprocess
import sys
import threading
import time
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from unittest.mock import AsyncMock, patch

import httpx
import uvicorn
from playwright.sync_api import sync_playwright, expect

from app.main import app
import games.app as games_proxy
from test_db_first_flow import database, add_place
from test_game_browser_flow import free_port, select_game


class GameReferenceHandler(SimpleHTTPRequestHandler):
    def log_message(self, *args): pass

    def translate_path(self, path):
        original = super().translate_path(path)
        if Path(original).is_file(): return original
        if path.startswith('/assets/'):
            candidate = Path('C:/temp/aio-04-p1-team4/frontend')/path.split('?',1)[0].lstrip('/')
            asset_root = Path('C:/temp/aio-04-p1-team4/frontend/assets').resolve()
            if candidate.resolve().is_relative_to(asset_root) and candidate.is_file(): return str(candidate)
        return original


def test_game_select_play_history_and_design(database, tmp_path, monkeypatch):
    root = Path(__file__).resolve().parents[1]
    with database.session_factory.begin() as session: add_place(session)
    port, node_port = free_port(), free_port()
    origin, node_origin = f'http://127.0.0.1:{port}', f'http://127.0.0.1:{node_port}'
    monkeypatch.setattr(app.state, 'database', database)
    monkeypatch.setattr(games_proxy, 'NODE_ORIGIN', node_origin)
    server = uvicorn.Server(uvicorn.Config(app, host='127.0.0.1', port=port, log_level='error'))
    worker = threading.Thread(target=server.run, daemon=True)
    node = reference = reference_worker = None
    output = root/'output/frontend_merge_stage3'
    output.mkdir(parents=True, exist_ok=True)
    worker.start()
    try:
        for _ in range(100):
            if server.started: break
            time.sleep(.05)
        assert server.started
        node = subprocess.Popen([shutil.which('node'),'games/server.mjs'],cwd=root,
            env={**os.environ,'HOST':'127.0.0.1','PORT':str(node_port),'BACKEND_ORIGIN':origin,
                'PYTHON_BIN':sys.executable,'ROOM_STORE_FILE':str(tmp_path/'rooms.json')},
            stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
        for _ in range(100):
            try:
                if httpx.get(node_origin+'/api/network').status_code==200: break
            except httpx.HTTPError: pass
            time.sleep(.05)
        source = Path('C:/temp/aio-04-p1-team4/games/dist')
        # 기존 Node 직접 접속도 정적 경로 변경 때문에 깨지지 않게 유지한다.
        direct=httpx.get(node_origin+'/games/play')
        assert direct.status_code==200 and '<base href="/" />' in direct.text
        assert httpx.get(node_origin+'/assets/shared-header.css').status_code==200
        if source.is_dir():
            reference = ThreadingHTTPServer(('127.0.0.1',0),partial(GameReferenceHandler,directory=str(source)))
            reference_worker=threading.Thread(target=reference.serve_forever,daemon=True)
            reference_worker.start()
        external = AsyncMock(side_effect=AssertionError('external restaurant search forbidden'))
        with patch('app.clients.kakao.KakaoClient.search_restaurants',external),sync_playwright() as p:
            browser=p.chromium.launch(headless=True)
            for label,size in [('desktop',{'width':1516,'height':1038}),('mobile',{'width':390,'height':844})]:
                page=browser.new_page(viewport=size,reduced_motion='reduce')
                page.route('https://fonts.googleapis.com/**',lambda route:route.abort())
                page.route('https://fonts.gstatic.com/**',lambda route:route.abort())
                if reference:
                    page.goto(f'http://127.0.0.1:{reference.server_port}')
                    expect(page.locator('[data-game="gacha"]')).to_be_visible()
                    page.screenshot(path=str(output/f'reference-select-{label}.png'),full_page=True)
                    page.locator('[data-game="gacha"]').click()
                    expect(page.locator('.play-board')).to_be_visible()
                    page.screenshot(path=str(output/f'reference-play-{label}.png'),full_page=True)
                errors=[]
                page.on('pageerror',lambda error:errors.append(str(error)))
                page.goto(origin)
                page.evaluate("""() => {LunchRunState.setContext({location:{lat:37.5,lng:127,name:'시험 위치',source:'place'},conditions:{budget:9000,cuisine:'중식',people:1,deadline:Date.now()+30*60000}});dispatchEvent(new PopStateEvent('popstate'));}""")
                page.evaluate("LunchRunState.setGame({mode:'solo',game:'gacha',view:'saved'})")
                page.goto(origin+'/games/')
                expect(page.locator('#candidate-count')).to_have_text('1개')
                expect(page.locator('[data-game="gacha"]')).to_be_visible()
                assert page.locator('#game-options button').count()==4
                page.screenshot(path=str(output/f'merged-select-{label}.png'),full_page=True)
                page.locator('[data-game="gacha"]').click()
                page.wait_for_url(origin+'/games/play')
                expect(page.locator('.play-board')).to_be_visible()
                assert page.evaluate('location.hash')==''
                page.screenshot(path=str(output/f'merged-play-{label}.png'),full_page=True)
                page.locator('[data-action="play"]').click()
                page.locator('[data-action="open-capsule"]').first.click()
                expect(page.locator('.result-title')).to_have_text('짜장면')
                expect(page.locator('.result-stats')).to_have_text('7,000원 · 1곳')
                expect(page.locator('.result-note')).to_have_text('실제 매장 상황은 달라질 수 있어요.')
                assert page.locator('.result-desc').count()==0
                kicker=page.locator('.result-kicker').bounding_box();art=page.locator('.confetti').bounding_box()
                assert kicker['y']>=art['y']+art['height']
                board=page.locator('.play-board').bounding_box();foot=page.locator('#game-footnote').bounding_box()
                center=(page.locator('.result-scene').bounding_box()['y']+foot['y']+foot['height'])/2
                assert abs(center-(board['y']+board['height']/2))<2
                for selector in ['.result-title','.result-stats','#game-actions','#game-footnote']:
                    box=page.locator(selector).bounding_box()
                    assert abs(box['x']+box['width']/2-board['x']-board['width']/2)<2
                page.screenshot(path=str(output/f'merged-result-{label}.png'),full_page=True)
                page.reload()
                expect(page.locator('.result-title')).to_have_text('짜장면')
                page.go_back()
                page.wait_for_url(origin+'/games/')
                expect(page.locator('[data-game="gacha"]')).to_be_visible()
                page.go_forward()
                page.wait_for_url(origin+'/games/play')
                expect(page.locator('.result-title')).to_have_text('짜장면')
                page.locator('#location').click()
                expect(page.locator('.lr-location-dialog')).to_be_visible()
                page.locator('[data-location-close]').click()
                assert page.request.get(origin+'/games/not-a-page').status==404
                page.locator('.stage-dock [data-shell="game"]').click()
                page.locator('[data-mode="group"]').click()
                expect(page.locator('#candidate-count')).to_have_text('1개')
                page.screenshot(path=str(output/f'merged-group-select-{label}.png'),full_page=True)
                assert page.locator('#game-options [data-game]').count()==3
                assert page.locator('[data-game="intersection"]').count()==1
                select_game(page,'roulette')
                expect(page.locator('#group-settings')).to_be_visible()
                select_game(page,'ladder')
                expect(page.locator('.ladder-starts button').first).to_be_visible()
                expect(page.locator('#game-footnote')).to_have_text('입력한 값으로 추첨해요.')
                assert page.get_by_text('아직 출발한 참가자가 없어요.',exact=True).count()==0
                assert page.get_by_text('참가자를 누른 순서대로 진행해요',exact=True).count()==0
                expect(page.get_by_role('button',name='새사다리 만들기',exact=True)).to_be_visible()
                reset=page.locator('[data-action="reset-ladder"]').bounding_box();board=page.locator('.play-board').bounding_box()
                assert abs(reset['x']+reset['width']/2-board['x']-board['width']/2)<1
                assert page.locator('.ladder-starts button').first.evaluate('(e)=>getComputedStyle(e).color')=='rgb(255, 255, 255)'
                assert page.locator('.ladder-starts button').first.evaluate('(e)=>getComputedStyle(e).fontWeight')=='800'
                assert page.locator('.ladder-svg').evaluate('(e)=>getComputedStyle(e).backgroundColor')=='rgb(247, 247, 247)'
                assert page.locator('.ladder-svg').evaluate('(e)=>getComputedStyle(e).backgroundImage')=='none'
                assert page.locator('.ladder-svg text').first.evaluate('(e)=>getComputedStyle(e).fill')=='rgb(255, 104, 29)'
                assert page.locator('.ladder-svg text').first.evaluate('(e)=>getComputedStyle(e).fontSize')=='20px'
                page.screenshot(path=str(output/f'ladder-contrast-{label}.png'),full_page=True)
                assert errors==[]
                page.close()
            # 일반 애니메이션 설정에서도 가챠 실행·캡슐 열기가 완료되어야 한다.
            motion=browser.new_page(viewport={'width':1516,'height':1038},reduced_motion='no-preference')
            motion.route('https://fonts.googleapis.com/**',lambda route:route.abort())
            motion.route('https://fonts.gstatic.com/**',lambda route:route.abort())
            motion.goto(origin)
            motion.evaluate("""() => {LunchRunState.setContext({location:{lat:37.5,lng:127,name:'시험 위치',source:'place'},conditions:{budget:9000,cuisine:'중식',people:1,deadline:Date.now()+30*60000}});dispatchEvent(new PopStateEvent('popstate'));}""")
            motion.goto(origin+'/games/')
            expect(motion.locator('#candidate-count')).to_have_text('1개')
            select_game(motion,'gacha')
            motion.locator('[data-action="play"]').click()
            capsule=motion.locator('[data-action="open-capsule"]').first
            capsule.wait_for(state='visible',timeout=15000)
            # 캡슐은 계속 떠다니므로 정지 상태를 기다리지 않고 실제 포인터로 누른다.
            bounds=capsule.bounding_box()
            motion.mouse.click(bounds['x']+bounds['width']/2,bounds['y']+bounds['height']/2)
            expect(motion.locator('.result-title')).to_have_text('짜장면')
            motion.close()
            external.assert_not_called()
            browser.close()
    finally:
        if reference:
            reference.shutdown();reference.server_close();reference_worker.join(timeout=5)
        if node:
            node.terminate();node.wait(timeout=10)
        server.should_exit=True
        worker.join(timeout=10)
