"""추천·채팅 API와 4단계 식당 저장 세션을 연결하는 라우터."""

import asyncio
import json
import logging
from datetime import datetime, timezone
from time import monotonic
from typing import Annotated

import anyio
from fastapi import APIRouter, Depends, HTTPException, Request, Response
from fastapi.responses import JSONResponse, StreamingResponse
from sqlalchemy.orm import Session

from . import services
from .clients.kakao import KakaoClient, KakaoError
from .clients.groq import GroqClient, GroqError
from .chat_sessions import SESSION_COOKIE_NAME, new_session_id, valid_session_id
from .database import MenuCatalog, get_db
from .operations import readiness_report
from .observability import request_id_context
from .schemas import ChatRequest, RecommendationRequest
from .food_types import catalog_food_type


router = APIRouter(prefix="/api")
logger = logging.getLogger("lunchrun.api")


def _chat_session_id(request: Request, response: Response) -> str:
    """유효한 세션 쿠키를 재사용하고 없거나 변조됐으면 새 UUID4를 발급한다."""

    session_id = valid_session_id(request.cookies.get(SESSION_COOKIE_NAME))
    if session_id is not None:
        return session_id
    session_id = new_session_id()
    response.set_cookie(
        SESSION_COOKIE_NAME,
        session_id,
        max_age=request.app.state.settings.chat_session_ttl_seconds,
        httponly=True,
        secure=request.app.state.settings.cookie_secure,
        samesite="lax",
        path="/",
    )
    return session_id


async def _enforce_chat_rate_limit(request: Request, session_id: str) -> None:
    """세션별 제한을 넘은 요청은 외부 API 호출 전에 429로 거부한다."""

    result = await request.app.state.chat_rate_limiter.check(session_id)
    if not result.allowed:
        raise HTTPException(
            429,
            "채팅 요청이 너무 많습니다. 잠시 후 다시 시도해 주세요.",
            headers={
                "Retry-After": str(result.retry_after),
                "X-Error-Code": "chat_rate_limit",
            },
        )


@router.get("/groq/status")
async def groq_status(request: Request, refresh: bool = False):
    # 서버 내 단일 진행 요청과 60초 캐시를 공유합니다. 수동 확인도 최소 5초 간격입니다.
    state = request.app.state
    if not hasattr(state, "groq_status_lock"):
        state.groq_status_lock = asyncio.Lock()
    async with state.groq_status_lock:
        cache = getattr(state, "groq_status_cache", None)
        ttl = 5 if refresh else 60
        if cache and cache[0] == state.settings and monotonic() - cache[1] < ttl:
            result = {**cache[2], "cached": True}
        else:
            result = await GroqClient(state.settings).check_connection()
            result.update(checked_at=datetime.now(timezone.utc).isoformat(), cached=False)
            state.groq_status_cache = (state.settings, monotonic(), result.copy())
    # 브라우저·프록시 캐시 대신 위 서버 캐시만 사용하고 확인 시각을 함께 전달합니다.
    return JSONResponse(result, headers={"Cache-Control": "no-store"})


@router.get("/health")
def health():
    """프로세스가 HTTP 요청을 받을 수 있는지만 확인하는 가벼운 생존 점검."""

    return {"status": "ok"}


@router.get("/readiness")
async def readiness(request: Request, refresh: bool = False):
    """외부 API를 호출하지 않고 DB·메뉴·브라우저·필수 설정을 확인한다."""

    cache = getattr(request.app.state, "readiness_cache", None)
    if cache and not refresh and monotonic() - cache[0] < 30:
        report, status_code = cache[1], cache[2]
    else:
        report, status_code = await anyio.to_thread.run_sync(
            readiness_report,
            request.app.state.database,
            request.app.state.settings,
        )
        request.app.state.readiness_cache = (monotonic(), report, status_code)
    return JSONResponse(
        report,
        status_code=status_code,
        headers={"Cache-Control": "no-store"},
    )


@router.post("/menus/candidates")
async def game_menu_candidates(
    body: RecommendationRequest,
    request: Request,
    session: Annotated[Session, Depends(get_db)],
):
    """게임 연출에 사용할 후보만 반환하며 외부 검색은 실행하지 않는다."""
    result = await services.recommend(
        body.conditions, body.location, body.radius_m,
        KakaoClient(request.app.state.settings.map_api_key),
        session=session, database=request.app.state.database,
        search_restaurants=False,
    )
    return {"menus": result["menus"], "message": result["message"],
            "location": body.location.model_dump(), "radius_m": body.radius_m}


@router.post("/menus/draw")
async def draw_menu(
    body: RecommendationRequest,
    request: Request,
    session: Annotated[Session, Depends(get_db)],
):
    """게임 1단계: 현재 위치·반경·예산·음식 종류로 메뉴만 추첨한다."""

    # 추첨 단계와 식당 조회 단계 모두 DB만 읽으며 외부 식당 검색은 실행하지 않는다.
    result = await services.recommend(
        body.conditions,
        body.location,
        body.radius_m,
        KakaoClient(request.app.state.settings.map_api_key),
        session=session,
        database=request.app.state.database,
        search_restaurants=False,
    )
    return {**result, "location": body.location.model_dump(), "radius_m": body.radius_m}


@router.post("/recommendations")
async def recommendations(body: RecommendationRequest, request: Request,
                          session: Annotated[Session, Depends(get_db)]):
    # 요청별 읽기 전용 DB 세션으로 확정 조건에 맞는 저장된 식당을 조회한다.
    client = KakaoClient(request.app.state.settings.map_api_key)
    try:
        result = await services.recommend(
            body.conditions, body.location, body.radius_m, client, body.menu_id,
            session, request.app.state.database,
            detail_success_ttl_hours=(
                request.app.state.settings.detail_success_ttl_hours
            ),
            detail_failure_retry_minutes=(
                request.app.state.settings.detail_failure_retry_minutes
            ),
        )
    except KakaoError as error:
        # 인증 실패를 빈 결과나 가상 식당으로 대체하지 않고 안전한 오류를 반환합니다.
        logger.warning(
            "recommendation_external_error",
            extra={"event": "recommendation_failed", "error_code": error.code},
        )
        raise HTTPException(error.status_code, error.message, headers={"X-Error-Code": error.code}) from None
    return {**result, "location": body.location.model_dump(), "radius_m": body.radius_m}


async def _record_chat_result(
    body: ChatRequest,
    request: Request,
    session_id: str,
    result: dict,
    progress=None,
) -> dict:
    """일반·스트리밍 API가 성공 결과를 동일한 세션 규칙으로 기록하게 한다."""

    # 외부 호출까지 성공한 응답만 최근 10턴과 현재 추천 상태에 기록한다.
    # 서비스의 세션 지시는 브라우저 응답에 노출하지 않고 검증된 상태 모델에만 적용한다.
    # 5단계: 서버의 실행 결과가 확정된 뒤에만 설명한다. 성공/실패 어느 쪽도 조건을 바꾸지 않는다.
    from .answer_narration import narrate_response
    old_state=await request.app.state.chat_sessions.get(session_id)
    await narrate_response(result,message=body.message.strip(),conditions=body.conditions,
        radius_m=body.radius_m,location=body.location,state=old_state,
        groq=GroqClient(request.app.state.settings),enabled=request.app.state.settings.groq_narration_enabled,
        progress=progress)
    session_meta = result.pop("_session", {})
    # 4단계: 요청 당시 값 대신 서버가 실제 적용한 조건을 일반·스트림에 동일하게 기록한다.
    effective_conditions = body.conditions.model_validate(session_meta.get('effective_conditions') or body.conditions.model_dump())
    effective_radius = session_meta.get('effective_radius_m',body.radius_m)
    state = await request.app.state.chat_sessions.record_exchange(
        session_id,
        user_message=body.message.strip(),
        assistant_message=result["text"],
        conditions=effective_conditions,
        location=body.location,
        radius_m=effective_radius,
        requested_menu_id=None if session_meta.get('conditions_changed') else body.menu_id,
        response=result,
        pending_action=session_meta.get("pending_action"),
        clear_pending=bool(session_meta.get("clear_pending")),
        last_intent=session_meta.get("intent"),
    )
    return {
        **result,
        "location": body.location.model_dump(),
        "radius_m": effective_radius,
        "conditions": effective_conditions.model_dump(),
        "session_version": state.version,
    }


@router.post("/chat")
async def chat(body: ChatRequest, request: Request, response: Response,
               session: Annotated[Session, Depends(get_db)]):
    # 기존 클라이언트 호환용 단일 JSON 응답도 스트림과 같은 서비스 경로를 사용한다.
    client = KakaoClient(request.app.state.settings.map_api_key)
    session_id = _chat_session_id(request, response)
    await _enforce_chat_rate_limit(request, session_id)
    conversation_state = await request.app.state.chat_sessions.get(session_id)
    try:
        result = await services.chat(
            body.message.strip(), body.conditions, body.menu_id, body.location,
            body.radius_m, client, GroqClient(request.app.state.settings), session,
            request.app.state.database, conversation_state,
            detail_success_ttl_hours=(
                request.app.state.settings.detail_success_ttl_hours
            ),
            detail_failure_retry_minutes=(
                request.app.state.settings.detail_failure_retry_minutes
            ),
        )
    except (KakaoError, GroqError) as error:
        # 외부 오류 원문이나 키는 공개하지 않고 진단 코드만 헤더에 포함합니다.
        logger.warning(
            "chat_external_error",
            extra={"event": "chat_failed", "error_code": error.code},
        )
        raise HTTPException(error.status_code, error.message, headers={"X-Error-Code": error.code}) from None
    return await _record_chat_result(body, request, session_id, result)


@router.post("/chat/stream")
async def chat_stream(
    body: ChatRequest,
    request: Request,
    session: Annotated[Session, Depends(get_db)],
):
    """JSON Lines로 진행상태와 최종 채팅 결과를 한 연결에서 전달한다."""

    existing_id = valid_session_id(request.cookies.get(SESSION_COOKIE_NAME))
    session_id = existing_id or new_session_id()
    # 같은 브라우저가 버튼을 연속으로 눌러 외부 수집을 중복 실행하지 못하게 한다.
    active_streams: set[str] = request.app.state.active_chat_streams
    if session_id in active_streams:
        return JSONResponse(
            {"detail": "이미 처리 중인 채팅 요청이 있습니다."}, status_code=409
        )
    await _enforce_chat_rate_limit(request, session_id)
    active_streams.add(session_id)
    conversation_state = await request.app.state.chat_sessions.get(session_id)
    queue: asyncio.Queue[dict | None] = asyncio.Queue()

    async def progress(event: dict) -> None:
        """서비스의 HTTP 비의존 이벤트를 현재 응답 큐에 넣는다."""

        await queue.put(event)

    async def worker() -> None:
        client = KakaoClient(request.app.state.settings.map_api_key)
        request_token = request_id_context.set(request.state.request_id)
        try:
            result = await services.chat(
                body.message.strip(),
                body.conditions,
                body.menu_id,
                body.location,
                body.radius_m,
                client,
                GroqClient(request.app.state.settings),
                session,
                request.app.state.database,
                conversation_state,
                detail_success_ttl_hours=(
                    request.app.state.settings.detail_success_ttl_hours
                ),
                detail_failure_retry_minutes=(
                    request.app.state.settings.detail_failure_retry_minutes
                ),
                progress=progress,
            )
            final = await _record_chat_result(body, request, session_id, result, progress=progress)
            await queue.put(
                {
                    "event": "completed",
                    "message": "추천 결과가 준비됐어요.",
                    "data": final,
                }
            )
        except (KakaoError, GroqError) as error:
            logger.warning(
                "chat_stream_external_error",
                extra={"event": "chat_stream_failed", "error_code": error.code},
            )
            await queue.put(
                {"event": "failed", "message": error.message, "code": error.code}
            )
        except Exception:
            # 스트림이 이미 시작된 뒤의 예외는 내부 원문 없이 안전한 이벤트로 끝낸다.
            await queue.put(
                {
                    "event": "failed",
                    "message": "요청을 처리하지 못했어요. 잠시 후 다시 시도해 주세요.",
                    "code": "chat_stream_error",
                }
            )
        finally:
            await queue.put(None)
            request_id_context.reset(request_token)

    async def events():
        task = asyncio.create_task(worker())
        try:
            yield json.dumps(
                {"event": "started", "message": "요청을 시작했어요."},
                ensure_ascii=False,
            ) + "\n"
            while True:
                event = await queue.get()
                if event is None:
                    break
                yield json.dumps(event, ensure_ascii=False) + "\n"
        finally:
            # 브라우저가 연결을 끊으면 Playwright와 외부 요청도 취소되도록 전달한다.
            if not task.done():
                task.cancel()
            active_streams.discard(session_id)

    response = StreamingResponse(
        events(),
        media_type="application/x-ndjson",
        headers={
            "Cache-Control": "no-store",
            "X-Accel-Buffering": "no",
        },
    )
    if existing_id is None:
        response.set_cookie(
            SESSION_COOKIE_NAME,
            session_id,
            max_age=request.app.state.settings.chat_session_ttl_seconds,
            httponly=True,
            secure=request.app.state.settings.cookie_secure,
            samesite="lax",
            path="/",
        )
    return response


@router.get("/chat/session")
async def chat_session(request: Request, response: Response,
                       session: Annotated[Session, Depends(get_db)]):
    """새로고침한 같은 브라우저가 최근 대화와 현재 조건을 복원하게 한다."""

    # 대화 문맥이 브라우저나 중간 프록시 캐시에 남지 않게 한다.
    response.headers["Cache-Control"] = "no-store"
    session_id = _chat_session_id(request, response)
    state = await request.app.state.chat_sessions.get(session_id)
    if state is None:
        return {"exists": False, "turns": []}

    # 세션에는 메뉴 ID만 저장하고 표시 정보는 DB의 최신 카탈로그에서 다시 읽는다.
    selected_menu = None
    if state.selected_menu_id:
        catalog = session.get(MenuCatalog, state.selected_menu_id)
        if catalog is not None and catalog.active:
            selected_menu = {
                "id": catalog.id,
                "name": catalog.name,
                "cuisine": catalog_food_type(catalog.cuisine),
                "description": catalog.description,
                "emoji": "🍽️",
                "source": "session",
            }
    return {
        "exists": True,
        "turns": [turn.model_dump(mode="json") for turn in state.turns],
        "conditions": state.conditions.model_dump() if state.conditions else None,
        "location": state.location.model_dump() if state.location else None,
        "radius_m": state.radius_m,
        "selected_menu": selected_menu,
        "restaurant_guidance": bool(selected_menu) and state.last_intent in {
            "recommend_menu", "reroll_menu", "search_restaurants", "ask_restaurant_detail"
        },
        # 3단계: 개발자 도구에서 실제 표시 순서와 상품·가격을 직접 확인할 수 있다.
        "displayed_restaurants": [item.model_dump() for item in state.displayed_restaurants],
        "last_recommendation_kind": state.last_recommendation_kind,
        "restaurant_ids": state.restaurant_ids,
        "candidate_restaurant_ids": state.candidate_restaurant_ids,
        "pending_action": (
            state.pending_action.model_dump() if state.pending_action else None
        ),
        "last_intent": state.last_intent,
        "version": state.version,
    }
