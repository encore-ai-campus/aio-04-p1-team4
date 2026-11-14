"""6단계 전체 흐름. 실제 Gemini 검증만 별도 환경변수로 켜며 운영 DB는 사용하지 않는다."""
import json
import os
from datetime import time
import pytest
import httpx
from fastapi.testclient import TestClient
from app.main import app
from app.chat_policy import QuestionInterpretation
from app.database import Database, Restaurant, Menu, BusinessHours
from app.chat_sessions import InMemoryChatSessionStore
from app.rate_limit import InMemoryChatRateLimiter
from app.clients.gemini import GeminiClient
import test_recommendations as base


@pytest.fixture
def boundary(monkeypatch):
    case=base.RecommendationTests();case.setUp()
    monkeypatch.setattr(app.state,'settings',app.state.settings.model_copy(update={'gemini_narration_enabled':True}))
    case.narrate.side_effect=lambda context:{'content':json.dumps({'paragraphs':[
        {'fact_ids':list(range(len(context['facts']))),'opening':'확인한 내용을 정리해드릴게요.'}
    ]},ensure_ascii=False)}
    try: yield case
    finally: case.tearDown()


def ask(case,message,intent,**fields):
    case.interpret.return_value=QuestionInterpretation.model_validate({'intent':intent,**fields},
        context={'menu_ids':{'noodle','spicynoodle'},'restaurant_ids':{'test-place'}})
    response=case.client.post('/api/chat',json={**base.BODY,'menu_id':None,'message':message})
    assert response.status_code==200,response.text
    data=response.json()
    assert data['answer_source']=='gemini'
    return data


def test_recommend_reroll_change_search_followup_and_map_are_consistent(boundary):
    initial=ask(boundary,'메뉴 추천해줘','recommend_menu')
    assert initial['result']['menu']['id']=='noodle'
    boundary._add_second_eligible_menu()
    reroll=ask(boundary,'다른 메뉴 추천해줘','reroll_menu')
    assert reroll['result']['menu']['id']=='spicynoodle'
    changed=ask(boundary,'예산 8500원으로 바꾸고 식당도 찾아줘','change_conditions',
                condition_patch={'budget':8500},search_after_change=True)
    assert changed['result']['menu']['id']=='noodle'
    assert changed['conditions']['budget']==8500
    # 새 화면 조건으로 이어지는 다음 질문을 재현한다.
    boundary.interpret.return_value=QuestionInterpretation.model_validate(
        {'intent':'ask_restaurant_detail','restaurant_id':'test-place','requested_detail':'price'},
        context={'restaurant_ids':{'test-place'}})
    body={**base.BODY,'conditions':changed['conditions'],'menu_id':'noodle','message':'첫 번째 식당 가격은?'}
    detail=boundary.client.post('/api/chat',json=body).json()
    assert detail['restaurant_detail']['price']==8000
    mapped=boundary.client.post('/map/api/nearby',json={k:v for k,v in body.items() if k!='message'}).json()
    assert mapped['restaurants']==changed['result']['restaurants']
    saved=boundary.client.get('/api/chat/session').json()
    assert saved['conditions']['budget']==8500 and len(saved['turns'])==4
    boundary.search.assert_not_awaited();boundary.collect_details.assert_not_awaited()


def test_map_chat_and_recommendation_share_unknown_hours_policy(boundary):
    with boundary.test_database.session_factory.begin() as s:
        row=s.get(Restaurant,'test-place')
        row.business_hours=[]
        s.flush()
        row.business_hours=[BusinessHours(day_of_week=d,holiday=None) for d in range(7)]
    result=ask(boundary,'짜장면 식당 알려줘','search_restaurants',menu_id='noodle')
    detail=boundary.client.get('/map/api/restaurants/test-place').json()
    assert detail['open_status']==result['result']['restaurants'][0]['open_status']=='unknown'
    body={k:v for k,v in base.BODY.items() if k!='message'}
    mapped=boundary.client.post('/map/api/nearby',json=body).json()
    assert '인분' not in mapped['message']
    assert '영업시간 미기재로 인해 알 수 없습니다' in result['text']


def test_permanent_closure_overrides_old_timetable(boundary):
    ask(boundary,'식당 알려줘','search_restaurants',menu_id='noodle')
    with boundary.test_database.session_factory.begin() as s:
        s.get(Restaurant,'test-place').operating_status='closed'
    data=ask(boundary,'지금 영업 중이야?','ask_restaurant_detail',restaurant_id='test-place',requested_detail='hours')
    assert data['restaurant_detail']['open_status']=='closed'
    assert boundary.client.get('/map/api/restaurants/test-place').json()['open_status']=='closed'


def test_menu_list_has_at_most_three_and_does_not_pick_for_user(boundary):
    boundary._add_second_eligible_menu()
    data=ask(boundary,'어떤 메뉴가 있어?','list_menus')
    assert len(data['menu_options'])==2
    assert data['result'] is None
    assert boundary.client.get('/api/chat/session').json()['selected_menu'] is None
    # 네 종류가 되어도 최대 세 후보만 표시한다.
    with boundary.test_database.session_factory.begin() as session:
        row=session.get(Restaurant,'test-place')
        for mid,name in [('udon','우동'),('cutlet','돈가스')]:
            row.menus.append(Menu(name=name,normalized_name=name,menu_catalog_id=mid,price=8000,price_status='known'))
    data=ask(boundary,'가능한 메뉴를 보여줘','list_menus')
    assert len(data['menu_options'])==3


def test_food_description_is_fixed_notice_and_scope_message_is_exact(boundary):
    boundary.interpret.return_value=QuestionInterpretation.model_validate(
        {'intent':'ask_menu_detail','menu_id':'noodle'},context={'menu_ids':{'noodle'}})
    data=boundary.client.post('/api/chat',json={**base.BODY,'message':'짜장면은 어떤 음식이야?'}).json()
    assert data['text']=='음식 설명은 제공하지 않습니다. 메뉴 추천이나 식당 조회를 요청해주세요.'
    assert data['answer_source']=='server'
    boundary.interpret.return_value=QuestionInterpretation(intent='out_of_scope')
    data=boundary.client.post('/api/chat',json={**base.BODY,'message':'오늘 날씨 알려줘'}).json()
    assert data['text']=='메뉴 선정 및 식당 선정에 관한 질문만 말씀해주세요.'


@pytest.mark.skipif(os.environ.get('LUNCHRUN_LIVE_STAGE6')!='1',reason='실제 Gemini는 별도 선택 시에만 최대 6회 호출한다.')
def test_live_three_turns_with_six_http_request_ceiling(tmp_path,monkeypatch):
    # 실제 외부 모델 + 임시 식당 DB의 결합만 확인한다. 카카오나 운영 DB에는 접근하지 않는다.
    db=Database(f"sqlite:///{(tmp_path/'live_stage6.db').as_posix()}")
    db.init_schema()
    with db.session_factory.begin() as s:
        row=Restaurant(id='live-test',name='검증용 식당',latitude=37.48,longitude=126.88,cuisine='중식',address='검증용 주소')
        row.menus=[Menu(name='짜장면',normalized_name='짜장면',menu_catalog_id='noodle',price=8000,price_status='known')]
        row.business_hours=[BusinessHours(day_of_week=d,holiday=False,start_time=time(0),end_time=time(0),ends_next_day=True) for d in range(7)]
        s.add(row)
    calls=[]
    class LimitedTransport(httpx.AsyncBaseTransport):
        async def handle_async_request(self,request):
            if len(calls)>=6: raise httpx.ConnectError('live_budget_reached',request=request)
            payload=json.loads(request.content)
            kind='narration' if 'facts' in json.loads(payload['messages'][1]['content']) else 'interpretation'
            calls.append(kind)
            async with httpx.AsyncHTTPTransport() as transport:
                response=await transport.handle_async_request(request)
                await response.aread()
                return response
    settings=app.state.settings.model_copy(update={'gemini_narration_enabled':True})
    real=GeminiClient(settings,transport=LimitedTransport())
    monkeypatch.setattr(app.state,'database',db)
    monkeypatch.setattr(app.state,'settings',settings)
    monkeypatch.setattr(app.state,'chat_sessions',InMemoryChatSessionStore())
    monkeypatch.setattr(app.state,'chat_rate_limiter',InMemoryChatRateLimiter(100,1000))
    monkeypatch.setattr('app.api.GeminiClient',lambda _settings:real)
    summary=[]
    try:
        with TestClient(app) as client:
            for index,message in enumerate(['메뉴 추천해줘','이 메뉴 파는 식당 알려줘','첫 번째 식당 가격은?']):
                response=client.post('/api/chat',json={**base.BODY,'menu_id':None,'message':message})
                assert response.status_code==200,f'live turn {index+1}: HTTP {response.status_code}'
                data=response.json()
                summary.append({'turn':index+1,'answer_source':data['answer_source'],'narration':data['narration']})
                assert data['answer_source']=='gemini',f'live turn {index+1}: {data.get("narration",{}).get("reason")}'
                if index==0: assert data['result']['menu']['id']=='noodle'
                if index==1: assert data['result']['restaurants'][0]['price']==8000
                if index==2: assert data['restaurant_detail']['price']==8000
        # 키·질문·응답 원문 없이 호출 수와 추가 지연·사용량만 출력한다.
    finally:
        # 사용량 제한 등 중간 실패가 있어도 완료된 단계의 진단 수치를 남긴다.
        print('LIVE_STAGE6_SUMMARY='+json.dumps({'calls':len(calls),'steps':summary},ensure_ascii=False))
        db.dispose()
