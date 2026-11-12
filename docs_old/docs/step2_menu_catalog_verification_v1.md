# 2단계 메뉴 카탈로그 검증 안내 v1

- 작성일: 2026-11-10
- 대상: 메뉴 카탈로그 테이블, 초기 데이터, 실제 DB 우선 후보 조회

## 자동 검증

프로젝트 루트 `C:\TeamProject_1`의 PowerShell에서 실행한다.

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_menu_catalog.py tests\test_database.py -v
```

정상 결과는 테스트 5개 통과다. 전체 기존 기능 회귀 검증은 다음 명령으로 실행한다.

```powershell
.\.venv\Scripts\python.exe -m pytest -q
```

작성 시점 확인 결과는 `57 passed, 1 skipped, 37 subtests passed`이다. Starlette TestClient 사용 중단 예정 경고 1개는 이번 구현 실패가 아니다.

## DB 테이블 확인

```powershell
.\.venv\Scripts\python.exe -c 'import sqlite3; c=sqlite3.connect(r"data\lunchrun.db"); print(c.execute("SELECT name FROM sqlite_master WHERE type=? AND name IN (?,?) ORDER BY name", ("table","menu_catalog","menu_alias")).fetchall())'
```

`menu_alias`, `menu_catalog` 두 테이블이 출력되면 정상이다.

## 기존 데이터 보존과 초기 데이터 확인

```powershell
.\.venv\Scripts\python.exe -c 'import sqlite3; c=sqlite3.connect(r"data\lunchrun.db"); print({t:c.execute("SELECT COUNT(*) FROM "+t).fetchone()[0] for t in ["restaurant","menu","business_hours","place_detail_status","menu_catalog","menu_alias"]})'
```

2단계 구현 직후 확인값:

- restaurant: 53
- menu: 106
- business_hours: 43
- place_detail_status: 53
- menu_catalog: 10
- menu_alias: 15

기존 네 테이블의 행 수가 유지되고 새 카탈로그 데이터만 추가됐는지 확인한다.

## 카탈로그 내용 확인

```powershell
.\.venv\Scripts\python.exe -c 'import sqlite3; c=sqlite3.connect(r"data\lunchrun.db"); print(*c.execute("SELECT id, name, cuisine, price_hint, active FROM menu_catalog ORDER BY id"), sep="\n")'
```

대표 메뉴 10개와 음식 종류, 기준 가격, 활성 여부가 출력돼야 한다. `price_hint`는 실제 식당 가격이 아니라 후보 필터용 기준값이다.

## 코드에서 직접 후보 확인

아래 명령은 현재 DB에 저장된 표본 좌표와 500m 반경에서 실제 메뉴 근거가 연결되는지 확인한다. 검증을 위해 예산 상한을 100,000원으로 둔다.

```powershell
.\.venv\Scripts\python.exe -c 'from app.config import load_settings; from app.database import Database; from app.menu_catalog import menu_candidates; d=Database(load_settings().database_url); s=d.session_factory(); print(*[x.to_dict() for x in menu_candidates(s, latitude=37.480066, longitude=126.878169, radius_m=500, budget=100000, cuisine="전체")], sep="\n"); s.close(); d.dispose()'
```

각 결과의 `source`를 확인한다.

- `database`: 반경 안의 실제 메뉴와 예산 이내 확인 가격을 근거로 선정
- `catalog`: 실제 근거가 부족해 카탈로그 기준으로 선정

## 직접 검토 체크리스트

- 기존 식당별 메뉴 106건이 보존됐는가?
- 메뉴 카탈로그 10건과 별칭 15건이 생성됐는가?
- 돈까스 표기가 돈가스 대표 메뉴에 연결되는 테스트가 통과하는가?
- 반경 밖 식당 메뉴가 실제 후보 근거에서 제외되는가?
- 실제 근거가 있으면 카탈로그 후보가 섞이지 않는가?
- 직전 메뉴 ID를 제외하면 같은 메뉴가 다시 선정되지 않는가?
- 카탈로그 기준 가격이 실제 매장 가격으로 표시되지 않는가?
