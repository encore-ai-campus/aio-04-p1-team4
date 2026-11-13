"""기존 카카오 지도 화면과 경로 조회를 FastAPI에 연결한다."""

from importlib import import_module

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse

from .config import PROJECT_ROOT
from typing import Annotated
from fastapi import Depends
from sqlalchemy.orm import Session
from sqlalchemy import select
from .database import get_db, Restaurant, Menu
from .schemas import RecommendationRequest
from .recommendation_engine import current_open_status

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


@router.get('/api/menu-search')
def menu_search(session: Annotated[Session, Depends(get_db)], query: str = ''):
    query = query.strip()
    if not 1 <= len(query) <= 100:
        raise HTTPException(422, '검색어를 1~100자로 입력해주세요.')
    rows = session.execute(select(Menu, Restaurant).join(Restaurant, Restaurant.id == Menu.restaurant_id)
        .where(Menu.name.contains(query, autoescape=True)).order_by(Menu.name, Restaurant.name).limit(101)).all()
    return {'has_more': len(rows) > 100, 'items': [{'restaurant_id': r.id, 'restaurant_name': r.name,
        'address': r.address, 'place_url': r.place_url, 'menu_name': m.name, 'price': m.price,
        'price_status': m.price_status} for m, r in rows[:100]]}


@router.get('/api/restaurants/{restaurant_id}')
def restaurant_details(restaurant_id: str, session: Annotated[Session, Depends(get_db)]):
    if session.get_bind().dialect.name == 'postgresql':
        from uuid import UUID
        try:
            restaurant_id = str(UUID(restaurant_id))
        except ValueError:
            raise HTTPException(404, '저장된 식당 상세정보가 없습니다.')
    row = session.get(Restaurant, restaurant_id)
    if row is None:
        raise HTTPException(404, '저장된 식당 상세정보가 없습니다.')
    opened, holiday_unknown = current_open_status(row.business_hours)
    detail = row.detail_status
    checked_at = (detail.hours_last_success_at or detail.last_success_at) if detail else None
    return {'id': row.id, 'name': row.name, 'place_url': row.place_url,
            'open_status': opened, 'holiday_unknown': holiday_unknown,
            'checked_at': checked_at.isoformat() if checked_at else None,
            'menus': [{'name': m.name, 'price': m.price, 'price_status': m.price_status} for m in row.menus],
            'business_hours': [{'day': h.day_of_week, 'holiday': h.holiday,
                'start': h.start_time.isoformat(timespec='minutes') if h.start_time else None,
                'end': h.end_time.isoformat(timespec='minutes') if h.end_time else None,
                'next_day': h.ends_next_day,
                'last_order': h.last_order_time.isoformat(timespec='minutes') if h.last_order_time else None}
                for h in sorted(row.business_hours, key=lambda h: (h.day_of_week, h.sequence))]}


@router.post('/api/nearby')
async def nearby(body: RecommendationRequest, request: Request, session: Annotated[Session, Depends(get_db)]):
    """지도 주변 탐색도 메뉴 후보와 동일한 DB 조건 판정을 사용한다."""
    from .db_recommendations import qualifying_products, restaurant_payloads
    products = qualifying_products(session, latitude=body.location.lat, longitude=body.location.lng,
        radius_m=body.radius_m, budget=body.conditions.budget, cuisine=body.conditions.cuisine,
        menu_id=body.menu_id)
    restaurants = restaurant_payloads(products)
    return {'restaurants': restaurants, 'candidate_restaurants': [], 'has_more': False,
        'source': 'database', 'message': f'DB 조건을 통과한 식당 {len(restaurants)}곳입니다. 인분 미확인 상품은 표시 가격 기준입니다.'}


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
