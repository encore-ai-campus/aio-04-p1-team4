from contextlib import asynccontextmanager

import httpx
from fastapi import APIRouter, FastAPI, HTTPException, Request, Response
from fastapi.responses import RedirectResponse


NODE_ORIGIN = "https://lunchrun-games.onrender.com"
HOP_BY_HOP_HEADERS = {
    "connection",
    "content-encoding",
    "content-length",
    "host",
    "transfer-encoding",
}


@asynccontextmanager
async def proxy_lifespan(app: FastAPI):
    async with httpx.AsyncClient(timeout=60) as client:
        app.state.proxy_client = client
        yield


def create_proxy_router(url_prefix: str) -> APIRouter:
    router = APIRouter()

    @router.get("")
    async def game_redirect(request: Request):
        query = f"?{request.url.query}" if request.url.query else ""
        return RedirectResponse(f"{url_prefix}/{query}", status_code=307)

    async def proxy(path: str, request: Request):
        target_url = f"{NODE_ORIGIN}/{path}"
        if request.url.query:
            target_url = f"{target_url}?{request.url.query}"

        headers = {
            key: value
            for key, value in request.headers.items()
            if key.lower() not in HOP_BY_HOP_HEADERS
        }
        headers["x-forwarded-host"] = request.headers.get("host", "")
        headers["x-forwarded-proto"] = request.url.scheme
        headers["x-forwarded-prefix"] = url_prefix

        try:
            upstream = await request.app.state.proxy_client.request(
                request.method,
                target_url,
                headers=headers,
                content=await request.body(),
            )
        except httpx.RequestError as exc:
            raise HTTPException(
                status_code=502,
                detail="게임 서버에 연결할 수 없습니다. Node.js 서버가 실행 중인지 확인하세요.",
            ) from exc

        response_headers = {
            key: value
            for key, value in upstream.headers.items()
            if key.lower() not in HOP_BY_HOP_HEADERS
        }
        return Response(
            content=upstream.content,
            status_code=upstream.status_code,
            headers=response_headers,
        )

    @router.api_route("/", methods=["GET", "POST"])
    async def game_root(request: Request):
        return await proxy("", request)

    @router.api_route("/{path:path}", methods=["GET", "POST"])
    async def game_proxy(path: str, request: Request):
        return await proxy(path, request)

    return router


app = FastAPI(title="LunchRun game proxy", lifespan=proxy_lifespan)
app.include_router(create_proxy_router("/game"), prefix="/game")
