# DB 마이그레이션 안내

기준일: 2026-11-16. 현재 사용하는 Supabase PostgreSQL과 `Lunchrun` 스키마를 대상으로 한다. 컬럼·키·제약은 [DB 설계서](DB_DESIGN_v1.md)를 참고한다.

## 적용 이력

`0001_initial_schema` → `0002_catalog_food_types` → `0003_db_first_schema` → `0004_csv_import_records`

마이그레이션은 DB 구조의 변경 이력이며 데이터 적재와 별개다. 앱은 시작할 때 `"Lunchrun".alembic_version`이 `0004_csv_import_records`인지 검사하고 테이블 생성·대표 메뉴 동기화를 자동 실행하지 않는다.

## 연결과 현재 상태 확인

저장소 루트의 `.env` 또는 실행 환경에 `DATABASE_URL`이나 `SUPABASE_DB_URL`을 설정한다. 기본 우선순위는 `DATABASE_URL` → `SUPABASE_DB_URL`이며, 실행 환경변수가 `.env`보다 우선한다. Alembic의 별도 `database_url` 실행 인자·설정이 있으면 환경변수보다 우선한다.

가상환경을 확인한 뒤 저장소 루트 PowerShell에서 조회한다.

```powershell
.\.venv\Scripts\python.exe --version
.\.venv\Scripts\alembic.exe current
.\.venv\Scripts\alembic.exe heads
```

앱과 Alembic은 PostgreSQL 주소를 psycopg 3 드라이버로 정규화하고 `search_path`와 버전 테이블의 스키마를 `Lunchrun`으로 지정한다. 연결 주소·비밀번호를 공유하거나 출력하지 않는다.

## 신규 DB와 기존 DB

- 신규 DB는 접속 역할·스키마·revision별 전제조건을 확인한 뒤 적용한다. `0003`은 기존 업무 테이블에 데이터가 있으면 재구성을 거부한다.
- 기존 DB는 백업·실제 스키마·현재 이력을 먼저 대조한다. `upgrade head`를 데이터 이전이나 일반 초기화 명령처럼 사용하지 않는다.
- `stamp`는 구조를 만들거나 검사하지 않고 이력만 기록한다. 구조가 일치하는지 확인하지 않은 채 head로 등록하지 않는다.
- 연결 주소 변경만으로 데이터가 복사되지는 않는다. 데이터 적재·이전은 별도 작업이다.

적용 대상과 전제조건을 확인한 경우의 명령:

```powershell
.\.venv\Scripts\alembic.exe upgrade head
```

`csv_import_record`는 `0004`에서 생성한다. ORM 모델에 포함되지 않으므로 Alembic의 메타데이터 비교 결과만으로 해당 테이블을 삭제해야 한다고 판단하지 않는다.

## 데이터와 복구

`0003`·`0004`는 자동 downgrade를 거부한다. 데이터 보존이 필요한 되돌리기는 별도 역마이그레이션으로 처리한다. 두 마이그레이션에는 업무·검토 테이블의 RLS 활성화와 `anon`·`authenticated` 테이블 권한 회수가 포함된다. 실제 배포 DB의 적용 여부는 별도로 확인한다.

API 요청의 PostgreSQL 세션은 읽기 전용이다. 스키마 변경·데이터 적재·대표 메뉴 관리는 별도 작업으로 수행한다. 대표 메뉴 수동 동기화는 [메뉴 관리 가이드](seed_management_v2.md)를 따르며 seed 명령은 `DATABASE_URL`만 읽는다는 점에 유의한다.
