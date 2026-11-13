from unittest.mock import AsyncMock, patch
from datetime import time
from fastapi.testclient import TestClient
from app.main import app
from app.database import Database, Restaurant, Menu, BusinessHours, PlaceDetailStatus


def test_map_details_and_nearby_use_database(tmp_path, monkeypatch):
    database = Database(f"sqlite:///{(tmp_path / 'map.db').as_posix()}")
    database.init_schema()
    monkeypatch.setattr(app.state, 'database', database)
    with database.session_factory.begin() as session:
        row = Restaurant(id='db-place', name='DB 식당', latitude=37.48, longitude=126.88,
                         address='서울', place_url='https://place.map.kakao.com/1', cuisine='한식', category_name='음식점 > 한식')
        row.detail_status = PlaceDetailStatus(menu_status='success', hours_status='success')
        row.menus = [Menu(menu_catalog_id='bibimbap', name='비빔밥', normalized_name='비빔밥', price=8000, price_status='known')]
        row.business_hours = [BusinessHours(day_of_week=day, holiday=False, start_time=time(0),
                              end_time=time(0), ends_next_day=True, sequence=0) for day in range(7)]
        session.add(row)
    try:
        with TestClient(app) as client:
            detail = client.get('/map/api/restaurants/db-place')
            assert detail.status_code == 200
            assert detail.json()['menus'][0]['price'] == 8000
            assert len(detail.json()['business_hours']) == 7
            assert detail.json()['open_status'] == 'open'
            catalog = client.get('/map/api/menu-search', params={'query':'비빔밥'}).json()
            assert catalog['items'][0]['restaurant_id'] == 'db-place'
            assert client.get('/map/api/restaurants/missing').status_code == 404
            found = {'id':'db-place','name':'DB 식당','lat':37.48,'lng':126.88,'address':'서울',
                     'place_url':'https://place.map.kakao.com/1','category':'음식점 > 한식',
                     'category_group_code':'FD6','search_keyword':'음식점','distance_m':0}
            with patch('app.clients.kakao.KakaoClient.search_restaurants', AsyncMock(return_value={'items':[found],'has_more':False})):
                result = client.post('/map/api/nearby', json={'location':{'lat':37.48,'lng':126.88,'name':'출발','source':'place'},
                    'radius_m':500,'conditions':{'budget':9000,'minutes':30,'cuisine':'한식'}})
            assert result.status_code == 200
            assert result.json()['restaurants'][0]['price'] == 8000
            assert result.json()['candidate_restaurants'] == []
    finally:
        database.dispose()
