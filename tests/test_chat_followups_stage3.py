"""3단계: 표시 상품·순서와 후속 답변을 실제 API에서 검증한다(외부 API는 모의)."""
from datetime import datetime, time
from unittest.mock import patch
from zoneinfo import ZoneInfo
import pytest

import test_recommendations as base
from app.chat_policy import QuestionInterpretation, parse_interpretation
from app.database import Restaurant, Menu, BusinessHours
from app.services import _restaurant_detail_answer
from app.chat_sessions import DisplayedRestaurant


@pytest.fixture
def boundary():
    case=base.RecommendationTests()
    case.setUp()
    try:
        yield case
    finally:
        case.tearDown()


def ask(case, message, intent='search_restaurants', **fields):
    case.interpret.return_value=QuestionInterpretation.model_validate(
        {'intent':intent,**fields},
        context={'menu_ids':{'noodle','spicynoodle'},'restaurant_ids':{'test-place','second','third'}})
    response=case.client.post('/api/chat',json={**base.BODY,'message':message})
    assert response.status_code==200, response.text
    return response.json()


def add_three(case):
    # 모두 영업 중이며 거리·가격이 달라 첫째~셋째를 구별할 수 있다.
    with case.test_database.session_factory.begin() as s:
        for rid,lat,price in [('second',37.4801,8500),('third',37.4802,9000)]:
            row=Restaurant(id=rid,name=rid,latitude=lat,longitude=126.88,cuisine='중식',address=rid+' 주소')
            row.menus=[Menu(name=rid+' 짜장면',normalized_name=rid+'짜장면',menu_catalog_id='noodle',price=price,price_status='known')]
            row.business_hours=[BusinessHours(day_of_week=d,holiday=False,start_time=time(0),end_time=time(0),ends_next_day=True) for d in range(7)]
            s.add(row)
    return ask(case,'짜장면 식당 알려줘')


@pytest.mark.parametrize('ordinal,rid,price',[('첫 번째','test-place',8000),('두 번째','second',8500),('세 번째','third',9000)])
def test_numbered_price_uses_displayed_order_even_if_model_selects_wrong_id(boundary,ordinal,rid,price):
    first=add_three(boundary)
    data=ask(boundary,ordinal+' 식당 가격은?','ask_restaurant_detail',restaurant_id='test-place',requested_detail='price')
    assert data['restaurant_detail']['restaurant_id']==rid
    assert data['restaurant_detail']['price']==price
    saved=boundary.client.get('/api/chat/session').json()
    assert [x['restaurant_id'] for x in saved['displayed_restaurants']]==[x['id'] for x in first['result']['restaurants']]
    assert saved['displayed_restaurants'][0]['product_id']==first['result']['restaurants'][0]['product_id']


def test_price_does_not_switch_to_new_cheapest_product(boundary):
    first=ask(boundary,'짜장면 식당 알려줘')
    with boundary.test_database.session_factory.begin() as s:
        row=s.get(Restaurant,'test-place')
        row.menus[0].price=9500
        row.menus.append(Menu(name='미니 짜장면',normalized_name='미니짜장면',menu_catalog_id='noodle',price=3000,price_status='known'))
    data=ask(boundary,'첫 번째 식당 가격은?','ask_restaurant_detail',restaurant_id='test-place',requested_detail='price')
    assert data['restaurant_detail']['price']==8000
    assert data['restaurant_detail']['product_id']==first['result']['restaurants'][0]['product_id']
    assert '앞서 표시한 가격 기준' in data['text']
    # 다시 조회하면 새 목록에 실제로 선택된 3000원 상품이 다음 질문의 기준이 된다.
    ask(boundary,'짜장면 식당 다시 알려줘')
    data=ask(boundary,'첫 번째 가격은?','ask_restaurant_detail',restaurant_id='test-place',requested_detail='price')
    assert data['restaurant_detail']['price']==3000


def test_missing_price_has_exact_message(boundary):
    with boundary.test_database.session_factory.begin() as s:
        menu=s.get(Restaurant,'test-place').menus[0]
        menu.price=None
        menu.price_status='missing'
    ask(boundary,'짜장면 식당 알려줘')
    data=ask(boundary,'그 식당 가격은?','ask_restaurant_detail',restaurant_id='test-place',requested_detail='price')
    assert data['text']=='해당 식당의 메뉴 가격 확인 불가'
    assert data['restaurant_detail']['price'] is None


def test_missing_address_has_exact_message(boundary):
    ask(boundary,'짜장면 식당 알려줘')
    with boundary.test_database.session_factory.begin() as s:
        s.get(Restaurant,'test-place').address=''
    data=ask(boundary,'그 식당 주소 알려줘','ask_restaurant_detail',restaurant_id='test-place',requested_detail='address')
    assert data['text']=='주소가 명시되어 있지 않습니다'


def test_ambiguous_reference_does_not_accept_model_guess(boundary):
    add_three(boundary)
    data=ask(boundary,'그 식당 주소 알려줘','ask_restaurant_detail',restaurant_id='test-place',requested_detail='address')
    assert '번호나 이름' in data['text']
    assert 'restaurant_detail' not in data
    assert boundary.client.get('/api/chat/session').json()['pending_action']['kind']=='select_restaurant'
    # 번호로 고른 후의 '그 식당'은 방금 선택한 식당을 뜻한다.
    ask(boundary,'두 번째 주소','ask_restaurant_detail',restaurant_id='second',requested_detail='address')
    data=ask(boundary,'그 식당 가격은?','ask_restaurant_detail',restaurant_id='test-place',requested_detail='price')
    assert data['restaurant_detail']['restaurant_id']=='second'


def test_out_of_range_ordinal_requests_clarification(boundary):
    add_three(boundary)
    data=ask(boundary,'4번째 가격은?','ask_restaurant_detail',restaurant_id='test-place',requested_detail='price')
    assert '번호나 이름' in data['text']
    assert 'restaurant_detail' not in data


def test_deleted_first_row_does_not_shift_second_position(boundary):
    add_three(boundary)
    with boundary.test_database.session_factory.begin() as s:
        s.delete(s.get(Restaurant,'test-place'))
    data=ask(boundary,'두 번째 식당 가격은?','ask_restaurant_detail',restaurant_id='second',requested_detail='price')
    assert data['restaurant_detail']['restaurant_id']=='second'
    assert [x['id'] for x in boundary.interpret.call_args.kwargs['restaurants']]==['test-place','second','third']


def test_hours_recomputed_at_each_question_and_unknown_exact_message(boundary):
    ask(boundary,'짜장면 식당 알려줘')
    with boundary.test_database.session_factory.begin() as s:
        row=s.get(Restaurant,'test-place')
        # 기존 구간을 먼저 삭제 확정하여 동일 요일·순번 UNIQUE 충돌을 피한다.
        row.business_hours=[]
        s.flush()
        row.business_hours=[BusinessHours(day_of_week=0,holiday=False,start_time=time(9),end_time=time(18))]
    # 판정 함수만 시간이 흐른 것처럼 호출한다. DB의 기존 open 표시를 재사용하지 않는다.
    import app.db_recommendations as policy
    original=policy.recommendation_hours
    for hour,expected in [(12,'open'),(19,'closed')]:
        fixed=datetime(2026,11,9,hour,tzinfo=ZoneInfo('Asia/Seoul'))
        with patch('app.db_recommendations.recommendation_hours',side_effect=lambda row: original(row,now=fixed)):
            data=ask(boundary,'지금 영업 중이야?','ask_restaurant_detail',restaurant_id='test-place',requested_detail='hours')
        assert data['restaurant_detail']['open_status']==expected
    with boundary.test_database.session_factory.begin() as s:
        s.get(Restaurant,'test-place').business_hours=[]
    data=ask(boundary,'지금 영업 중이야?','ask_restaurant_detail',restaurant_id='test-place',requested_detail='hours')
    assert data['text']=='영업시간 미기재로 인해 알 수 없습니다'


def test_menu_and_restaurant_reason_use_recommendation_context(boundary):
    ask(boundary,'메뉴 추천해줘','recommend_menu')
    data=ask(boundary,'왜 추천했어?','explain_recommendation')
    assert '앞서 입력해주신 조건에 부합하는 메뉴를 추천드렸습니다.' in data['text']
    assert '반경: 500m' in data['text'] and '예산: 10,000원 이하' in data['text']
    ask(boundary,'식당 알려줘')
    data=ask(boundary,'왜 추천했어?','explain_recommendation')
    assert data['text']=='현재 위치를 기반으로 추천한 메뉴를 판매하는 식당을 추천드렸습니다.'


def test_new_menu_recommendation_invalidates_previous_restaurants(boundary):
    ask(boundary,'식당 알려줘')
    ask(boundary,'메뉴 추천해줘','recommend_menu')
    data=ask(boundary,'첫 번째 식당 가격은?','ask_restaurant_detail',restaurant_id='test-place',requested_detail='price')
    assert '다시 조회' in data['text']
    assert boundary.client.get('/api/chat/session').json()['displayed_restaurants']==[]


def test_budget_exceeded_wording_uses_displayed_amount(boundary):
    # 정상 추천에서는 초과 상품이 제외된다. 방어 분기의 고정 문구도 직접 검증한다.
    with boundary.test_database.session_factory() as s:
        text,detail=_restaurant_detail_answer(s,'test-place','price','noodle',7000,
            DisplayedRestaurant(restaurant_id='test-place',name='테스트 식당',menu_name='짜장면',price=8000))
    assert '예산에 적합하지 않음' in text and detail['price']==8000


def test_reason_intent_is_validated_without_fabricated_target():
    assert parse_interpretation('{"intent":"explain_recommendation"}',{'noodle'}).intent=='explain_recommendation'


def test_displayed_products_survive_ten_turn_window(boundary, monkeypatch):
    # 10턴 이상 연속 검증만 테스트용 제한을 늘린다. 운영 요청 제한은 유지한다.
    from app.rate_limit import InMemoryChatRateLimiter
    monkeypatch.setattr(base.app.state,'chat_rate_limiter',InMemoryChatRateLimiter(100,1000))
    add_three(boundary)
    for _ in range(11):
        ask(boundary,'왜 추천했어?','explain_recommendation')
    data=ask(boundary,'세 번째 식당 가격은?','ask_restaurant_detail',restaurant_id='third',requested_detail='price')
    assert data['restaurant_detail']['price']==9000
    saved=boundary.client.get('/api/chat/session').json()
    assert len(saved['turns'])==10
    assert len(saved['displayed_restaurants'])==3


def test_changed_conditions_clear_displayed_products_and_reason(boundary):
    add_three(boundary)
    boundary.interpret.return_value=QuestionInterpretation(intent='explain_recommendation')
    data=boundary.client.post('/api/chat',json={**base.BODY,'conditions':{'budget':7000},'message':'왜 추천했어?'}).json()
    assert '먼저 메뉴 또는 식당을 추천받아' in data['text']
    saved=boundary.client.get('/api/chat/session').json()
    assert saved['displayed_restaurants']==[]
    assert saved['last_recommendation_kind'] is None


def test_followup_stream_uses_same_snapshot(boundary):
    import json
    add_three(boundary)
    boundary.interpret.return_value=QuestionInterpretation.model_validate(
        {'intent':'ask_restaurant_detail','restaurant_id':'second','requested_detail':'price'},
        context={'restaurant_ids':{'second'}})
    with boundary.client.stream('POST','/api/chat/stream',json={**base.BODY,'message':'두 번째 식당 가격은?'}) as response:
        events=[json.loads(line) for line in response.iter_lines() if line]
    assert events[-1]['event']=='completed'
    assert events[-1]['data']['restaurant_detail']['price']==8500
    assert 'searching' not in [e['event'] for e in events]
