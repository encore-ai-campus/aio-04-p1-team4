"""홈·게임·AI·지도가 공유하는 읽기 전용 식당/상품 조건 판정."""
from collections import defaultdict
from datetime import datetime
from zoneinfo import ZoneInfo
import math

from sqlalchemy import bindparam, select, text, or_
from sqlalchemy.orm import selectinload

from .database import Restaurant, Menu, MenuCatalog
from .food_types import matches_food_type
from .recommendation_engine import current_open_status

# 1단계: 누락 정보는 탈락 사유 대신 사용자에게 확인 문구로 전달한다.
PRICE_NOTICE = '해당 식당의 메뉴 가격 확인 불가'
HOURS_NOTICE = '영업시간 미기재로 인해 알 수 없습니다'


def recommendation_hours(restaurant, now=None):
    """오늘의 시간표 누락과 실제 영업 종료를 구분한다. 휴무는 우선 제외한다."""
    # 6단계: 폐업으로 확인된 식당은 남아 있는 과거 시간표보다 폐업 상태를 우선한다.
    if restaurant.operating_status == 'closed':
        return 'closed', False
    current = now.astimezone(ZoneInfo('Asia/Seoul')) if now else datetime.now(ZoneInfo('Asia/Seoul'))
    rows = restaurant.business_hours
    today = current.weekday()
    if any(row.day_of_week == today and row.holiday is True for row in rows):
        return 'closed', False
    state, holiday_unknown = current_open_status(rows, now=current)
    # 전날 시작한 심야 영업도 기존 시간 비교 함수가 확인한다.
    if state == 'open':
        return state, holiday_unknown
    today_rows = [row for row in rows if row.day_of_week == today]
    if not today_rows or any(row.start_time is None or row.end_time is None for row in today_rows):
        return 'unknown', False
    return 'closed', False


def distance_m(lat1, lng1, lat2, lng2):
    a,b=math.radians(lat1),math.radians(lat2)
    h=math.sin((b-a)/2)**2+math.cos(a)*math.cos(b)*math.sin(math.radians(lng2-lng1)/2)**2
    return 6371008.8*2*math.asin(math.sqrt(min(1,max(0,h))))


def _import_metadata(session, restaurant_ids):
    if session.get_bind().dialect.name != 'postgresql' or not restaurant_ids:
        return {}
    statement=text('SELECT payload FROM "Lunchrun".csv_import_record '
        "WHERE record_kind='menus' AND payload->>'restaurant_id' IN :ids").bindparams(bindparam('ids',expanding=True))
    return {(p['restaurant_id'],p['normalized_name']):p for p in session.scalars(statement,{'ids':list(restaurant_ids)})}


def qualifying_products(session, *, latitude, longitude, radius_m, budget, cuisine='전체',
                        menu_id=None, excluded_menu_ids=None, now: datetime | None=None):
    """정확한 대표 메뉴 FK와 실제 상품 가격·영업 상태로 후보를 판정한다."""
    lat_delta=radius_m/110000
    lng_delta=radius_m/(110000*max(abs(math.cos(math.radians(latitude))),1e-6))
    query=(select(Restaurant,Menu,MenuCatalog)
        .join(Menu,Menu.restaurant_id==Restaurant.id)
        .join(MenuCatalog,MenuCatalog.id==Menu.menu_catalog_id)
        .where(Restaurant.latitude.between(max(-90,latitude-lat_delta),min(90,latitude+lat_delta)),
            Restaurant.operating_status!='closed',MenuCatalog.active.is_(True),
            # 품절은 판정하지 않으며, 가격 미확인은 확인 필요 추천으로 허용한다.
            or_(Menu.price.is_(None), Menu.price<=budget))
        .options(selectinload(Restaurant.business_hours),selectinload(Restaurant.detail_status)))
    if -180<=longitude-lng_delta and longitude+lng_delta<=180:
        query=query.where(Restaurant.longitude.between(longitude-lng_delta,longitude+lng_delta))
    if menu_id:query=query.where(MenuCatalog.id==menu_id)
    if excluded_menu_ids:query=query.where(MenuCatalog.id.not_in(excluded_menu_ids))
    rows=session.execute(query.order_by(MenuCatalog.name,Menu.price,Restaurant.name,Menu.id)).all()
    metadata=_import_metadata(session,{r.id for r,_,_ in rows})
    eligible=[];rest_cache={}
    for r,m,c in rows:
        if r.id not in rest_cache:
            distance=distance_m(latitude,longitude,r.latitude,r.longitude)
            state,holiday_unknown=recommendation_hours(r,now=now)
            valid=(distance<=radius_m and matches_food_type(cuisine,r.cuisine or r.category_name)
                and state!='closed')
            rest_cache[r.id]=(valid,distance,state,holiday_unknown)
        valid,distance,state,holiday_unknown=rest_cache[r.id]
        if not valid:continue
        info=metadata.get((r.id,m.normalized_name),{})
        if info.get('catalog_status','linked')!='linked':continue
        warnings=[]
        if m.price is None: warnings.append(PRICE_NOTICE)
        if state == 'unknown': warnings.append(HOURS_NOTICE)
        if holiday_unknown: warnings.append('휴무일 확인 필요')
        eligible.append({'restaurant':r,'menu':m,'catalog':c,'distance_m':round(distance),
            'open_status':state, 'serving_status':'unverified',
            'serving_unverified':False,'warnings':warnings})
    return eligible


def candidate_payloads(products):
    groups=defaultdict(list)
    for item in products:groups[item['catalog'].id].append(item)
    result=[]
    for menu_id,items in groups.items():
        c=items[0]['catalog'];prices=[x['menu'].price for x in items if x['menu'].price is not None]
        unverified=False
        warnings=list(dict.fromkeys(w for x in items for w in x['warnings']))
        result.append({'id':menu_id,'name':c.name,'cuisine':c.cuisine,'search_keyword':c.name,
            'description':'주변 DB 식당의 메뉴 후보입니다.',
            'source':'database','price_verified':bool(prices) and all(x['menu'].price is not None for x in items),'verified_price':min(prices) if prices else None,
            'verified_price_max':max(prices) if prices else None,'price_hint':None,
            'nearby_restaurant_count':len({x['restaurant'].id for x in items}),
            'serving_unverified':unverified,'serving_status':'unverified',
            'warnings':warnings})
    return sorted(result,key=lambda x:(x['name'],x['id']))


def restaurant_payloads(products):
    groups=defaultdict(list)
    for item in products:groups[item['restaurant'].id].append(item)
    result=[]
    for rid,items in groups.items():
        # 같은 식당의 여러 상품 중 가격 확인 상품을 우선하여 한 행만 표시한다.
        x=min(items,key=lambda x:(x['menu'].price is None,x['menu'].price or 0,x['menu'].name,x['menu'].id));r=x['restaurant'];m=x['menu']
        result.append({'id':rid,'kakao_id':r.kakao_id,'name':r.name,'category':r.category_name or r.cuisine,
            'address':r.address,'lat':r.latitude,'lng':r.longitude,'place_url':r.place_url,
            'distance_m':x['distance_m'],'menu_name':m.name,'menu_id':x['catalog'].id,
            'product_id':m.id,'price':m.price,'price_status':m.price_status,'menu_verified':True,
            'open_status':x['open_status'],'recommendation_kind':'recommendation','source':'database',
            'serving_status':x['serving_status'],'serving_unverified':x['serving_unverified'],
            'availability_status':m.availability_status,'warnings':x['warnings'],
            'menu_verified_at':m.verified_at.isoformat() if m.verified_at else None})
    # 영업 확인 식당 우선, 각 그룹에서 가까운 순으로 최대 세 식당만 반환한다.
    return sorted(result,key=lambda x:(x['open_status']!='open',x['distance_m'],x['name'],x['id']))[:3]
