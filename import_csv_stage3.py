"""Approved CSV import. Every write explicitly targets the Lunchrun schema."""
from pathlib import Path
from datetime import datetime
from collections import Counter
import csv
import hashlib
import json
from sqlalchemy import MetaData, Table, create_engine, select, text
from app.config import load_settings
from app.database.session import normalize_database_url

ROOT=Path(__file__).resolve().parent
SOURCE=ROOT/'tmp'/'csv_stage3_catalog_review'
SCHEMA='Lunchrun'


def read(name):
    with (SOURCE/name).open(encoding='utf-8-sig',newline='') as f:return list(csv.DictReader(f))


def stamp(value):
    return datetime.fromisoformat(value.replace('Z','+00:00')) if value else None


def main():
    files=('restaurants.csv','menus.csv','menu_catalog.csv','menu_alias.csv','restaurant_matches.csv','reviews.csv','excluded_rows.csv')
    data={n:read(n) for n in files}
    batch=hashlib.sha256(b''.join((SOURCE/n).read_bytes() for n in files)).hexdigest()
    engine=create_engine(normalize_database_url(load_settings().database_url))
    names=('restaurant','menu','menu_catalog','menu_alias','business_hours','place_detail_status','restaurant_match','csv_import_record')
    metadata=MetaData(schema=SCHEMA)
    tables={n:Table(n,metadata,autoload_with=engine) for n in names}
    expected={'restaurant':2174,'menu':35231,'menu_catalog':152,'restaurant_match':584}
    with engine.begin() as c:
        c.execute(text("SELECT pg_advisory_xact_lock(52312026)"))
        for n in names:
            if c.scalar(select(__import__('sqlalchemy').func.count()).select_from(tables[n])):
                raise RuntimeError('Target is not empty; refusing duplicate or destructive import: '+n)
        def insert(name,rows):
            for start in range(0,len(rows),500):c.execute(tables[name].insert(),rows[start:start+500])
        cats=[]
        for x in data['menu_catalog.csv']:
            cats.append({k:x[k] for k in ('id','name','normalized_name','cuisine','search_keyword','description')}|{'active':True,'price_hint':None})
        insert('menu_catalog',cats)
        insert('menu_alias',data['menu_alias.csv'])
        restaurants=[]
        for x in data['restaurants.csv']:
            restaurants.append({k:x[k] for k in ('id','name','address','cuisine','category_name','operating_status')}|
                {k:x[k] or None for k in ('kakao_id','naver_id','place_url')}|
                {'latitude':float(x['latitude']),'longitude':float(x['longitude'])})
        insert('restaurant',restaurants)
        menus=[]
        for x in data['menus.csv']:
            menus.append({k:x[k] for k in ('restaurant_id','name','normalized_name','price_status','availability_status','source_provider','source_url')}|
                {'menu_catalog_id':x['menu_catalog_id'] or None,'price':int(x['price']) if x['price'] else None,'verified_at':stamp(x['verified_at'])})
        insert('menu',menus)
        # Menu information was imported, but no business hours were collected.
        with_menu={x['restaurant_id'] for x in menus}
        insert('place_detail_status',[{'restaurant_id':r['id'],'menu_status':'success' if r['id'] in with_menu else 'missing','hours_status':'pending'} for r in restaurants])
        matches=[]
        for x in data['restaurant_matches.csv']:
            matches.append({k:x[k] for k in ('source_name','source_address','match_status')}|
                {k:x[k] or None for k in ('restaurant_id','candidate_kakao_id','reason')})
        insert('restaurant_match',matches)
        audit=[]
        # Preserve every prepared record's source rows, classification and review status.
        for filename,rows in data.items():
            for i,row in enumerate(rows):
                key=filename+':'+str(i+2)
                audit.append(dict(id=hashlib.sha256((batch+'|'+key).encode()).hexdigest(),batch_id=batch,
                    record_kind=filename.removesuffix('.csv'),record_key=key,payload=row))
        # Preserve excluded and price-conflicting raw rows as well, not as invented products.
        with (Path.home()/'Downloads'/'menu_example.before-kakao-ids.csv').open(encoding='utf-8-sig',newline='') as f:
            raw=list(csv.DictReader(f))
        held={int(x['source_row']) for x in data['excluded_rows.csv']}
        for x in data['reviews.csv']:
            held.update(int(i) for i in x['source_rows'].split(',') if i)
        for index in sorted(held):
            key='raw:'+str(index)
            audit.append(dict(id=hashlib.sha256((batch+'|'+key).encode()).hexdigest(),batch_id=batch,
                record_kind='raw_held_row',record_key=key,payload=raw[index-2]))
        insert('csv_import_record',audit)
        counts={n:c.scalar(text(f'SELECT count(*) FROM "Lunchrun"."{n}"')) for n in names}
        for n,count in expected.items():assert counts[n]==count,(n,counts[n])
        linked=c.scalar(text('SELECT count(*) FROM "Lunchrun".menu WHERE menu_catalog_id IS NOT NULL'))
        assert linked==2969
        assert c.scalar(text('SELECT count(*) FROM "Lunchrun".menu WHERE menu_catalog_id IS NOT NULL AND price_status=\'known\''))==2376
        actual=dict(c.execute(text('SELECT payload->>\'catalog_status\',count(*) FROM "Lunchrun".csv_import_record WHERE record_kind=\'menus\' GROUP BY 1')).all())
        assert actual==dict(Counter(x['catalog_status'] for x in data['menus.csv']))
        assert c.scalar(text('SELECT count(*) FROM "Lunchrun".menu m LEFT JOIN "Lunchrun".restaurant r ON r.id=m.restaurant_id WHERE r.id IS NULL'))==0
        result=dict(schema=SCHEMA,batch_id=batch,counts=counts,linked_menus=linked,classification=actual,held_raw_rows=len(held),committed=False)
    result['committed']=True
    (SOURCE/'import_result.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(result,ensure_ascii=False,indent=2))
    engine.dispose()


if __name__=='__main__':main()
