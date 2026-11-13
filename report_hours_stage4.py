"""Read-only DB verification and local collection report."""
from collections import Counter
import csv
import json
from pathlib import Path
from sqlalchemy import select, text
from app.config import load_settings
from app.database import Restaurant
from app.database.session import Database
from collect_hours_stage4 import fingerprint, targets

OUT=Path(__file__).resolve().parent/'tmp'/'hours_stage4'


def main():
    db=Database(load_settings().database_url)
    eligible,excluded=targets(db,0)
    with db.engine.connect() as c:
        results=dict(c.execute(text('SELECT record_key,payload FROM "Lunchrun".csv_import_record WHERE record_kind=\'hours_collection\'')).all())
        hours_rows=c.scalar(text('SELECT count(*) FROM "Lunchrun".business_hours'))
        holiday_rows=c.scalar(text('SELECT count(*) FROM "Lunchrun".business_hours WHERE holiday IS TRUE'))
        overnight_rows=c.scalar(text('SELECT count(*) FROM "Lunchrun".business_hours WHERE ends_next_day'))
        breaks=c.scalar(text('SELECT count(DISTINCT restaurant_id) FROM "Lunchrun".business_hours WHERE sequence>0'))
        bad_weeks=c.scalar(text('SELECT count(*) FROM (SELECT restaurant_id FROM "Lunchrun".business_hours GROUP BY restaurant_id HAVING count(DISTINCT day_of_week)<>7) s'))
        public_tables=list(c.scalars(text("SELECT tablename FROM pg_tables WHERE schemaname='public' ORDER BY tablename")))
    completed=[results[r['id']] for r in eligible if r['id'] in results]
    states=dict(Counter(r['status'] for r in completed))
    baseline=json.loads((OUT/'baseline.json').read_text(encoding='utf-8'))
    current=fingerprint(db)
    assert current==baseline,'Menu data changed; report must not claim preservation.'
    assert bad_weeks==0,'Incomplete schedules stored.'
    report=dict(eligible=len(eligible),completed=len(completed),remaining=len(eligible)-len(completed),excluded=excluded,
        statuses=states,business_hours_rows=hours_rows,holiday_rows=holiday_rows,overnight_rows=overnight_rows,
        restaurants_with_split_intervals=breaks,menu_data_unchanged=True,fingerprint=current,public_tables=public_tables)
    output=[]
    with db.session_factory() as s:
        for r in s.scalars(select(Restaurant).order_by(Restaurant.name)):
            result=results.get(r.id)
            output.append({'restaurant_id':r.id,'name':r.name,'kakao_id':r.kakao_id or '',
                'source_url':r.place_url or '', 'status':result['status'] if result else 'excluded_no_url' if not r.place_url else 'pending',
                'reason':result.get('reason') or '' if result else '',
                'hours_rows':result.get('hours_rows',0) if result else 0,
                'checked_at':result.get('checked_at','') if result else ''})
    with (OUT/'restaurant_results.csv').open('w',encoding='utf-8-sig',newline='') as f:
        w=csv.DictWriter(f,fieldnames=list(output[0]));w.writeheader();w.writerows(output)
    (OUT/'verification.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    lines=['# 영업시간·휴무 수집 검증 결과','',f'- 대상: {len(eligible)}곳, 완료: {len(completed)}곳, 남음: {report["remaining"]}곳.',
        f'- URL 미확정 등 제외: {json.dumps(excluded,ensure_ascii=False)}.',
        f'- 결과: {json.dumps(states,ensure_ascii=False)}.',
        f'- 시간표 {hours_rows}행, 휴무 {holiday_rows}행, 익일 종료 {overnight_rows}행.',
        f'- 분리된 영업 구간이 있는 식당 {breaks}곳. 브레이크 타임 외 복수 영업 구간도 포함.',
        '- 전체 메뉴 데이터의 SHA-256과 대표 메뉴 연결·카탈로그 건수: 기준값과 일치.',
        f'- 기존 public 테이블: {", ".join(public_tables)}.',
        '', '## 저장 및 해석 규칙', '',
        'Lunchrun.business_hours와 영업시간 수집 상태, csv_import_record의 hours_collection 원문·결과만 갱신했다. 메뉴·가격·대표 메뉴 연결에는 쓰지 않았다.',
        '7개 요일이 모두 해석된 경우에만 시간표를 저장했다. 브레이크 타임은 영업 구간을 나누고, 자정을 넘는 종료는 별도 표시한다.',
        '정보 없음·접근 실패·불완전한 해석은 기존 정상 시간표를 지우지 않는다. 원문과 이유를 검토 기록에 남긴다.',
        '페이지의 향후 7일 표기를 주간 시간표로 정규화하므로, 임시휴무·격주·월별 예외가 감지되면 보류한다. 페이지에 표시되지 않은 예외나 현장 영업 상태는 보장하지 않는다.',
        '이 작업은 DB 시간표 보완이다. 사용자 요청을 DB 조회만으로 처리하는 추천 경로 전환은 별도 후속 작업이다.',
        '', '## 결과 파일', '',
        '- tmp/hours_stage4/restaurant_results.csv: 전체 식당별 성공·미확인·제외 결과.',
        '- tmp/hours_stage4/verification.json: 실제 DB 검증 집계.',
        '- tmp/hours_stage4/progress.jsonl: 식당별 수집 원문·진행 기록.',
        '- Lunchrun.csv_import_record, record_kind=hours_collection: 원문·출처·확인 시각·실패 사유.',
        '', '브라우저 직접 읽기 표본 3곳과 저장 표본 8곳을 확인한 뒤 전체 수집을 실행했다. 표본은 성공 6곳·정보 없음 2곳, 시간표 48행이었다. 파싱·저장 회귀 테스트는 7개 통과했다.',
        '커밋·push는 실행하지 않았다.']
    (Path(__file__).resolve().parent/'docs'/'db_first_stage4_hours_results.md').write_text('\n'.join(lines)+'\n',encoding='utf-8')
    print(json.dumps(report,ensure_ascii=False),flush=True);db.dispose()


if __name__=='__main__':main()
