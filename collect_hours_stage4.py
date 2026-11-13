"""Hours-only collection. Never writes menu/catalog/price columns or public schema."""
import argparse
import asyncio
from collections import Counter
from dataclasses import asdict
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import time

from sqlalchemy import select, text, delete
from app.config import load_settings
from app.database import Restaurant, BusinessHours, PlaceDetailStatus
from app.database.session import Database
from app.collectors.kakao_place import KakaoPlaceCollector, PlaceCollectionError, validate_place_url
from app.place_details import parse_place_page

OUT=Path(__file__).resolve().parent/'tmp'/'hours_stage4'
SCHEMA='Lunchrun'


def fingerprint(db):
    with db.engine.connect() as c:
        digest=hashlib.sha256()
        for row in c.execute(text('SELECT row_to_json(m)::text FROM "Lunchrun".menu m ORDER BY id')):
            digest.update(row[0].encode())
        return {'menus':c.scalar(text('SELECT count(*) FROM "Lunchrun".menu')),
                'linked':c.scalar(text('SELECT count(*) FROM "Lunchrun".menu WHERE menu_catalog_id IS NOT NULL')),
                'catalogs':c.scalar(text('SELECT count(*) FROM "Lunchrun".menu_catalog')),
                'menu_sha256':digest.hexdigest()}


def targets(db,limit):
    rows=[];excluded=Counter()
    with db.session_factory() as s:
        for r in s.scalars(select(Restaurant).order_by(Restaurant.name)):
            if not r.kakao_id or not r.place_url:
                excluded['no_confirmed_url']+=1;continue
            try:url=validate_place_url(r.kakao_id,r.place_url)
            except PlaceCollectionError:excluded['invalid_url']+=1;continue
            rows.append({'id':r.id,'name':r.name,'kakao_id':r.kakao_id,'url':url})
    return rows[:limit] if limit else rows,dict(excluded)


def store(db,row,result,raw):
    now=datetime.now(timezone.utc)
    state=result['status'];hours=result.pop('_hours',())
    with db.session_factory.begin() as s:
        status=s.get(PlaceDetailStatus,row['id'])
        if status is None:
            status=PlaceDetailStatus(restaurant_id=row['id']);s.add(status)
        # Only a complete, parsed schedule replaces hours. Missing/failure preserves rows.
        if state=='success':
            s.execute(delete(BusinessHours).where(BusinessHours.restaurant_id==row['id']))
            s.add_all([BusinessHours(restaurant_id=row['id'],source_url=row['url'],verified_at=now,**asdict(h)) for h in hours])
            status.hours_status='success';status.hours_last_success_at=now
        elif status.hours_last_success_at is None:
            status.hours_status=state
        # menu_status, menu_last_success_at and menu rows are deliberately untouched.
        status.last_attempt_at=now
        payload=dict(result,source_url=row['url'],checked_at=now.isoformat(),raw_business_days=raw)
        audit_id=hashlib.sha256(('hours-stage4:'+row['id']).encode()).hexdigest()
        s.execute(text('INSERT INTO "Lunchrun".csv_import_record (id,batch_id,record_kind,record_key,payload) '
            'VALUES (:id,\'hours-stage4\',\'hours_collection\',:key,CAST(:payload AS jsonb)) '
            'ON CONFLICT (id) DO UPDATE SET payload=EXCLUDED.payload'),
            {'id':audit_id,'key':row['id'],'payload':json.dumps(payload,ensure_ascii=False)})
    return payload


async def run(args):
    OUT.mkdir(parents=True,exist_ok=True)
    db=Database(load_settings().database_url)
    rows,excluded=targets(db,args.limit)
    before=fingerprint(db)
    baseline=OUT/'baseline.json'
    if baseline.exists():assert json.loads(baseline.read_text(encoding='utf-8'))==before,'Protected menu data changed; stop.'
    else:baseline.write_text(json.dumps(before,indent=2),encoding='utf-8')
    with db.engine.connect() as c:
        previous={r[0]:r[1] for r in c.execute(text('SELECT record_key,payload FROM "Lunchrun".csv_import_record WHERE record_kind=\'hours_collection\''))}
    pending=[r for r in rows if r['id'] not in previous] if not args.retry else rows
    print(json.dumps({'targets':len(rows),'excluded':excluded,'already_attempted':len(rows)-len(pending),'pending':len(pending)},ensure_ascii=False),flush=True)
    gate=asyncio.Lock();next_start=0.0;counter=Counter();done=0
    async with KakaoPlaceCollector(hours_only=True,timeout_ms=18000) as collector:
        semaphore=asyncio.Semaphore(args.concurrency)
        async def one(row):
            nonlocal next_start,done
            async with semaphore:
                async with gate:
                    wait=max(0,next_start-time.monotonic())
                    if wait:await asyncio.sleep(wait)
                    next_start=time.monotonic()+1.0
                raw=[]
                try:
                    page=await collector.collect(row['kakao_id'],row['url'])
                    raw=[asdict(d) for d in page.business_days]
                    parsed=parse_place_page(page);state=parsed.hours_status
                    days={h.day_of_week for h in parsed.business_hours}
                    ambiguous=any(any(word in detail for word in ('임시휴무','공휴일','명절','격주','매월','첫째','둘째','셋째','넷째','다섯째')) for day in page.business_days for detail in day.details)
                    if state=='success' and (len(days)!=7 or ambiguous):state='parse_failed'
                    result={'id':row['id'],'name':row['name'],'status':state,'hours_rows':len(parsed.business_hours) if state=='success' else 0,
                        'reason':'incomplete_or_exception_schedule' if state=='parse_failed' else None,'_hours':parsed.business_hours if state=='success' else ()}
                except PlaceCollectionError as e:
                    result={'id':row['id'],'name':row['name'],'status':e.status,'reason':e.code,'hours_rows':0}
                payload=await asyncio.to_thread(store,db,row,result,raw)
                counter[payload['status']]+=1;done+=1
                with (OUT/'progress.jsonl').open('a',encoding='utf-8') as f:f.write(json.dumps(payload,ensure_ascii=False)+'\n')
                print(json.dumps({'done':done,'total':len(pending),'name':row['name'],'status':payload['status'],'rows':payload['hours_rows']},ensure_ascii=False),flush=True)
        await asyncio.gather(*(one(row) for row in pending))
    after=fingerprint(db);assert before==after,'Protected menu data changed!'
    with db.engine.connect() as c:
        total_rows=c.scalar(text('SELECT count(*) FROM "Lunchrun".business_hours'))
        stored=dict(c.execute(text('SELECT hours_status,count(*) FROM "Lunchrun".place_detail_status GROUP BY 1')).all())
    report={'selected_targets':len(rows),'excluded':excluded,'new_attempts':done,'this_run':dict(counter),
        'stored_hours_rows':total_rows,'stored_statuses':stored,'menu_fingerprint_before':before,'menu_fingerprint_after':after,
        'protected_menu_data_unchanged':before==after}
    (OUT/('sample_result.json' if args.limit else 'full_result.json')).write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(report,ensure_ascii=False),flush=True);db.dispose()


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--limit',type=int,default=0)
    parser.add_argument('--concurrency',type=int,default=2);parser.add_argument('--retry',action='store_true')
    asyncio.run(run(parser.parse_args()))
