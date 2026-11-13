"""4단계 조건 즉시 적용: 운영 DB·외부 API 없이 실제 일반/스트림 API를 검증한다."""
import json
import pytest
from pydantic import ValidationError
import test_recommendations as base
from app.chat_policy import QuestionInterpretation, parse_interpretation

@pytest.fixture
def boundary():
    case=base.RecommendationTests(); case.setUp()
    try: yield case
    finally: case.tearDown()


def change(case, *, patch=None, adjustment=None, radius=500, conditions=None, search=False, stream=False):
    case.interpret.return_value=QuestionInterpretation(intent='change_conditions',
        condition_patch=patch or {},radius_adjustment=adjustment,search_after_change=search)
    body={**base.BODY,'radius_m':radius,'message':'조건 변경'}
    if conditions: body['conditions']=conditions
    if stream:
        with case.client.stream('POST','/api/chat/stream',json=body) as response:
            events=[json.loads(line) for line in response.iter_lines() if line]
        assert events[-1]['event']=='completed',events
        return events[-1]['data'],events
    response=case.client.post('/api/chat',json=body)
    assert response.status_code==200,response.text
    return response.json(),[]


def test_immediate_budget_and_session_use_new_value(boundary):
    data,_=change(boundary,patch={'budget':8000})
    assert data['applied_patch']=={'budget':8000}
    assert data['suggested_patch'] is None
    assert '변경 전: 10,000원 → 변경 후: 8,000원' in data['text']
    assert data['result']['menu']['id']=='noodle'
    assert data['result']['restaurants']==[]
    assert '식당까지 추천해드릴까요?' in data['text']
    saved=boundary.client.get('/api/chat/session').json()
    assert saved['conditions']['budget']==8000
    assert saved['displayed_restaurants']==[]
    boundary.search.assert_not_awaited()


@pytest.mark.parametrize('radius,direction,expected,notice',[
    (500,'decrease',450,'50 m 축소 하였습니다.'),
    (100,'increase',150,'50 m 확대 하였습니다.'),
    (75,'decrease',50,'25 m 축소 하였습니다.'),
    (475,'increase',500,'25 m 확대 하였습니다.'),
    (50,'decrease',50,'최소 반경입니다.'),
    (500,'increase',500,'최대 반경입니다.'),
])
def test_relative_radius_boundaries(boundary,radius,direction,expected,notice):
    data,_=change(boundary,adjustment=direction,radius=radius)
    assert data['radius_m']==expected
    assert notice in data['text']
    assert data['applied_patch']==({'radius_m':expected} if expected!=radius else {})
    saved=boundary.client.get('/api/chat/session').json()
    assert saved['radius_m']==expected


def test_same_value_does_not_reroll_or_clear_list(boundary):
    first=boundary.client.post('/api/chat',json={**base.BODY,'message':'식당 알려줘'}).json()
    data,_=change(boundary,patch={'budget':10000})
    assert data['text']=='이미 해당 조건이 적용되어 있습니다.'
    assert data['result'] is None and data['applied_patch']=={}
    saved=boundary.client.get('/api/chat/session').json()
    assert saved['displayed_restaurants'][0]['product_id']==first['result']['restaurants'][0]['product_id']


def test_no_candidates_keeps_new_conditions_and_clears_old_list(boundary):
    boundary.client.post('/api/chat',json={**base.BODY,'message':'식당 알려줘'})
    data,_=change(boundary,patch={'cuisine':'한식'})
    assert data['result']['menu'] is None
    assert '변경된 조건에 맞는 메뉴가 없습니다' in data['text']
    saved=boundary.client.get('/api/chat/session').json()
    assert saved['conditions']['cuisine']=='한식'
    assert saved['displayed_restaurants']==[] and saved['selected_menu'] is None


def test_combined_change_and_search_returns_new_list_in_single_request(boundary):
    data,events=change(boundary,patch={'cuisine':'중식','budget':9000},search=True,stream=True)
    assert data['conditions']['cuisine']=='중식' and data['conditions']['budget']==9000
    assert data['search_performed'] is True
    assert len(data['result']['restaurants'])==1
    assert '바뀐 조건에 의한 메뉴는 짜장면입니다.' in data['text']
    assert '1. 테스트 식당 · 짜장면 · 8,000원' in data['text']
    assert 'searching' in [e['event'] for e in events]
    saved=boundary.client.get('/api/chat/session').json()
    assert saved['conditions']['budget']==9000
    assert len(saved['displayed_restaurants'])==1
    boundary.interpret.assert_awaited_once()
    boundary.search.assert_not_awaited()


def test_relative_change_contract_rejects_conflicts_and_other_intents():
    valid=parse_interpretation('{"intent":"change_conditions","radius_adjustment":"decrease"}',set())
    assert valid.radius_adjustment=='decrease'
    for value in [
        {'intent':'recommend_menu','radius_adjustment':'increase'},
        {'intent':'change_conditions','condition_patch':{'radius_m':100},'radius_adjustment':'increase'},
        {'intent':'change_conditions','condition_patch':{'radius_m':600}},
    ]:
        with pytest.raises(ValidationError): parse_interpretation(json.dumps(value),set())
