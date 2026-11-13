"""새 추천 정책은 임시 SQLite로 검증하며 실제 DB를 변경하지 않는다."""
from datetime import datetime, time
from zoneinfo import ZoneInfo

import pytest
from test_db_first_flow import database, add_place, products
from app.database import BusinessHours
from app.db_recommendations import candidate_payloads, restaurant_payloads, PRICE_NOTICE, HOURS_NOTICE

NOW = datetime(2026, 11, 9, 12, tzinfo=ZoneInfo('Asia/Seoul'))


@pytest.mark.parametrize('missing_price,missing_hours', [(True,False),(False,True),(True,True)])
def test_missing_data_recommended_with_exact_warnings(database, missing_price, missing_hours):
    with database.session_factory.begin() as s:
        r=add_place(s)
        if missing_price:
            r.menus[0].price=None
            r.menus[0].price_status='missing'
        if missing_hours:
            r.business_hours=[]
    with database.session_factory() as s:
        rows=products(s,now=NOW)
        place=restaurant_payloads(rows)[0]
        assert (PRICE_NOTICE in place['warnings']) == missing_price
        assert (HOURS_NOTICE in place['warnings']) == missing_hours
        assert place['open_status'] == ('unknown' if missing_hours else 'open')
        assert candidate_payloads(rows)[0]['verified_price'] == (None if missing_price else 7000)


def test_open_first_distance_limit_and_distinct_restaurants(database):
    with database.session_factory.begin() as s:
        for i in range(5):
            r=add_place(s,str(i),latitude=37.5+i*0.0001)
            if i==0: r.business_hours=[]
    with database.session_factory() as s:
        result=restaurant_payloads(products(s,now=NOW))
        assert [x['id'] for x in result] == ['1','2','3']
        assert len({x['id'] for x in result})==3


@pytest.mark.parametrize('reason', ['holiday','outside','break','budget'])
def test_known_exclusions(database,reason):
    with database.session_factory.begin() as s:
        r=add_place(s)
        if reason=='budget': r.menus[0].price=10000
        elif reason=='holiday': r.business_hours=[BusinessHours(day_of_week=0,holiday=True)]
        elif reason=='outside':
            r.business_hours=[BusinessHours(day_of_week=0,holiday=False,start_time=time(13),end_time=time(18))]
        else:
            r.business_hours=[BusinessHours(day_of_week=0,holiday=False,start_time=time(a),end_time=time(b),sequence=i) for i,(a,b) in enumerate([(9,11),(13,18)])]
    with database.session_factory() as s:
        assert products(s,now=NOW)==[]


def test_sold_out_ignored_and_unknown_holiday_warned(database):
    with database.session_factory.begin() as s:
        r=add_place(s)
        r.menus[0].availability_status='sold_out'
        for row in r.business_hours: row.holiday=None
    with database.session_factory() as s:
        item=restaurant_payloads(products(s,now=NOW))[0]
        assert item['warnings']==['휴무일 확인 필요']


def test_incomplete_today_is_unknown(database):
    with database.session_factory.begin() as s:
        r=add_place(s)
        r.business_hours=[BusinessHours(day_of_week=0,holiday=None)]
    with database.session_factory() as s:
        assert restaurant_payloads(products(s,now=NOW))[0]['open_status']=='unknown'


def test_overnight_previous_day_and_unknown_fills_remaining(database):
    with database.session_factory.begin() as s:
        r=add_place(s,'night')
        r.business_hours=[BusinessHours(day_of_week=6,holiday=False,start_time=time(22),end_time=time(2),ends_next_day=True)]
        add_place(s,'unknown',business_hours=[])
    with database.session_factory() as s:
        result=restaurant_payloads(products(s,now=NOW.replace(hour=1)))
        assert [(x['id'],x['open_status']) for x in result]==[('night','open'),('unknown','unknown')]
