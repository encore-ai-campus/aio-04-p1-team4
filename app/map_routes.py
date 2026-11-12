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
from .clients.kakao import KakaoClient, KakaoError
from .repositories import save_restaurants
from .recommendation_engine import current_open_status
from .food_types import matches_food_type

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
    row = session.get(Restaurant, restaurant_id)
    if row is None:
        raise HTTPException(404, '저장된 식당 상세정보가 없습니다.')
    opened, holiday_unknown = current_open_status(row.business_hours)
    detail = row.detail_status
    return {'id': row.id, 'name': row.name, 'place_url': row.place_url,
            'open_status': opened, 'holiday_unknown': holiday_unknown,
            'checked_at': detail.last_success_at.isoformat() if detail and detail.last_success_at else None,
            'menus': [{'name': m.name, 'price': m.price, 'price_status': m.price_status} for m in row.menus],
            'business_hours': [{'day': h.day_of_week, 'holiday': h.holiday,
                'start': h.start_time.isoformat(timespec='minutes') if h.start_time else None,
                'end': h.end_time.isoformat(timespec='minutes') if h.end_time else None,
                'next_day': h.ends_next_day,
                'last_order': h.last_order_time.isoformat(timespec='minutes') if h.last_order_time else None}
                for h in sorted(row.business_hours, key=lambda h: (h.day_of_week, h.sequence))]}


@router.post('/api/nearby')
async def nearby(body: RecommendationRequest, request: Request, session: Annotated[Session, Depends(get_db)]):
    client = KakaoClient(request.app.state.settings.map_api_key)
    found, more = [], False
    try:
        for page in range(1, 4):
            result = await client.search_restaurants(
                '카페' if body.conditions.cuisine == '카페/빵' else '음식점',
                body.location.lat, body.location.lng, radius_m=body.radius_m, page=page,
                **({'category_group_code': 'CE7'} if body.conditions.cuisine == '카페/빵' else {}))
            found.extend(result['items'])
            more = result['has_more']
            if not more:
                break
    except KakaoError as error:
        raise HTTPException(error.status_code, error.message) from None
    save_restaurants(session, found)
    verified, candidates, seen = [], [], set()
    for item in found:
        if item['id'] in seen:
            continue
        seen.add(item['id'])
        row = session.get(Restaurant, item['id'])
        if not row or not matches_food_type(body.conditions.cuisine, row.cuisine or row.category_name):
            continue
        opened, unknown = current_open_status(row.business_hours)
        if opened == 'closed':
            continue
        prices = [m for m in row.menus if m.price_status == 'known' and m.price is not None and m.price <= body.conditions.budget]
        menu = min(prices, key=lambda m: m.price) if prices else None
        if row.menus and not menu and all(m.price_status == 'known' and m.price is not None for m in row.menus):
            continue
        entry = {**item, 'open_status': opened, 'price': menu.price if menu else None,
                 'menu_name': menu.name if menu else None, 'warnings': ['메뉴·가격·영업정보는 DB 확인 시점 기준']}
        (verified if menu and opened == 'open' and not unknown else candidates).append(entry)
    return {'restaurants': verified, 'candidate_restaurants': candidates, 'has_more': more,
            'message': f'카카오 검색 상위 {len(found)}곳을 DB와 비교했습니다. ' + ('추가 결과가 있을 수 있습니다.' if more else '')}


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
