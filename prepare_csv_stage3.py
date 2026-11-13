"""CSV 적재 예정 자료만 생성한다. DB 연결·쓰기 기능은 없다."""
from pathlib import Path
from collections import Counter, defaultdict
from datetime import datetime
from uuid import uuid5, NAMESPACE_URL
from urllib.parse import urlsplit
import csv
import json
import math
import re
import unicodedata

ROOT = Path(__file__).resolve().parent
INPUT = Path.home() / 'Downloads'
OUT = ROOT / 'tmp' / 'csv_stage3_preview'


def norm(value):
    return re.sub(r'\s+', '', unicodedata.normalize('NFC', value or '').casefold())


def read(name):
    with (INPUT / name).open(encoding='utf-8-sig', newline='') as stream:
        return list(csv.DictReader(stream))


def save(name, rows, columns):
    with (OUT / name).open('w', encoding='utf-8-sig', newline='') as stream:
        writer = csv.DictWriter(stream, fieldnames=columns, extrasaction='ignore')
        writer.writeheader(); writer.writerows(rows)


def distance(a, b):
    lat1, lon1, lat2, lon2 = map(math.radians, [a['latitude'], a['longitude'], b['latitude'], b['longitude']])
    h = math.sin((lat2-lat1)/2)**2 + math.cos(lat1)*math.cos(lat2)*math.sin((lon2-lon1)/2)**2
    return 6371000 * 2 * math.asin(min(1, math.sqrt(h)))


def main():
    # These imports expose constants only and never initialize an application/DB.
    from app.database.seed import DEFAULT_MENU_CATALOG
    from app.food_types import catalog_food_type, FOOD_TYPE_MAPPING
    OUT.mkdir(parents=True, exist_ok=True)
    raw = read('menu_example.before-kakao-ids.csv')
    confirmed = read('confirmed_matches.csv')
    unresolved = read('unresolved_restaurants.csv')
    report = read('resolution_report.csv')
    key = lambda row: (norm(row['source_name']), norm(row['source_address']))
    certified = defaultdict(set)
    for row in confirmed:
        if row['status'] == 'matched' and row['kakao_id'].strip():
            certified[key(row)].add(row['kakao_id'].strip())
    report_counts = Counter(row['status'] for row in report)
    if Counter(tuple(sorted(r.items())) for r in confirmed + unresolved) != Counter(tuple(sorted(r.items())) for r in report):
        raise ValueError('매칭 보고서와 확정/미해결 목록이 일치하지 않습니다.')
    source = defaultdict(list)
    for index, row in enumerate(raw, 2):
        source[(norm(row['지점명']), norm(row['주소']))].append((index, row))
    reviews, exclusions, matched, groups = [], [], [], defaultdict(list)
    stats = Counter()
    for source_key, entries in source.items():
        row = entries[0][1]
        existing = {r['카카오ID'].strip() for _, r in entries if r['카카오ID'].strip()}
        agreed = certified.get(source_key, set())
        navers = {r['네이버장소ID'].strip() for _, r in entries if r['네이버장소ID'].strip()}
        reason = None
        if len(existing | agreed) > 1: reason = 'conflicting_kakao_ids'
        elif len(navers) > 1: reason = 'conflicting_naver_ids'
        if reason:
            reviews.append(dict(kind='restaurant', key=str(source_key), reason=reason, source_rows=','.join(str(i) for i,_ in entries)))
            stats['restaurant_source_groups_held'] += 1
            continue
        kakao = next(iter(existing | agreed), '')
        naver = next(iter(navers), '')
        identity = 'kakao:'+kakao if kakao else 'naver:'+naver if naver else 'source:'+'|'.join(source_key)
        groups[identity].extend(entries)
        if agreed and not existing: stats['newly_matched_source_groups'] += 1
        if agreed: stats['confirmed_mapping_source_groups'] += 1
    restaurants, items = [], defaultdict(list)
    for identity, entries in sorted(groups.items()):
        samples = []
        invalid = False
        for index,row in entries:
            try:
                p = dict(latitude=float(row['위도']), longitude=float(row['경도']))
                if not all(math.isfinite(v) for v in p.values()) or not -90 <= p['latitude'] <= 90 or not -180 <= p['longitude'] <= 180:
                    raise ValueError()
                samples.append(p)
            except ValueError:
                reviews.append(dict(kind='restaurant', key=identity, reason='invalid_coordinates', source_rows=str(index)))
                invalid = True
        if invalid: continue
        if any(distance(samples[0], p) > 200 for p in samples):
            reviews.append(dict(kind='restaurant', key=identity, reason='same_id_coordinate_conflict_over_200m', source_rows=','.join(str(i) for i,_ in entries)))
            continue
        representative = entries[0][1]
        kakao_values = {r['카카오ID'].strip() for _,r in entries if r['카카오ID'].strip()}
        if identity.startswith('kakao:'): kakao_values.add(identity[6:])
        naver_values = {r['네이버장소ID'].strip() for _,r in entries if r['네이버장소ID'].strip()}
        if len(kakao_values)>1 or len(naver_values)>1:
            reviews.append(dict(kind='restaurant',key=identity,reason='merged_external_identity_conflict',source_rows=','.join(str(i) for i,_ in entries)))
            continue
        kakao = next(iter(kakao_values),''); naver = next(iter(naver_values),'')
        uid = str(uuid5(NAMESPACE_URL, 'lunchrun:'+identity))
        raw_category = representative['카카오분류(추가가게)'].strip() or representative['업태구분명'].strip()
        cuisine = catalog_food_type(raw_category)
        if cuisine == '기타' and raw_category not in FOOD_TYPE_MAPPING['기타']:
            reviews.append(dict(kind='category',key=uid,reason='unmapped_category:'+raw_category,source_rows=str(entries[0][0])))
        restaurants.append(dict(id=uid,kakao_id=kakao,naver_id=naver,name=representative['지점명'].strip(),
            address=representative['주소'].strip(),**samples[0],cuisine=cuisine,category_name=raw_category,
            operating_status='unknown',place_url='https://place.map.kakao.com/'+kakao if kakao else '',
            source_rows=','.join(str(i) for i,_ in entries)))
        for index,row in entries:
            name = row['메뉴명'].strip()
            if not name:
                exclusions.append(dict(source_row=index,reason='no_menu_name',restaurant_id=uid));continue
            price_raw = row['가격(원)'].strip()
            original_price = row['가격원문'].strip()
            if price_raw:
                try:
                    price = int(price_raw)
                    if price<=0: raise ValueError()
                    status='known'
                except ValueError:
                    reviews.append(dict(kind='menu',key=uid+'|'+name,reason='invalid_price',source_rows=str(index)));continue
            else:
                price='';status='variable' if re.search('시가|변동',original_price) else 'missing'
            stamp = row['확인일시'].strip()
            try:
                date = datetime.fromisoformat(stamp.replace('Z','+00:00')) if stamp else None
                if date and date.tzinfo is None: raise ValueError()
            except ValueError:
                reviews.append(dict(kind='menu',key=uid+'|'+name,reason='invalid_verified_at',source_rows=str(index)));stamp='';date=None
            url=row['출처링크'].strip();host=urlsplit(url).hostname or ''
            provider='naver' if host.endswith('.naver.com') else 'kakao' if host.endswith('.kakao.com') else 'unknown'
            items[(uid,norm(name))].append(dict(restaurant_id=uid,name=name,normalized_name=norm(name),price=price,
                price_status=status,availability_status='sold_out' if '품절' in row['품절표기'] else 'unknown',
                source_provider=provider,source_url=url,verified_at=stamp,source_row=index,_date=date))
    aliases={norm(c['name']):c['id'] for c in DEFAULT_MENU_CATALOG}
    aliases.update({norm('자장면'):'noodle',norm('돈까스'):'cutlet'})
    menus=[];unmapped=Counter()
    for (rid,normalized), candidates in sorted(items.items()):
        prices={(m['price'],m['price_status']) for m in candidates}
        if len(prices)>1:
            # Price conflicts are held, not guessed from a timestamp alone.
            reviews.append(dict(kind='menu',key=rid+'|'+normalized,reason='duplicate_product_price_conflict',source_rows=','.join(str(m['source_row']) for m in candidates)))
            stats['menu_price_conflict_groups']+=1;continue
        chosen=max(candidates,key=lambda m:m['_date'].timestamp() if m['_date'] else float('-inf'))
        stats['duplicate_menu_rows_removed']+=len(candidates)-1
        chosen['source_rows']=','.join(str(m['source_row']) for m in candidates)
        blocked=bool(re.search(r'세트|커플|패밀리|\d+\s*인|추가|토핑|소주|맥주|주류',chosen['name']))
        chosen['menu_catalog_id']=aliases.get(normalized,'') if not blocked else ''
        chosen['catalog_status']='exact_or_verified_alias' if chosen['menu_catalog_id'] else 'review_required'
        if not chosen['menu_catalog_id']:unmapped[chosen['name']]+=1
        menus.append(chosen)
    restaurant_ids={r['id'] for r in restaurants}
    source_row_to_restaurant={int(i):r['id'] for r in restaurants for i in r['source_rows'].split(',')}
    for row in report:
        source_key=key(row)
        source_matches={source_row_to_restaurant[i] for i,_ in source.get(source_key,[]) if i in source_row_to_restaurant}
        rid=next(iter(source_matches)) if len(source_matches)==1 and row['status']=='matched' else ''
        matched.append(dict(restaurant_id=rid,source_name=row['source_name'],source_address=row['source_address'],
            candidate_kakao_id=row['kakao_id'],match_status=row['status'],reason=row['reason']))
    catalogs=[dict(id=c['id'],name=c['name'],normalized_name=norm(c['name']),active=True,cuisine=c['cuisine'],
        search_keyword=c['name'],description='',price_hint='') for c in DEFAULT_MENU_CATALOG]
    alias_rows=[dict(menu_catalog_id=c['id'],name=c['name'],normalized_name=norm(c['name'])) for c in DEFAULT_MENU_CATALOG]
    alias_rows += [dict(menu_catalog_id='noodle',name='자장면',normalized_name=norm('자장면')),
                   dict(menu_catalog_id='cutlet',name='돈까스',normalized_name=norm('돈까스'))]
    assert len(restaurant_ids)==len(restaurants)
    assert all(m['restaurant_id'] in restaurant_ids for m in menus)
    assert len({(m['restaurant_id'],m['normalized_name']) for m in menus})==len(menus)
    save('restaurants.csv',restaurants,['id','kakao_id','naver_id','name','address','latitude','longitude','cuisine','category_name','operating_status','place_url','source_rows'])
    save('menus.csv',menus,['restaurant_id','menu_catalog_id','name','normalized_name','price','price_status','availability_status','source_provider','source_url','verified_at','catalog_status','source_rows'])
    save('menu_catalog.csv',catalogs,['id','name','normalized_name','active','cuisine','search_keyword','description','price_hint'])
    save('menu_alias.csv',alias_rows,['menu_catalog_id','name','normalized_name'])
    save('restaurant_matches.csv',matched,['restaurant_id','source_name','source_address','candidate_kakao_id','match_status','reason'])
    save('reviews.csv',reviews,['kind','key','reason','source_rows'])
    save('excluded_rows.csv',exclusions,['source_row','reason','restaurant_id'])
    save('unmapped_menu_names.csv',[dict(name=n,restaurant_product_count=c) for n,c in unmapped.most_common()],['name','restaurant_product_count'])
    summary=dict(source_rows=len(raw),source_restaurant_keys=len(source),planned_restaurants=len(restaurants),
        restaurants_with_kakao=sum(bool(r['kakao_id']) for r in restaurants),restaurants_without_kakao=sum(not r['kakao_id'] for r in restaurants),
        planned_menus=len(menus),known_price_menus=sum(m['price_status']=='known' for m in menus),
        linked_menus=sum(bool(m['menu_catalog_id']) for m in menus),unlinked_menus=sum(not m['menu_catalog_id'] for m in menus),
        catalog_count=len(catalogs),review_reasons=dict(Counter(r['reason'] for r in reviews)),
        exclusions=len(exclusions),matching_status=dict(report_counts),details=dict(stats),supabase_written=False)
    (OUT/'summary.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(summary,ensure_ascii=False,indent=2))


if __name__=='__main__':main()
