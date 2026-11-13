"""DB 전용 후보의 조건 일치와 외부 호출 없는 추천을 검증한다."""
import asyncio
from datetime import time
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import func, select

from app.database import Database, Restaurant, Menu, BusinessHours, PlaceDetailStatus
from app.db_recommendations import qualifying_products, candidate_payloads
from app.menu_catalog import menu_candidates
from app.schemas import Conditions, SelectedLocation
from app.services import recommend


@pytest.fixture
def database(tmp_path):
    db = Database(f"sqlite:///{(tmp_path/'flow.db').as_posix()}")
    db.init_schema()
    yield db
    db.dispose()


def add_place(session, rid='one', price=7000, **changes):
    r = Restaurant(id=rid, name=rid, category_name='음식점 > 중식', cuisine='중식',
        latitude=37.5, longitude=127.0, address='테스트',
        detail_status=PlaceDetailStatus(menu_status='success', hours_status='success'))
    r.menus.append(Menu(name='짜장면', normalized_name='짜장면', menu_catalog_id='noodle',
        price=price, price_status='known'))
    r.business_hours = [BusinessHours(day_of_week=day, holiday=False,
        start_time=time(0), end_time=time(0), ends_next_day=True) for day in range(7)]
    for key, value in changes.items():
        setattr(r, key, value)
    session.add(r)
    return r


def products(session, **kwargs):
    return qualifying_products(session, latitude=37.5, longitude=127.0,
        radius_m=500, budget=9000, **kwargs)


def test_no_catalog_price_fallback(database):
    with database.session_factory() as s:
        assert products(s) == []
        assert menu_candidates(s, latitude=37.5, longitude=127.0, radius_m=500, budget=9000) == []


def test_exact_link_prices_without_portion_warning(database):
    with database.session_factory.begin() as s:
        add_place(s)
        add_place(s, 'two', price=8500)
        bad = add_place(s, 'unlinked', price=1000)
        bad.menus[0].menu_catalog_id = None
    with database.session_factory() as s:
        result = candidate_payloads(products(s))
        assert len(result) == 1
        assert result[0]['nearby_restaurant_count'] == 2
        assert (result[0]['verified_price'], result[0]['verified_price_max']) == (7000, 8500)
        # 1단계부터 인분·품절은 판정하거나 안내하지 않는다.
        assert not result[0]['serving_unverified']
        assert result[0]['warnings'] == []
        assert products(s, excluded_menu_ids={'noodle'}) == []


@pytest.mark.parametrize('reason', ['budget', 'distance', 'cuisine', 'closed'])
def test_reject_ineligible_products(database, reason):
    with database.session_factory.begin() as s:
        r = add_place(s)
        if reason == 'budget': r.menus[0].price = 10000
        if reason == 'distance': r.latitude = 37.6
        if reason == 'cuisine': r.cuisine = '한식'
        if reason == 'closed': r.operating_status = 'closed'
        if reason == 'hours': r.detail_status.hours_status = 'missing'
        if reason == 'sold_out': r.menus[0].availability_status = 'sold_out'
    with database.session_factory() as s:
        assert products(s, cuisine='중식') == []


def test_recommend_does_not_search_or_write(database):
    with database.session_factory.begin() as s:
        add_place(s)
    client = AsyncMock()
    client.search_restaurants.side_effect = AssertionError('external search forbidden')
    with database.session_factory() as s:
        before = s.scalar(select(func.count()).select_from(Menu))
        result = asyncio.run(recommend(Conditions(budget=9000),
            SelectedLocation(lat=37.5, lng=127.0, name='테스트', source='place'),
            500, client, session=s, database=database, menu_id='noodle'))
        assert result['source'] == 'database'
        assert result['menu']['id'] == 'noodle'
        assert len(result['restaurants']) == 1
        assert not result['restaurants'][0]['serving_unverified']
        assert s.scalar(select(func.count()).select_from(Menu)) == before
        assert not s.new and not s.dirty and not s.deleted
    client.search_restaurants.assert_not_called()


def test_home_draw_and_map_share_identical_candidates(database, monkeypatch):
    from fastapi.testclient import TestClient
    from app.main import app
    monkeypatch.setattr(app.state, 'database', database)
    with database.session_factory.begin() as s:
        add_place(s)
    payload = {'location':{'lat':37.5,'lng':127.0,'name':'시험','source':'place'},
        'radius_m':500,'conditions':{'budget':9000,'cuisine':'중식','minutes':30}}
    with TestClient(app) as client:
        pool = client.post('/api/menus/candidates', json=payload).json()['menus']
        drawn = client.post('/api/menus/draw', json=payload).json()['menu']
        result = client.post('/api/recommendations', json={**payload,'menu_id':drawn['id']}).json()
        nearby = client.post('/map/api/nearby', json={**payload,'menu_id':drawn['id']}).json()
        assert [m['id'] for m in pool] == [drawn['id']] == ['noodle']
        assert result['restaurants'] == nearby['restaurants']
        assert result['restaurants'][0]['price'] == drawn['verified_price'] == 7000
