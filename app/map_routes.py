"""기존 카카오 지도 화면과 경로 조회를 FastAPI에 연결한다."""

from importlib import import_module

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse

from .config import PROJECT_ROOT

# 하이픈이 있는 기존 데모 폴더의 경로 계산 코드를 그대로 재사용한다.
walking = import_module("kakao-map.walk_routes")
MAP_DIRECTORY = PROJECT_ROOT / "kakao-map"
router = APIRouter(prefix="/map", tags=["map"])


@router.get("", include_in_schema=False)
def map_redirect():
    # 상대 경로로 지정한 CSS·JS가 /map/ 아래에서 로딩되게 한다.
    return RedirectResponse(url="/map/", status_code=307)


@router.get("/", include_in_schema=False)
def map_index():
    return FileResponse(MAP_DIRECTORY / "index.html")


@router.get("/config.json", include_in_schema=False)
def map_config(request: Request):
    return JSONResponse(
        {"javascriptKey": request.app.state.settings.kakao_javascript_key},
        headers={"Cache-Control": "no-store"},
    )


@router.post("/api/walking-route")
def map_walking_route(body: dict, request: Request):
    origin = request.headers.get("origin")
    if origin and origin != str(request.base_url).rstrip("/"):
        raise HTTPException(status_code=403, detail="같은 서버에서 요청해주세요.")
    try:
        result = walking.walking_route(
            body,
            PROJECT_ROOT,
            api_key=request.app.state.settings.map_api_key.get_secret_value(),
        )
    except walking.RouteError as error:
        return JSONResponse(
            {"error": error.message},
            status_code=error.status,
            headers={"Cache-Control": "no-store"},
        )
    return JSONResponse(result, headers={"Cache-Control": "no-store"})


@router.get("/{filename}", include_in_schema=False)
def map_asset(filename: str):
    # 데모 폴더 전체를 공개하지 않고 화면에 필요한 파일만 제공한다.
    path = MAP_DIRECTORY / filename
    if (
        path.suffix not in {".html", ".css", ".js"}
        or path.resolve().parent != MAP_DIRECTORY.resolve()
        or not path.is_file()
    ):
        raise HTTPException(status_code=404, detail="파일을 찾을 수 없습니다.")
    return FileResponse(path)
