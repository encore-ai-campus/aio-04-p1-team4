"""지도 디자인과 DB 연결을 두 화면 크기에서 검증한다."""
import threading
import time
from pathlib import Path
import uvicorn
from playwright.sync_api import sync_playwright, expect
from app.main import app
from test_db_first_flow import database, add_place
from test_game_browser_flow import free_port


def test_map_design_and_details(database, monkeypatch):
    with database.session_factory.begin() as session:
        add_place(session)
        add_place(session, 'two', price=8000)
    monkeypatch.setattr(app.state, 'database', database)
    root=Path(__file__).resolve().parents[1]
    output=root/'output/frontend_merge_stage5'
    output.mkdir(parents=True,exist_ok=True)
    port=free_port()
    origin=f'http://127.0.0.1:{port}'
    server=uvicorn.Server(uvicorn.Config(app,host='127.0.0.1',port=port,log_level='error'))
    worker=threading.Thread(target=server.run,daemon=True)
    worker.start()
    try:
        for _ in range(100):
            if server.started: break
            time.sleep(.05)
        assert server.started
        with sync_playwright() as playwright:
            browser=playwright.chromium.launch(headless=True)
            for label,size in [('desktop',{'width':1516,'height':1038}),('mobile',{'width':390,'height':844})]:
                page=browser.new_page(viewport=size,reduced_motion='reduce')
                errors=[]
                page.on('pageerror',lambda error: errors.append(str(error)))
                page.route('https://dapi.kakao.com/**',lambda route:route.fulfill(content_type='application/javascript',body=(root/'tests/map-sdk-stub.js').read_text(encoding='utf-8')))
                page.goto(origin+'/map/')
                page.evaluate("""() => {LunchRunState.setContext({location:{lat:37.5,lng:127,name:'시험 위치',source:'place'},conditions:{budget:9000,cuisine:'중식',deadline:Date.now()+30*60000}});LunchRunState.setMenu({id:'noodle',name:'짜장면'});}""")
                page.goto(origin+'/map/?search=1')
                expect(page.locator('.restaurant-item')).to_have_count(2)
                expect(page.locator('#restaurant-list')).not_to_contain_text('인분 미확인')
                expect(page.locator('.map-stage-dock')).to_be_visible()
                page.screenshot(path=str(output/f'map-{label}.png'),full_page=True)
                page.locator('[data-restaurant="one"]').click()
                expect(page.locator('#selected-card')).to_contain_text('7,000원')
                page.get_by_role('button',name='메뉴·가격 보기 (1개)').click()
                expect(page.locator('dialog')).to_contain_text('짜장면')
                page.screenshot(path=str(output/f'menu-{label}.png'),full_page=True)
                page.locator('dialog').get_by_role('button',name='닫기',exact=True).click()
                page.locator('#dock-route').click()
                assert '/map/' in page.url
                page.screenshot(path=str(output/f'detail-{label}.png'),full_page=True)
                assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
                page.locator('#account').click()
                expect(page.locator('.profile-dialog')).to_be_visible()
                page.locator('.profile-close').click()
                page.locator('#header-location').click()
                expect(page.locator('.lr-location-dialog')).to_be_visible()
                assert not errors, errors
                page.close()
            browser.close()
    finally:
        server.should_exit=True
        worker.join(timeout=10)
