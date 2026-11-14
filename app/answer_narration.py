"""5단계: 서버의 사실 문장을 보존하며 Gemini가 답변의 연결·문단을 구성한다."""
from __future__ import annotations

import json
import logging
from pathlib import Path
from time import monotonic
from typing import Literal
from pydantic import BaseModel, ConfigDict, Field

logger = logging.getLogger('lunchrun.narration')
PROMPT_FILE = Path(__file__).parent / 'prompts' / 'narration_v1.txt'


class AnswerParagraph(BaseModel):
    """자유 사실 서술 대신 허용된 연결 표현과 서버 사실 ID만 받을 수 있다."""
    model_config = ConfigDict(extra='forbid', strict=True)
    opening: Literal['', '확인한 내용을 정리해드릴게요.', '이렇게 안내해드릴 수 있어요.', '현재 조건을 기준으로 정리해드릴게요.'] = ''
    fact_ids: list[int] = Field(min_length=1, max_length=40)
    closing: Literal['', '원하시면 조건을 바꿔 다시 추천받을 수 있어요.'] = ''


class AnswerPlan(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)
    paragraphs: list[AnswerParagraph] = Field(min_length=1, max_length=20)


def build_narration_messages(context: dict) -> list[dict]:
    """사용자 입력과 과거 대화는 지시가 아닌 데이터로 별도 전달한다."""
    system = PROMPT_FILE.read_text(encoding='utf-8')
    system += '\n출력 JSON Schema:\n' + json.dumps(AnswerPlan.model_json_schema(),ensure_ascii=False)
    return [{'role':'system','content':system},
            {'role':'user','content':json.dumps(context,ensure_ascii=False)}]


def validate_and_render(raw: str, facts: list[str]) -> str:
    """모든 사실을 정확히 한 번씩 원래 순서로 사용해야 한다. 변조된 문장은 받을 수 없다."""
    def unique_keys(pairs):
        result={}
        for key,value in pairs:
            if key in result: raise ValueError('duplicate_key')
            result[key]=value
        return result
    plan=AnswerPlan.model_validate(json.loads(raw,object_pairs_hook=unique_keys))
    ids=[i for paragraph in plan.paragraphs for i in paragraph.fact_ids]
    if ids != list(range(len(facts))):
        raise ValueError('fact_order_or_omission')
    paragraphs=[]
    for paragraph in plan.paragraphs:
        # 실제 식당명·상품·가격·주소·영업 여부·필수 안내는 모델 문장이 아닌 서버 값을 넣는다.
        parts=[paragraph.opening,*[facts[i] for i in paragraph.fact_ids],paragraph.closing]
        paragraphs.append('\n'.join(part for part in parts if part))
    answer='\n\n'.join(paragraphs)
    if not 1 <= len(answer) <= 5000: raise ValueError('answer_length')
    return answer


async def narrate_response(response, *, message, conditions, radius_m, location, state, gemini,
                           enabled=True, progress=None):
    """실패하더라도 추천·적용 조건·세션용 구조는 그대로 유지하고 서버 문장을 반환한다."""
    response['answer_source']='server'
    meta=response.get('_session') or {}
    # 모호한 질문/범위 밖/실행 전 오류는 정해진 안내가 더 정확하며 추가 호출을 하지 않는다.
    intent=meta.get('intent')
    if not enabled or intent not in {'recommend_menu','reroll_menu','search_restaurants',
            'list_menus','ask_restaurant_detail','explain_recommendation','change_conditions'}:
        response['narration']={'status':'skipped','reason':'disabled' if not enabled else 'fixed_reply'}
        return response
    if intent=='ask_restaurant_detail' and not response.get('restaurant_detail'):
        response['narration']={'status':'skipped','reason':'unresolved_target'}
        return response
    original=response['text']
    facts=[line for line in original.splitlines() if line.strip()]
    result=response.get('result') or {}
    selected=result.get('menu') if isinstance(response.get('result'),dict) else ({'id':state.selected_menu_id} if state and state.selected_menu_id else None)
    # 메뉴만 새로 뽑은 응답의 빈 목록을 예전 식당으로 채우지 않는다.
    places=(result.get('restaurants') or []) if isinstance(response.get('result'),dict) else ([item.model_dump() for item in state.displayed_restaurants] if state else [])
    # 최근 10턴과 현재 결과만 사용한다. 전체 메뉴 후보/DB나 인증키를 보내지 않는다.
    context={
        'question':message[:500],
        'conversation_history':[{'user':turn.user_message[:500],'assistant':turn.assistant_message[:1500]}
                                for turn in (state.turns[-10:] if state else [])],
        'intent':intent,'conditions':meta.get('effective_conditions') or conditions.model_dump(),
        'radius_m':meta.get('effective_radius_m',radius_m),'location_name':location.name,
        'selected_menu':{key:selected[key] for key in ('id','name') if key in selected} if selected else None,
        'restaurants':[{key:item[key] for key in ('id','restaurant_id','name','menu_name','price','open_status') if key in item}
                       for item in places[:3]],
        'menu_options':response.get('menu_options'),
        'restaurant_detail':response.get('restaurant_detail'),
        'facts':[{'id':i,'text':fact} for i,fact in enumerate(facts)],
    }
    started=monotonic()
    try:
        if progress: await progress({'event':'generating_answer','message':'답변을 정리하고 있어요.'})
        generated=await gemini.compose_answer(context)
        rendered=validate_and_render(generated['content'],facts)
        response['text']=rendered
        if isinstance(response.get('result'),dict): response['result']['message']=rendered
        response['answer_source']='gemini'
        response['narration']={'status':'success','elapsed_ms':round((monotonic()-started)*1000,2),
                               'usage':generated.get('usage')}
    except Exception as error:
        # CancelledError는 BaseException이므로 취소를 삼키지 않는다. 원문/질문/위치는 로그에 남기지 않는다.
        from .clients.gemini import GeminiError
        reason=error.code if isinstance(error,GeminiError) else 'narration_validation' if isinstance(error,(ValueError,TypeError,KeyError)) else 'narration_error'
        response['text']=original
        if isinstance(response.get('result'),dict): response['result']['message']=original
        response['answer_source']='server_fallback'
        response['narration']={'status':'fallback','reason':reason,'elapsed_ms':round((monotonic()-started)*1000,2)}
        logger.info('answer_fallback',extra={'event':'answer_fallback','error_code':reason})
    return response
