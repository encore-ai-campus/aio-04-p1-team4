# LunchRun DB 마이그레이션 안내 v1

- 작성일: 2026-11-10
- 도구: SQLAlchemy 2.x, Alembic 1.20.1

## 새 SQLite DB

프로젝트 루트에서 실행한다.

```powershell
.\.venv\Scripts\alembic.exe upgrade head
```

초기 마이그레이션은 식당·메뉴 카탈로그·메뉴 별칭·수집 메뉴·영업시간·상세수집 상태 테이블을 만든다. 기본 메뉴 시드는 앱 시작 시 `seed_menu_catalog()`가 중복 없이 등록한다.

## 기존 `create_all()` DB

기존 데이터가 있는 DB에는 초기 마이그레이션을 다시 실행하면 안 된다. 먼저 백업하고 현재 스키마가 ORM 모델과 같은지 검증한 후 이력을 등록한다.

```powershell
.\.venv\Scripts\alembic.exe stamp 0001_initial_schema
.\.venv\Scripts\alembic.exe current
```

`stamp`는 테이블과 데이터를 변경하지 않고 `alembic_version`만 기록한다.

## 변경사항 확인

```powershell
.\.venv\Scripts\alembic.exe check
```

`No new upgrade operations detected`가 정상이다. 차이가 나오면 자동 생성 결과를 그대로 적용하지 말고 모델·기존 데이터·SQLite/PostgreSQL 호환성을 검토한다.

## 이후 스키마 변경

```powershell
.\.venv\Scripts\alembic.exe revision --autogenerate -m "변경 내용"
.\.venv\Scripts\alembic.exe upgrade head
```

생성 파일을 검토한 뒤 실행한다. 운영 DB에서 `downgrade`를 실행하기 전에는 반드시 백업한다.

## PostgreSQL·Supabase 준비

`DATABASE_URL`을 SQLAlchemy psycopg 형식으로 설정한다.

```text
postgresql+psycopg://USER:PASSWORD@HOST:PORT/DATABASE?sslmode=require
```

- 비밀번호의 특수문자는 URL 인코딩한다.
- 연결 문자열과 키를 Git에 저장하지 않는다.
- 먼저 별도 테스트 DB에서 `upgrade head`와 전체 테스트를 실행한다.
- Supabase Auth는 현재 범위에 포함하지 않는다.
- 실제 이전 전 SQLite 백업과 PostgreSQL 데이터 이관 계획을 별도로 작성한다.

## 현재 앱 시작 동작

로컬 호환을 위해 앱 시작 시 `create_all()`과 멱등 시드를 계속 실행한다. 새 테이블 생성에는 도움이 되지만 기존 컬럼 변경은 처리하지 못하므로 운영 스키마 변경의 기준은 Alembic이다.
