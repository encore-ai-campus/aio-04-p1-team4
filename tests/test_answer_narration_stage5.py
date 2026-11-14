"""5단계의 사실 보존·추가 HTTP 호출·실패 대체를 외부 네트워크 없이 검증한다."""
import asyncio
import json
from unittest.mock import AsyncMock
import httpx
import pytest
from app.answer_narration import validate_and_render, narrate_response
from app.clients.gemini import GeminiClient, GeminiError
from app.config import Settings
from app.schemas import Conditions, SelectedLocation
from app.chat_sessions import ChatSessionState, ConversationTurn
import test_recommendations as base


def plan(facts,opening=''):
    return json.dumps({'paragraphs':[{'opening':opening,'fact_ids':list(range(len(facts))),'closing':''}]},ensure_ascii=False)


@pytest.fixture
def boundary(monkeypatch):
    case=base.RecommendationTests();case.setUp()
    monkeypatch.setattr(base.app.state,'settings',base.app.state.settings.model_copy(update={'gemini_narration_enabled':True}))
    try: yield case
    finally: case.tearDown()


def request(case,message='짜장면 식당 알려줘',stream=False):
    body={**base.BODY,'message':message}
    if stream:
        with case.client.stream('POST','/api/chat/stream',json=body) as response:
            events=[json.loads(line) for line in response.iter_lines() if line]
        assert events[-1]['event']=='completed',events
        return events[-1]['data'],events
    response=case.client.post('/api/chat',json=body)
    assert response.status_code==200,response.text
    return response.json(),[]


def test_success_preserves_facts_and_records_generated_answer(boundary):
    boundary.narrate.side_effect=lambda context:{'content':plan(context['facts'],'확인한 내용을 정리해드릴게요.'),'usage':{'total_tokens':123}}
    data,_=request(boundary)
    assert data['answer_source']=='gemini'
    assert data['text'].startswith('확인한 내용을 정리해드릴게요.')
    assert '1. 테스트 식당 · 짜장면 · 8,000원' in data['text']
    assert data['result']['message']==data['text']
    assert data['narration']['usage']['total_tokens']==123
    assert data['narration']['elapsed_ms']>=0
    saved=boundary.client.get('/api/chat/session').json()
    assert saved['turns'][-1]['assistant_message']==data['text']
    assert saved['displayed_restaurants'][0]['price']==8000


@pytest.mark.parametrize('raw',[
    '{"paragraphs":[{"fact_ids":[0]}]}',
    '{"paragraphs":[{"fact_ids":[1,0,2]}]}',
    '{"paragraphs":[{"fact_ids":[0,0,1,2]}]}',
    '{"paragraphs":[{"fact_ids":[0,1,2],"opening":"가짜식당은 100원이고 영업 중입니다"}]}',
    '{"paragraphs":[{"fact_ids":[0,1,2],"text":"가격 확인 필요 없음"}]}',
    '{"paragraphs":[{"fact_ids":[0,true,2]}]}',
    '{"paragraphs":[],"paragraphs":[]}',
    'not-json',
])
def test_omission_order_fabrication_and_duplicate_keys_are_rejected(raw):
    with pytest.raises((ValueError,TypeError)):
        validate_and_render(raw,['추천 메뉴: 짜장면','해당 식당의 메뉴 가격 확인 불가','영업시간 미기재로 인해 알 수 없습니다'])


def test_invalid_generated_plan_falls_back_without_changing_result(boundary):
    boundary.narrate.side_effect=None
    boundary.narrate.return_value={'content':'{"paragraphs":[{"fact_ids":[0]}]}'}
    data,_=request(boundary)
    assert data['answer_source']=='server_fallback'
    assert data['narration']['reason']=='narration_validation'
    assert '1. 테스트 식당 · 짜장면 · 8,000원' in data['text']
    assert data['result']['restaurants'][0]['price']==8000


@pytest.mark.parametrize('code',['gemini_rate_limit','gemini_timeout','gemini_connection','gemini_auth'])
def test_generation_failure_keeps_server_answer(boundary,code):
    boundary.narrate.side_effect=GeminiError(code,'private-secret')
    data,_=request(boundary)
    assert data['answer_source']=='server_fallback'
    assert data['narration']['reason']==code
    assert 'private-secret' not in json.dumps(data)
    assert data['result']['restaurants'][0]['price']==8000


def test_stream_has_progress_and_fallback_still_completed(boundary):
    data,events=request(boundary,stream=True)
    assert 'generating_answer' in [e['event'] for e in events]
    assert data['answer_source']=='server_fallback'
    assert 'failed' not in [e['event'] for e in events]


def test_disabled_does_not_make_generation_call(boundary,monkeypatch):
    monkeypatch.setattr(base.app.state,'settings',base.app.state.settings.model_copy(update={'gemini_narration_enabled':False}))
    data,_=request(boundary)
    assert data['answer_source']=='server'
    assert data['narration']['reason']=='disabled'
    boundary.narrate.assert_not_awaited()


def test_interpretation_failure_still_returns_error_without_narration(boundary):
    boundary.interpret.side_effect=GeminiError('gemini_rate_limit','해석 사용량 제한',503)
    response=boundary.client.post('/api/chat',json={**base.BODY,'message':'추천'})
    assert response.status_code==503
    boundary.narrate.assert_not_awaited()


def test_context_uses_latest_ten_turns_and_effective_conditions():
    async def run():
        state=ChatSessionState(turns=[ConversationTurn(user_message=str(i),assistant_message='과거 답변') for i in range(12)])
        gemini=AsyncMock()
        gemini.compose_answer.side_effect=lambda context:{'content':plan(context['facts'])}
        response={'text':'예산 변경 전: 10,000원 → 변경 후: 8,000원','result':{'menu':{'id':'noodle','name':'짜장면'},'restaurants':[]},
                  '_session':{'intent':'change_conditions','effective_conditions':{'budget':8000,'cuisine':'중식','minutes':30},'effective_radius_m':100}}
        await narrate_response(response,message='예산 변경',conditions=Conditions(),radius_m=500,
            location=SelectedLocation(**base.LOCATION),state=state,gemini=gemini)
        context=gemini.compose_answer.call_args.args[0]
        assert len(context['conversation_history'])==10
        assert context['conversation_history'][0]['user']=='2'
        assert context['conditions']['budget']==8000 and context['radius_m']==100
        assert context['restaurants']==[]
    asyncio.run(run())


def test_cancellation_is_not_converted_to_fallback():
    async def run():
        gemini=AsyncMock();gemini.compose_answer.side_effect=asyncio.CancelledError()
        with pytest.raises(asyncio.CancelledError):
            await narrate_response({'text':'추천 메뉴: 짜장면','_session':{'intent':'recommend_menu'}},
                message='추천',conditions=Conditions(),radius_m=500,location=SelectedLocation(**base.LOCATION),state=None,gemini=gemini)
    asyncio.run(run())


def test_generation_http_options_and_usage():
    def handler(request):
        body=json.loads(request.content)
        assert body['max_completion_tokens']==512
        assert body['response_format']=={'type':'json_object'}
        assert 'facts' in json.loads(body['messages'][1]['content'])
        return httpx.Response(200,json={'choices':[{'finish_reason':'stop','message':{'content':plan(['사실'])}}],
                                       'usage':{'total_tokens':50,'private':'private-secret'}})
    client=GeminiClient(Settings(map_api_key='fake',gemini_api_key='fake'),transport=httpx.MockTransport(handler))
    data=asyncio.run(client.compose_answer({'facts':[{'id':0,'text':'사실'}]}))
    assert data['usage']=={'total_tokens':50}


@pytest.mark.parametrize('status,code',[(401,'gemini_auth'),(429,'gemini_rate_limit'),(500,'gemini_upstream')])
def test_generation_http_failure_has_no_retry_or_private_response(status,code):
    calls=[]
    def handler(request):
        calls.append(request)
        return httpx.Response(status,json={'error':'private-secret'})
    client=GeminiClient(Settings(map_api_key='fake',gemini_api_key='fake'),transport=httpx.MockTransport(handler))
    with pytest.raises(GeminiError) as error: asyncio.run(client.compose_answer({'facts':[]}))
    assert error.value.code==code and 'private-secret' not in str(error.value)
    assert len(calls)==1


def test_missing_notices_are_preserved_on_success(boundary):
    from app.database import Restaurant
    with boundary.test_database.session_factory.begin() as session:
        row=session.get(Restaurant,'test-place')
        row.menus[0].price=None
        row.menus[0].price_status='missing'
        row.business_hours=[]
    boundary.narrate.side_effect=lambda context:{'content':plan(context['facts'],'확인한 내용을 정리해드릴게요.')}
    data,_=request(boundary)
    assert data['answer_source']=='gemini'
    assert '해당 식당의 메뉴 가격 확인 불가' in data['text']
    assert '영업시간 미기재로 인해 알 수 없습니다' in data['text']
    assert data['result']['restaurants'][0]['price'] is None


def test_generation_timeout_is_sanitized():
    def handler(request): raise httpx.ReadTimeout('private-secret',request=request)
    client=GeminiClient(Settings(map_api_key='fake',gemini_api_key='fake'),transport=httpx.MockTransport(handler))
    with pytest.raises(GeminiError) as error: asyncio.run(client.compose_answer({'facts':[]}))
    assert error.value.code=='gemini_timeout'
    assert 'private-secret' not in str(error.value)


def test_truncated_generation_is_rejected():
    client=GeminiClient(Settings(map_api_key='fake',gemini_api_key='fake'),transport=httpx.MockTransport(
        lambda request:httpx.Response(200,json={'choices':[{'finish_reason':'length','message':{'content':'{}'}}]})))
    with pytest.raises(GeminiError) as error: asyncio.run(client.compose_answer({'facts':[]}))
    assert error.value.code=='gemini_response'
