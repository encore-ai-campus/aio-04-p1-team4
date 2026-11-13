"""홈·게임·AI·지도가 공유하는 읽기 전용 식당/상품 조건 판정."""
from collections import defaultdict
from datetime import datetime
import math

from sqlalchemy import bindparam, select, text
from sqlalchemy.orm import selectinload

from .database import Restaurant, Menu, MenuCatalog
from .food_types import matches_food_type
from .recommendation_engine import current_open_status

SERVING_NOTICE = '인분 미확인 · 매장 표시 가격 기준'


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
            Menu.price_status=='known',Menu.price>0,Menu.price<=budget,
            Menu.availability_status!='sold_out')
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
            state,holiday_unknown=current_open_status(r.business_hours,now=now)
            valid=(distance<=radius_m and matches_food_type(cuisine,r.cuisine or r.category_name)
                and r.detail_status is not None and r.detail_status.hours_status=='success'
                and r.detail_status.menu_status=='success' and state=='open' and not holiday_unknown)
            rest_cache[r.id]=(valid,distance)
        valid,distance=rest_cache[r.id]
        if not valid:continue
        info=metadata.get((r.id,m.normalized_name),{})
        if info.get('catalog_status','linked')!='linked':continue
        serving=info.get('serving_status','unverified')
        warnings=[]
        if serving!='explicit_single':warnings.append(SERVING_NOTICE)
        if m.availability_status=='unknown':warnings.append('판매·품절 상태 미확인')
        if r.operating_status=='unknown':warnings.append('매장 운영 상태는 수집 시간표 기준')
        eligible.append({'restaurant':r,'menu':m,'catalog':c,'distance_m':round(distance),
            'serving_status':serving,'serving_unverified':serving!='explicit_single','warnings':warnings})
    return eligible


def candidate_payloads(products):
    groups=defaultdict(list)
    for item in products:groups[item['catalog'].id].append(item)
    result=[]
    for menu_id,items in groups.items():
        c=items[0]['catalog'];prices=[x['menu'].price for x in items]
        unverified=any(x['serving_unverified'] for x in items)
        result.append({'id':menu_id,'name':c.name,'cuisine':c.cuisine,'search_keyword':c.name,
            'description':'주변 DB 식당의 표시 가격 기준 후보입니다.'+(' '+SERVING_NOTICE if unverified else ''),
            'source':'database','price_verified':True,'verified_price':min(prices),
            'verified_price_max':max(prices),'price_hint':None,
            'nearby_restaurant_count':len({x['restaurant'].id for x in items}),
            'serving_unverified':unverified,'serving_status':'unverified' if unverified else 'explicit_single',
            'warnings':[SERVING_NOTICE] if unverified else []})
    return sorted(result,key=lambda x:(x['name'],x['id']))


def restaurant_payloads(products):
    groups=defaultdict(list)
    for item in products:groups[item['restaurant'].id].append(item)
    result=[]
    for rid,items in groups.items():
        x=min(items,key=lambda x:(x['menu'].price,x['menu'].name,x['menu'].id));r=x['restaurant'];m=x['menu']
        result.append({'id':rid,'kakao_id':r.kakao_id,'name':r.name,'category':r.category_name or r.cuisine,
            'address':r.address,'lat':r.latitude,'lng':r.longitude,'place_url':r.place_url,
            'distance_m':x['distance_m'],'menu_name':m.name,'menu_id':x['catalog'].id,
            'product_id':m.id,'price':m.price,'price_status':m.price_status,'menu_verified':True,
            'open_status':'open','recommendation_kind':'recommendation','source':'database',
            'serving_status':x['serving_status'],'serving_unverified':x['serving_unverified'],
            'availability_status':m.availability_status,'warnings':x['warnings'],
            'menu_verified_at':m.verified_at.isoformat() if m.verified_at else None})
    return sorted(result,key=lambda x:(x['distance_m'],x['price'],x['name'],x['id']))
