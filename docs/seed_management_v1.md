# seed.py 메뉴 수동 관리 v1

`app/database/seed.py`의 DEFAULT_MENU_CATALOG가 대표 메뉴 전체의 기준이다.
CSV와 식당 수집 메뉴 테이블은 동기화하지 않는다.

## 사용 방법

목록을 편집하고 프로젝트 루트 PowerShell에서 실행한다.

```powershell
.\.venv\Scripts\python.exe -m app.database.seed
```

- 새 ID: 추가
- 기존 ID: 이름·설명·검색어·기준가격·별칭 갱신
- 목록에서 삭제: DB 행을 보존하고 active=False
- 같은 ID 재등록: 다시 활성화
- 결과의 updated는 목록에 존재해 갱신 처리한 기존 행 수이며 실제 차이 건수와 다를 수 있다.

ID는 고정해서 사용한다. 모든 메뉴의 별칭은 목록과 같게 교체되며 비활성 메뉴의 별칭은 제거한다.
빈 목록과 중복 ID·이름·별칭은 거부한다. 실패하면 전체 트랜잭션이 롤백된다.
식당별 메뉴·가격·영업시간은 삭제하지 않는다.

서버 시작 시 기존 초기화 함수는 누락 항목만 추가한다. 수정·삭제까지 반영하려면 위 명령을 실행한다.
메뉴를 편집할 때는 서버를 중지하고 동기화한 뒤 재시작하는 것을 권장한다.

## Supabase

같은 명령이 DATABASE_URL을 읽고 SQLAlchemy로 연결한다. Supabase PostgreSQL 주소로 전환해도 동기화 코드를 바꿀 필요가 없다.
테이블은 먼저 Alembic으로 준비한다. 실제 PostgreSQL 연결 검증은 별도로 필요하다.

## 현재 분류 제한

현재 DB 카탈로그 제약은 한식·중식·일식·양식·샐러드만 저장할 수 있다.
화면의 15개 식당 업태와 카탈로그 저장 분류는 다르다. 이번 구현은 이 제약을 바꾸지 않는다.
새 저장 분류를 추가하려면 ORM·Alembic 제약을 확장해야 한다.

## 확인

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_menu_catalog.py -q
```

목록에서 메뉴를 제거하고 동기화한 뒤 active=False인지 확인한다. 다시 추가하고 실행하면 True여야 한다.
DB 카탈로그 전체를 이 파일이 관리하므로 DB 편집 도구로 따로 등록한 행도 목록에 없으면 비활성화된다.
