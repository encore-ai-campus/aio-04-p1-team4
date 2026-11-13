"""FastAPI 애플리케이션 생성과 3단계 DB 생명주기 연결."""

from contextlib import asynccontextmanager
from pathlib import Path
from time import perf_counter

import anyio
from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles

from .api import router
from .chat_sessions import InMemoryChatSessionStore
from .config import load_settings
from .database import Database
from .locations import router as location_router  # 실제 위치 검색용 라우터를 별도로 연결합니다.
from .map_routes import router as map_router
from games.app import create_proxy_router, proxy_lifespan as games_proxy_lifespan
from .observability import (
    configure_logging,
    request_id_context,
    request_id_from_header,
)
from .rate_limit import InMemoryChatRateLimiter

STATIC = Path(__file__).resolve().parent.parent / "frontend"
settings = load_settings()
# 애플리케이션 전체에서 엔진 하나를 공유하고 요청마다 세션만 새로 만든다.
database = Database(settings.database_url)
logger = configure_logging()


@asynccontextmanager
async def lifespan(application: FastAPI):
    # 로컬 프로토타입에서는 누락된 테이블만 생성합니다. 외부 DB 전환 시 마이그레이션으로 교체합니다.
    await anyio.to_thread.run_sync(application.state.database.init_schema)
    try:
        async with games_proxy_lifespan(application):
            yield
    finally:
        # 메모리 세션은 개발용이므로 서버 종료 시 참조를 명시적으로 정리한다.
        await application.state.chat_sessions.clear()
        await application.state.chat_rate_limiter.clear()
        application.state.active_chat_streams.clear()
        # 서버 종료 시 연결 풀과 파일 핸들을 정리한다.
        application.state.database.dispose()


app = FastAPI(title="LunchRun-demo", version="0.1.0", lifespan=lifespan)
app.state.settings = settings
app.state.database = database
# Redis를 연결하기 전 단계에서는 프로세스 메모리에 최근 10턴을 보관한다.
app.state.chat_sessions = InMemoryChatSessionStore(
    ttl_seconds=settings.chat_session_ttl_seconds
)
# Redis 작업 큐 전에는 현재 프로세스 안에서 세션별 중복 스트림만 차단한다.
app.state.active_chat_streams = set()
app.state.chat_rate_limiter = InMemoryChatRateLimiter(
    settings.chat_requests_per_minute,
    settings.chat_requests_per_day,
)
app.include_router(router)
app.include_router(location_router)  # 추천용 가상 데이터와 위치 검색의 책임을 분리합니다.
app.include_router(map_router)
app.include_router(create_proxy_router("/games"), prefix="/games", tags=["games"])
app.mount("/static", StaticFiles(directory=STATIC), name="static")


@app.middleware("http")
async def request_observability(request: Request, call_next):
    """요청 ID·크기 제한·처리시간을 질문과 좌표 없이 기록한다."""

    request_id = request_id_from_header(request.headers.get("X-Request-ID"))
    request.state.request_id = request_id
    token = request_id_context.set(request_id)
    started = perf_counter()
    try:
        content_length = request.headers.get("Content-Length")
        try:
            too_large = bool(
                content_length and int(content_length) > settings.max_request_bytes
            )
        except ValueError:
            too_large = True
        if too_large:
            response = JSONResponse(
                {"detail": "요청 본문이 너무 큽니다."}, status_code=413
            )
        else:
            response = await call_next(request)
        response.headers["X-Request-ID"] = request_id
        logger.info(
            "request_completed",
            extra={
                "event": "request_completed",
                "method": request.method,
                "path": request.url.path,
                "status_code": response.status_code,
                "duration_ms": round((perf_counter() - started) * 1000, 2),
            },
        )
        return response
    except Exception:
        # 예외 원문에는 외부 URL 등이 포함될 수 있어 구조화 로그에는 고정 문구만 남긴다.
        logger.error(
            "request_failed",
            extra={
                "event": "request_failed",
                "method": request.method,
                "path": request.url.path,
                "duration_ms": round((perf_counter() - started) * 1000, 2),
            },
        )
        raise
    finally:
        request_id_context.reset(token)


@app.get("/", include_in_schema=False)
def index():
    return FileResponse(STATIC / "index.html")


@app.get("/config.json", include_in_schema=False)
def frontend_config():
    return JSONResponse({"apiBase": ""}, headers={"Cache-Control": "no-store"})


@app.get("/conditions", include_in_schema=False)
def conditions_page():
    """기존 조건 화면 주소는 홈으로 정규화한다."""
    return RedirectResponse('/', status_code=307)


def home_subpage():
    """새로고침과 직접 접속에도 같은 화면 셸을 제공한다."""
    return FileResponse(STATIC / 'index.html')


for page in ('ai', 'budget', 'time', 'distance', 'people', 'group-input', 'play', 'result'):
    app.add_api_route('/' + page, home_subpage, methods=['GET'], include_in_schema=False)


@app.get('/restaurants', include_in_schema=False)
@app.get('/route', include_in_schema=False)
def legacy_map_page():
    return RedirectResponse('/map/', status_code=307)


# 브라우저에 공개해도 되는 JavaScript 키만 반환합니다. 전체 설정이나 REST/Groq 키는 반환하지 않습니다.
@app.get("/api/public-config", include_in_schema=False)
def public_config():
    return {"kakaoJavascriptKey": app.state.settings.kakao_javascript_key}


app.mount("/", StaticFiles(directory=STATIC), name="frontend")
