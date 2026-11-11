import json
from pathlib import Path
root=Path(__file__).resolve().parent.parent
p=root/'PROJECT_CONTEXT.json'
d=json.loads(p.read_text(encoding='utf-8'))
d.setdefault('user_confirmed_updates',{})['frontend_ui_03']={
    'path':'frontend_UI_03',
    'budget':{'default':5000,'min':1000,'max':100000000,'step':1000,'input':'직접 입력·콤마, 슬라이더 삭제'},
    'time':'AM/PM 선택·시/분 직접 입력, ±10분, 슬라이더 삭제',
    'dock_hidden':['conditions','budget','time','distance','people'],
    'icons':'상단 아이콘만 확대','footer':'예시 데이터 안내 문구 삭제',
    'apply_label':'적용','slider':'거리/인원 핸들 확대',
    'time_calculation_note':'구현 해석: 오늘 Asia/Seoul 기준 남은 분, 지난 시각0. 날짜 선택 없음'
}
p.write_text(json.dumps(d,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
q=root/'frontend_UI_03/api_contract.md'
s=q.read_text(encoding='utf-8').replace('"budget": 12000','"budget": 5000')
s+='\n\nUI 03 추가: lunch_end_time은 24시간 HH:mm 문자열입니다. remaining_minutes는 오늘 Asia/Seoul 기준으로 계산하며 지난 종료 시각은 0입니다. 예산 1,000~100,000,000원, 기본 5,000원. 서버에서 재검증하세요.\n'
q.write_text(s,encoding='utf-8')
