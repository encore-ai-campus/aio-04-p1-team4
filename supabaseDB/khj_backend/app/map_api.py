"""기존 5500 지도 화면과 place_url → DB 상세정보 수집을 한 서버로 제공한다."""
from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from datetime import datetime, timezone
import importlib.util
import os
from pathlib import Path
import sys

import anyio
from dotenv import dotenv_values
from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from .database import Database, Restaurant
from .database.cli import initialize_url
from .detail_collection import collect_restaurant_details
from .repositories.restaurants import save_restaurants

BACKEND = Path(__file__).resolve().parents[1]
WORKSPACE = BACKEND.parent
WEB = WORKSPACE / 'examples/kakao-map'
ALLOWED_ORIGINS = {f'http://{host}:{port}' for host in ('localhost', '127.0.0.1') for port in (5500, 8000)}

class PlaceInput(BaseModel):
    model_config = ConfigDict(extra='forbid')
    name: str = Field(min_length=1, max_length=200)
    lat: float = Field(ge=-90, le=90, allow_inf_nan=False)
    lng: float = Field(ge=-180, le=180, allow_inf_nan=False)
    address: str = Field(default='', max_length=500)
    category: str = Field(default='', max_length=300)

def utc(value):
    if value is None:
        return None
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)

def read_detail(database, rid):
    with database.session_factory() as session:
        row = session.scalar(select(Restaurant).where(Restaurant.id == rid).options(
            selectinload(Restaurant.menus), selectinload(Restaurant.business_hours), selectinload(Restaurant.detail_status)))
        if row is None or row.basic_source != 'kakao_api':
            return None
        status = row.detail_status
        return dict(id=row.id, name=row.name, latitude=row.latitude, longitude=row.longitude, address=row.address, place_url=row.place_url,
            menus=[dict(id=m.id, name=m.name, price=m.price, price_status=m.price_status) for m in row.menus
                if status and status.menu_source_url == row.place_url],
            business_hours=[dict(day_of_week=h.day_of_week, holiday=h.holiday, start_time=h.start_time,
                end_time=h.end_time, ends_next_day=h.ends_next_day, last_order_time=h.last_order_time, sequence=h.sequence)
                for h in sorted(row.business_hours, key=lambda h:(h.day_of_week,h.sequence))
                if status and status.hours_source_url == row.place_url],
            detail_status=dict(menu_status=status.menu_status if status else 'pending', hours_status=status.hours_status if status else 'pending',
                last_attempt_at=utc(status.last_attempt_at) if status else None, last_success_at=utc(status.last_success_at) if status else None,
                menu_source_url=status.menu_source_url if status else None, hours_source_url=status.hours_source_url if status else None,
                menu_checked_at=utc(status.menu_checked_at) if status else None, hours_checked_at=utc(status.hours_checked_at) if status else None,
                error_code=status.error_code if status else None))

def needs_collection(detail, force=False):
    status = detail['detail_status']
    attempted = status['last_attempt_at']
    age = (datetime.now(timezone.utc)-attempted).total_seconds() if attempted else float('inf')
    if force:
        return age >= 60  # 버튼 연타로 같은 페이지를 반복 수집하지 않는다.
    states = {status['menu_status'], status['hours_status']}
    if states & {'fetch_failed','parse_failed'}:
        return age >= 3600
    return ('pending' in states or age >= 7*86400 or
            status['menu_source_url'] != detail['place_url'] or status['hours_source_url'] != detail['place_url'])

def collect_in_worker(database, rid, collector):
    # Uvicorn의 Windows selector 루프와 브라우저 subprocess 루프를 분리한다.
    factory = asyncio.ProactorEventLoop if sys.platform == 'win32' else asyncio.new_event_loop
    with asyncio.Runner(loop_factory=factory) as runner:
        return runner.run(collect_restaurant_details(database, rid, collector))

def create_map_app(db_path: Path | None = None, collector=None):
    # 테스트용 경로는 환경변수보다 우선한다. 실서버는 비밀 연결문자열을 서버에서만 사용한다.
    env = {**dotenv_values(WORKSPACE/'.env'), **dotenv_values(BACKEND/'.env'), **os.environ}
    database_url = (f'sqlite:///{db_path.resolve().as_posix()}' if db_path else
        env.get('DATABASE_URL') or env.get('SUPABASE_DB_URL') or f'sqlite:///{(BACKEND/"data/lunchrun.db").as_posix()}')

    @asynccontextmanager
    async def lifespan(application):
        await anyio.to_thread.run_sync(initialize_url, database_url)
        application.state.database = Database(database_url)
        application.state.collection_slots = asyncio.Semaphore(2)
        application.state.place_locks = {}
        try:
            yield
        finally:
            application.state.database.dispose()

    app = FastAPI(title='LUNCH RUN 지도·DB 상세정보', lifespan=lifespan)

    @app.middleware('http')
    async def origin_guard(request, call_next):
        if request.method == 'POST' and request.headers.get('origin') not in ALLOWED_ORIGINS | {None}:
            return JSONResponse({'detail':'허용된 사이트에서 요청해주세요.'}, status_code=403)
        return await call_next(request)

    @app.get('/config.json')
    def config():
        env = {**dotenv_values(WORKSPACE/'.env'), **dotenv_values(BACKEND/'.env'), **os.environ}
        return JSONResponse({'javascriptKey': env.get('KAKAO_JAVASCRIPT_KEY','')}, headers={'Cache-Control':'no-store'})

    @app.get('/api/health')
    def health(request: Request):
        return {'status':'ok', 'database':request.app.state.database.engine.dialect.name, 'detail_collection':'place_url'}

    @app.get('/api/restaurants')
    async def restaurants(request: Request, limit: int = Query(100,ge=1,le=200), offset: int = Query(0,ge=0)):
        def load():
            with request.app.state.database.session_factory() as session:
                return [dict(id=r.id,name=r.name,latitude=r.latitude,longitude=r.longitude,address=r.address,place_url=r.place_url)
                        for r in session.scalars(select(Restaurant).where(Restaurant.basic_source=='kakao_api').order_by(Restaurant.id).limit(limit).offset(offset))]
        return await anyio.to_thread.run_sync(load)

    @app.get('/api/menu-catalog')
    async def catalog(request: Request):
        database = request.app.state.database
        def load():
            with database.session_factory() as session:
                ids=list(session.scalars(select(Restaurant.id).where(Restaurant.basic_source=='kakao_api')))
            rows=[]
            for rid in ids:
                data=read_detail(database,rid)
                if data is None:
                    continue
                rows.append(dict(id=rid,name=data['name'],address=data['address'],lat=data['latitude'],lng=data['longitude'],
                    url=data['place_url'],menus=data['menus'],status=data['detail_status']['menu_status'],
                    source='카카오 상세페이지 · DB',sourceUrl=data['detail_status']['menu_source_url'],
                    retrievedAt=data['detail_status']['menu_checked_at']))
            return dict(restaurants=rows,summary=dict(restaurantsWithMenus=sum(bool(r['menus']) for r in rows),
                menuCount=sum(len(r['menus']) for r in rows),pricedMenuCount=sum(m['price'] is not None for r in rows for m in r['menus'])))
        return await anyio.to_thread.run_sync(load)

    @app.get('/api/restaurants/{rid}')
    async def restaurant(rid: str, request: Request):
        if not rid.isascii() or not rid.isdecimal() or len(rid)>40:
            raise HTTPException(422,'카카오 장소 ID가 필요합니다.')
        result = await anyio.to_thread.run_sync(read_detail, request.app.state.database, rid)
        if result is None:
            raise HTTPException(404,'아직 DB에 저장되지 않은 식당입니다.')
        return result

    @app.post('/api/restaurants/{rid}/details')
    async def details(rid: str, body: PlaceInput, request: Request, refresh: bool = False):
        if not rid.isascii() or not rid.isdecimal() or len(rid)>40:
            raise HTTPException(422,'카카오 장소 ID가 필요합니다.')
        lock = request.app.state.place_locks.setdefault(rid, asyncio.Lock())
        database = request.app.state.database
        async with lock:
            def save():
                with database.session_factory() as session:
                    result=save_restaurants(session,[dict(id=rid,**body.model_dump(),place_url=f'https://place.map.kakao.com/{rid}')])
                    if not result.failed:
                        session.get(Restaurant,rid).basic_source='kakao_api'
                        session.commit()
                    return result
            saved = await anyio.to_thread.run_sync(save)
            if saved.failed:
                raise HTTPException(422,'식당 기본정보를 저장하지 못했습니다.')
            result = await anyio.to_thread.run_sync(read_detail,database,rid)
            mode = 'cached'
            if needs_collection(result,refresh):
                async with request.app.state.collection_slots:
                    await anyio.to_thread.run_sync(collect_in_worker,database,rid,collector)
                result = await anyio.to_thread.run_sync(read_detail,database,rid)
                mode = 'collected'
            return {**result,'collection':mode}

    @app.post('/api/walking-route')
    async def walking(request: Request):
        spec = importlib.util.spec_from_file_location('lunchrun_walk_routes', WEB/'walk_routes.py')
        module = importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
        try:
            body = await request.json()
            if not isinstance(body, dict):
                raise ValueError('invalid_body')
            return await anyio.to_thread.run_sync(module.walking_route, body, WORKSPACE)
        except module.RouteError as error:
            return JSONResponse({'error':error.message},status_code=error.status)
        except (ValueError,TypeError):
            return JSONResponse({'error':'출발지와 도착지를 확인해주세요.'},status_code=400)

    app.mount('/',StaticFiles(directory=WEB,html=True),name='map-screen')
    return app

app = create_map_app()
