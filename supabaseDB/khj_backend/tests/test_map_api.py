from datetime import datetime, timedelta, timezone

from fastapi.testclient import TestClient

from app.collectors import RawBusinessDay, RawMenu, RawPlacePage, PlaceCollectionError
from app.database import PlaceDetailStatus
from app.map_api import create_map_app


class Collector:
    def __init__(self):
        self.calls = 0
        self.fail = False

    async def collect(self, rid, url):
        self.calls += 1
        assert url == 'https://place.map.kakao.com/123'
        if self.fail:
            raise PlaceCollectionError('fetch_failed', 'page_timeout')
        return RawPlacePage(True, True, (RawMenu('김치찌개', '9,000원'),),
            (RawBusinessDay('월', ('11:00 ~ 21:00', '15:00 ~ 17:00 브레이크타임')),))


BODY = dict(name='테스트 식당', lat=37.48, lng=126.88, address='서울 금천구', category='음식점 > 한식')


def test_collect_persist_cache_and_failure_preserves_details(tmp_path):
    collector = Collector()
    app = create_map_app(tmp_path/'map.db', collector)
    with TestClient(app) as client:
        assert client.get('/api/restaurants/123').status_code == 404
        response = client.post('/api/restaurants/123/details', json=BODY)
        assert response.status_code == 200, response.text
        data = response.json()
        assert data['collection'] == 'collected'
        assert data['menus'][0]['price'] == 9000
        assert len(data['business_hours']) == 2
        assert data['detail_status']['menu_source_url'] == data['place_url']
        assert datetime.fromisoformat(data['detail_status']['hours_checked_at']).utcoffset() == timedelta(0)
        assert client.post('/api/restaurants/123/details', json=BODY).json()['collection'] == 'cached'
        assert collector.calls == 1
        with app.state.database.session_factory.begin() as session:
            session.get(PlaceDetailStatus, '123').last_attempt_at = datetime.now(timezone.utc)-timedelta(days=8)
        collector.fail = True
        failed = client.post('/api/restaurants/123/details', json=BODY).json()
        assert failed['detail_status']['menu_status'] == 'fetch_failed'
        assert failed['menus'] == data['menus']
        assert failed['business_hours'] == data['business_hours']
        assert failed['detail_status']['menu_checked_at'] == data['detail_status']['menu_checked_at']
        assert client.get('/api/restaurants/123').json()['menus'] == data['menus']
        assert client.post('/api/restaurants/123/details', json=BODY).json()['collection'] == 'cached'
        assert collector.calls == 2
        assert len(client.get('/api/restaurants').json()) == 1
    # 실제 DB 파일을 다시 열어도 데이터가 남는다.
    with TestClient(create_map_app(tmp_path/'map.db', collector)) as client:
        assert client.get('/api/restaurants/123').json()['menus'][0]['name'] == '김치찌개'


def test_validation_static_and_origin(tmp_path):
    with TestClient(create_map_app(tmp_path/'map.db', Collector())) as client:
        assert client.get('/').status_code == 200
        assert client.get('/db-details.js').status_code == 200
        assert client.get('/.env').status_code == 404
        assert client.post('/api/restaurants/license:123/details', json=BODY).status_code == 422
        assert client.post('/api/restaurants/123/details', json={**BODY,'place_url':'https://example.com'}).status_code == 422
        assert client.post('/api/restaurants/123/details', json=BODY, headers={'Origin':'https://example.com'}).status_code == 403
        assert client.get('/api/restaurants?limit=10000').status_code == 422
        assert client.post('/api/walking-route', json=[]).status_code == 400
        assert client.post('/api/walking-route', json={}).status_code == 400


def test_legacy_file_rows_are_not_displayed(tmp_path):
    from app.repositories.restaurants import save_restaurants
    app=create_map_app(tmp_path/'legacy.db', Collector())
    with TestClient(app) as client:
        with app.state.database.session_factory() as session:
            save_restaurants(session,[dict(id='123',**BODY,place_url='https://place.map.kakao.com/123')])
        assert client.get('/api/restaurants').json()==[]
        assert client.get('/api/restaurants/123').status_code==404
        assert client.get('/api/menu-catalog').json()['restaurants']==[]
        client.post('/api/restaurants/123/details',json=BODY)
        assert len(client.get('/api/restaurants').json())==1
        assert client.get('/api/menu-catalog').json()['summary']['menuCount']==1
        html=client.get('/').text
        for asset in ('nearby-data.js','cuisine-data.js','menus.js','business-hours-data.js'):
            assert f'src="{asset}' not in html


def test_conditional_holiday_is_not_a_weekly_closed_day():
    from app.place_details import parse_place_page
    page = RawPlacePage(False, True, (), (RawBusinessDay('월', ('매월 둘째 월요일 휴무',)),), '매월 둘째 월요일 휴무')
    result = parse_place_page(page)
    assert result.hours_status == 'parse_failed'
    assert not result.business_hours
