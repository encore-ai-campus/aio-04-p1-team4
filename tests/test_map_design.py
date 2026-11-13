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
                page.route('**/map/api/walking-route',lambda route:route.fulfill(content_type='application/json',body='{"distance":150,"duration":120,"paths":[[[127,37.499],[127.0001,37.4995],[127,37.5]]]}'))
                page.goto(origin+'/map/')
                page.evaluate("""() => {LunchRunState.setContext({location:{lat:37.499,lng:127,name:'시험 위치',source:'place'},conditions:{budget:9000,cuisine:'중식',deadline:Date.now()+30*60000}});LunchRunState.setMenu({id:'noodle',name:'짜장면'});}""")
                page.goto(origin+'/map/?search=1')
                expect(page.locator('.restaurant-item')).to_have_count(2)
                assert page.locator('.restaurant-item').first.locator('small').first.text_content()=='7,000원'
                assert page.locator('.data-note, #mode-label').count()==0
                if label=='desktop':
                    page.wait_for_function('Math.abs(document.querySelector("#list-title").getBoundingClientRect().top-document.querySelector("#map").getBoundingClientRect().top)<1')
                    assert page.locator('.map-actions').bounding_box()['y']+page.locator('.map-actions').bounding_box()['height']<size['height']
                    assert page.locator('.restaurant-item').first.bounding_box()['height']<110
                expect(page.locator('.map-stage-dock')).to_be_visible()
                page.screenshot(path=str(output/f'map-{label}.png'),full_page=True)
                started=time.monotonic()
                page.locator('#random').click()
                expect(page.locator('#random')).to_be_disabled()
                expect(page.locator('.restaurant-details')).to_have_count(0)
                expect(page.locator('#random')).to_be_enabled(timeout=6000)
                assert 1.8<=time.monotonic()-started<6
                page.locator("h1").click()
                page.locator('[data-restaurant="one"]').click()
                expect(page.locator('#selected-card')).to_be_hidden()
                expect(page.locator('.restaurant-details')).to_have_count(1)
                expect(page.locator('.restaurant-details')).to_contain_text('테스트')
                expect(page.locator('.restaurant-hours')).to_contain_text('요일')
                expanded=page.locator('[data-restaurant="one"]').locator('..').bounding_box()
                assert expanded['height']>page.locator('.restaurant-item').first.bounding_box()['height']
                page.screenshot(path=str(output/f'menu-{label}.png'),full_page=True)
                page.locator('[data-restaurant="one"]').click()
                expect(page.locator('.restaurant-details')).to_have_count(0)
                page.locator('[data-restaurant="one"]').click()
                expect(page.locator('.restaurant-details')).to_have_count(1)
                page.locator('.restaurant-details').click()
                expect(page.locator('.restaurant-details')).to_have_count(0)
                page.locator('[data-restaurant="one"]').click()
                page.locator('h1').click()
                expect(page.locator('.restaurant-details')).to_have_count(0)
                page.locator('[data-restaurant="one"]').click()
                expect(page.locator('.restaurant-details')).to_have_count(1)
                before=page.evaluate('LunchRunState.read().restaurants')
                page.reload()
                expect(page.locator('.restaurant-item')).to_have_count(2)
                expect(page.locator('[data-restaurant="one"]')).to_have_attribute('aria-pressed','true')
                expect(page.locator('[data-restaurant="one"]')).to_have_attribute('aria-expanded','false')
                expect(page.locator('.restaurant-details')).to_have_count(0)
                page.locator('[data-restaurant="one"]').click()
                expect(page.locator('.restaurant-details')).to_have_count(1)
                page.locator('h1').click()
                assert page.url==origin+'/map/'
                assert page.evaluate('LunchRunState.read().restaurants')==before
                page.locator('#confirm-route').click()
                expect(page.locator('.route-endpoint')).to_have_count(2)
                expect(page.locator('.route-endpoint.origin')).to_have_attribute('aria-label','출발 위치')
                expect(page.locator('.route-endpoint.origin')).to_have_text('')
                assert page.locator('.route-endpoint.origin').bounding_box()['width']==24
                page.emulate_media(reduced_motion='no-preference')
                glow=page.locator('.route-endpoint.origin').evaluate('(e)=>({name:getComputedStyle(e,"::after").animationName,duration:getComputedStyle(e,"::after").animationDuration})')
                assert glow=={'name':'origin-outer-glow-strong','duration':'3s'}
                page.emulate_media(reduced_motion='reduce')
                assert page.locator('.route-endpoint.destination .pin-number').count()==0
                expect(page.locator('.route-endpoint.destination')).to_have_text('')
                expect(page.locator('.route-endpoint.destination')).to_have_attribute('aria-label','one')
                for selector in ['.route-endpoint.origin','.route-endpoint.destination']:
                    marker=page.locator(selector)
                    assert marker.evaluate('(e)=>getComputedStyle(e).borderWidth')=='0px'
                    assert marker.evaluate('(e)=>getComputedStyle(e).boxShadow')=='none'
                assert page.locator('.route-endpoint.destination').bounding_box()['width']==30
                assert page.locator('.route-endpoint.origin').evaluate('(e)=>getComputedStyle(e,"::before").borderWidth')=='6px'

                expect(page.locator('#map-hint')).to_be_hidden()
                assert page.evaluate('window.testPolylines[0]')==[{'lat':37.499,'lng':127},{'lat':37.4995,'lng':127.0001},{'lat':37.5,'lng':127}]
                assert page.evaluate('LunchRunState.read().route.distance')==150
                assert page.evaluate('window.testBounds.padding')==[70,45,40,45]
                expect(page.locator('#selected-card')).to_be_hidden()
                expect(page.locator('#route-focus-summary')).to_contain_text('총 소요 예상 2분')
                expect(page.locator('#route-focus-summary')).to_contain_text('거리 150m')
                assert page.locator('.route-summary-lines>span').count()==2
                expect(page.locator('.route-value').first).to_have_text('2분')
                expect(page.locator('.route-value').last).to_have_text('150m')
                assert page.locator('.route-value').first.evaluate('(e)=>getComputedStyle(e).fontWeight')=='800'
                assert page.locator('.route-value').first.evaluate('(e)=>getComputedStyle(e).fontSize')=='16px'
                assert page.locator('#route-focus-summary>svg').count()==0
                assert page.locator('.route-summary-lines').evaluate('(e)=>getComputedStyle(e).textAlign')=='right'
                assert page.locator('#route-focus-summary').evaluate('(e)=>getComputedStyle(e).backgroundColor')=='rgba(255, 255, 255, 0.8)'
                assert page.locator('.restaurant-item:visible').count()==1
                assert page.evaluate('window.testPolylineColors[0]')=='#ff641a'
                expect(page.locator('#confirm-route')).to_be_hidden()
                assert page.locator('#kakao-map .backend-map-pin').count()==2
                action=page.locator('#random').bounding_box();box=page.locator('#map').bounding_box()
                assert abs(action['x']+action['width']/2-box['x']-box['width']/2)<1
                page.screenshot(path=str(output/f'route-{label}.png'),full_page=True)
                page.get_by_role('button',name='다른 식당 선택',exact=True).click()
                expect(page.locator('#confirm-route')).to_be_visible()
                expect(page.locator('#random')).to_have_text('식당 랜덤')
                assert page.locator('.restaurant-item:visible').count()==2
                expect(page.locator('.restaurant-details')).to_have_count(0)
                page.locator('.search-options summary').click()
                page.locator('h1').click()
                assert not page.locator('.search-options').evaluate('(e)=>e.open')
                page.locator('.search-options summary').click()
                expect(page.locator('#map-budget')).to_be_visible()
                page.locator('.search-options summary').click()
                assert page.locator('.search-options').evaluate('(e)=>e.open')
                expect(page.locator('#search-radius')).to_be_visible()
                assert page.locator('#precise-location,#map-center-search,#search-location,#search-again,#catalog-open,.map-links').count()==0
                expect(page.locator('#map-budget')).to_have_value('9,000원')
                page.locator('#budget-more').click()
                expect(page.locator('#map-budget')).to_have_value('10,000원')
                page.locator('#budget-less').click()
                page.locator('#map-budget').fill('12000')
                page.locator('#cuisine-filter').focus()
                expect(page.locator('#map-budget')).to_have_value('12,000원')
                page.locator('#radius-less').click()
                expect(page.locator('#radius-value')).to_have_text('450m')
                page.locator('#radius-more').click()
                expect(page.locator('#radius-value')).to_have_text('500m')
                page.locator('#search-radius').press('End')
                expect(page.locator('#radius-value')).to_have_text('500m')
                minus=page.locator('#radius-less').bounding_box();slider=page.locator('#search-radius').bounding_box();plus=page.locator('#radius-more').bounding_box()
                assert minus['x']<slider['x']<plus['x']
                assert page.locator('#map-budget').evaluate('(e)=>getComputedStyle(e).textAlign')=='center'
                assert page.locator('#change-location svg').count()==1
                assert page.evaluate('LunchRunState.read().conditions.budget')==9000
                page.screenshot(path=str(output/f'conditions-{label}.png'),full_page=True)
                with page.expect_response(lambda response:'/api/menus/candidates' in response.url):
                    page.get_by_role('button',name='변경 된 조건으로 재검색',exact=True).click()
                assert page.evaluate('LunchRunState.read().conditions.budget')==12000
                assert page.evaluate('LunchRunState.read().conditions.radius_m')==500
                assert not page.locator('.search-options').evaluate('(e)=>e.open')
                expect(page.locator('.restaurant-item')).to_have_count(2)

                page.locator('.search-options summary').click()
                if label=='desktop':
                    dock=page.locator('.map-stage-dock').bounding_box()
                    assert abs(dock['x']-(size['width']-max(22,(size['width']-1280)/2+25)-170))<1
                    assert abs(dock['y']+dock['height']-(size['height']-60))<1
                page.locator('#confirm-route').click()
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
