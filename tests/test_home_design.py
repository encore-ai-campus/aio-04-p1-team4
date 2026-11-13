"""원본 홈 디자인과 실제 DB·위치 연결을 데스크톱/모바일에서 확인한다."""
import json
import threading
import time
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import uvicorn
from playwright.sync_api import sync_playwright, expect

from app.main import app
from test_db_first_flow import database, add_place
from test_game_browser_flow import free_port


class ReferenceHandler(SimpleHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def do_GET(self):
        if self.path == '/config.json':
            self.send_response(200)
            self.send_header('Content-Type', 'application/json')
            self.end_headers()
            self.wfile.write(b'{"apiBase":""}')
        else:
            super().do_GET()


def test_home_reference_layout_and_db_controls(database, monkeypatch):
    root = Path(__file__).resolve().parents[1]
    source = Path('C:/temp/aio-04-p1-team4/frontend')
    with database.session_factory.begin() as session:
        add_place(session)
    monkeypatch.setattr(app.state, 'database', database)
    port = free_port()
    origin = f'http://127.0.0.1:{port}'
    server = uvicorn.Server(uvicorn.Config(app, host='127.0.0.1', port=port, log_level='error'))
    worker = threading.Thread(target=server.run, daemon=True)
    # 다른 개발 환경에서는 원본 폴더 없이도 실제 앱 검증을 실행한다.
    reference = ThreadingHTTPServer(('127.0.0.1', 0), partial(ReferenceHandler, directory=str(source))) if source.is_dir() else None
    reference_worker = threading.Thread(target=reference.serve_forever, daemon=True) if reference else None
    output = root/'output/frontend_merge_stage2'
    output.mkdir(parents=True, exist_ok=True)
    worker.start()
    if reference_worker: reference_worker.start()
    try:
        for _ in range(100):
            if server.started: break
            time.sleep(.05)
        assert server.started
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            for label, size in [('desktop', {'width':1516,'height':1038}), ('mobile', {'width':390,'height':844})]:
                page = browser.new_page(viewport=size, reduced_motion='reduce')
                # 두 화면에 같은 시스템 폰트를 적용하여 네트워크 폰트 차이를 배제한다.
                page.route('https://fonts.googleapis.com/**', lambda route: route.abort())
                page.route('https://fonts.gstatic.com/**', lambda route: route.abort())
                if reference:
                    page.goto(f'http://127.0.0.1:{reference.server_port}')
                    expect(page.locator('[data-action="go:budget"]')).to_be_visible()
                    page.screenshot(path=str(output/f'reference-{label}.png'), full_page=True)
                errors = []
                page.on('pageerror', lambda error: errors.append(str(error)))
                page.goto(origin)
                page.evaluate("""() => {LunchRunState.setContext({location:{lat:37.5,lng:127,name:'시험 위치',source:'place'},conditions:{budget:9000,cuisine:'중식',people:2,deadline:Date.now()+30*60000}});dispatchEvent(new PopStateEvent('popstate'));}""")
                expect(page.locator('#db-menu-preview')).to_contain_text('짜장면')
                assert page.locator('.site-header .brand img').count() == 1
                assert page.locator('#dock button').count() == 5
                assert page.locator('[data-category]').count() == 15
                assert not page.locator('[data-category="중식"]').is_disabled()
                assert page.locator('#scene').count() == 0
                expect(page.locator('#screen [data-action="go:backend-games"]')).to_be_visible()
                if label == 'desktop':
                    screen = page.locator('#screen').bounding_box()
                    dock = page.locator('#dock').bounding_box()
                    actions = page.locator('#screen .actions').bounding_box()
                    footer = page.locator('.app footer').bounding_box()
                    assert screen['x'] + screen['width'] < dock['x']
                    assert actions['y'] + actions['height'] < footer['y']
                else:
                    assert page.evaluate('document.documentElement.scrollWidth') <= size['width']
                    assert page.locator('h1').bounding_box()['y'] >= page.locator('.site-header').bounding_box()['height']
                page.screenshot(path=str(output/f'merged-{label}.png'), full_page=True)
                page.locator('#location').click()
                expect(page.locator('.lr-location-dialog')).to_be_visible()
                expect(page.locator('[data-location-query]')).to_be_visible()
                page.screenshot(path=str(output/f'location-{label}.png'), full_page=True)
                page.locator('[data-location-close]').click()
                before = page.evaluate('LunchRunState.read().conditions')
                page.locator('#account').click()
                page.locator('#profile-nickname').fill('테스터')
                page.locator('.profile-save').click()
                expect(page.locator('.profile-label')).to_have_text('테스터')
                assert page.evaluate('LunchRunState.read().conditions') == before
                page.locator('[data-action="go:budget"]').click()
                page.wait_for_url(origin+'/budget')
                page.locator('#budget-input').fill('100000001')
                page.locator('[data-action="apply-budget"]').click()
                assert page.evaluate('LunchRunState.read().conditions.budget') == 100000
                assert page.evaluate('LunchRunState.read().conditions.cuisine') == '중식'
                page.goto(origin+'/distance')
                assert page.locator('input[type=range]').get_attribute('min') == '50'
                assert page.locator('input[type=range]').get_attribute('max') == '500'
                page.screenshot(path=str(output/f'distance-{label}.png'), full_page=True)
                assert errors == []
                page.close()
            browser.close()
    finally:
        if reference:
            reference.shutdown()
            reference.server_close()
            reference_worker.join(timeout=5)
        server.should_exit = True
        worker.join(timeout=10)
