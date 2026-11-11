# 메뉴 카탈로그 관리 v2: 음식 종류 확장

- 작성일: 2026-11-12
- 이전 문서: `seed_management_v1.md`
- 마이그레이션: `0002_catalog_food_types`

## 저장 가능한 분류

한식, 중식, 일식/회, 양식, 분식, 패스트푸드, 치킨, 도시락/구내식당,
뷔페식, 냉면, 고기, 카페/빵, 술집, 기타.

화면의 15개 선택지 중 `전체`는 검색 옵션이므로 개별 메뉴에 저장하지 않는다.
`seed.py`의 cuisine에는 위 이름을 정확히 사용한다. 카카오 업태 이름인 `중국식`, `까페` 등은
식당 원본 분류로 유지하며 카탈로그에는 각각 `중식`, `카페/빵`으로 등록한다.

## 기존 데이터 처리

- 일식 → 일식/회
- 샐러드 → 기타
- 나머지 기존 카탈로그 분류는 유지
- 메뉴 ID·이름·별칭·가격·검색어·활성 상태·작성 시각 보존
- 식당 기본정보, 수집 메뉴, 영업시간, 상세수집 상태는 변경하지 않음

Alembic은 기존 CHECK를 해제하고 분류 두 값만 바꾼 뒤 14개 저장 분류 CHECK를 생성한다.
SQLite는 테이블 배치 복사를 사용하고 PostgreSQL은 제약조건 변경으로 처리한다.
초기 Alembic 생성 DB와 create_all 생성 DB의 제약 이름 차이도 처리한다.

## 실제 적용 결과

프로젝트의 `data/lunchrun.db`에 적용했다. 기존 DB는 Alembic 이력이 없어 초기 스키마와
비교한 뒤 `0001_initial_schema`로 등록하고 `0002_catalog_food_types`까지 올렸다.
`data/backups/lunchrun_pre_catalog_types_20261112_012701_394755.db`에 적용 전 백업을 보관한다.
백업 폴더는 Git에서 제외한다.

적용 전후 전체 행을 비교해 카탈로그 분류 변환 외에는 값이 같음을 확인했다.
식당 58, 수집 메뉴 585, 영업 구간 207, 수집 상태 58, 카탈로그 10, 별칭 15행을 보존했다.
SQLite integrity_check와 foreign_key_check 및 Alembic check가 통과했다.

## 메뉴 편집과 동기화

`app/database/seed.py` 목록을 편집한 뒤 다음 명령을 실행한다.

```powershell
.\.venv\Scripts\python.exe -m app.database.seed
```

추가·수정·별칭 교체·목록에서 빠진 메뉴 비활성화·동일 ID 재활성화를 지원한다.
이번 마이그레이션에서는 전체 시드 동기화를 실행하지 않아 기존 사용자 편집값을 덮어쓰지 않았다.
예를 들어 치킨 메뉴를 추가할 때 cuisine을 `치킨`으로 지정할 수 있다.
새 메뉴 자체는 자동 생성하지 않는다.

## 다른 환경과 Supabase

기존 Alembic 등록 DB는 백업 후 다음을 실행한다.

```powershell
.\.venv\Scripts\alembic.exe upgrade head
.\.venv\Scripts\alembic.exe check
```

기존 create_all DB는 무조건 head로 stamp하지 않는다. 기존 스키마와 이력을 확인한 뒤
초기 버전으로 등록하고 upgrade를 실행해야 데이터 변환이 수행된다.
새 DB는 upgrade head부터 실행하고 앱 시작 또는 시드 명령으로 초기 메뉴를 준비한다.
Supabase에서는 DATABASE_URL을 PostgreSQL psycopg 주소로 설정해 동일 마이그레이션을 사용한다.
실제 Supabase 연결에서의 검증은 아직 수행하지 않았다.

이전 5개 분류로 줄일 때는 기타 등 새 분류 데이터를 무손실로 되돌릴 수 없으므로
downgrade를 거부한다. 복구가 필요하면 서버를 중지한 뒤 백업을 복원한다.

## 직접 확인

1. 서버 재시작 후 브라우저를 새로고침한다.
2. DB의 menu_catalog에서 돈가스·우동이 일식/회, 병아리콩 샐러드가 기타인지 확인한다.
3. 아래 테스트로 전체 분류 저장과 마이그레이션 데이터 보존을 확인한다.

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_database.py tests\test_menu_catalog.py -q
```

## 추가·수정·삭제 예시

아래 코드는 설명용 예시이며 실제 seed.py나 DB에 떡볶이를 추가한 것은 아니다.

### 1. 메뉴 추가

`C:\TeamProject_1\app\database\seed.py`를 열고 `DEFAULT_MENU_CATALOG = (...)`의
닫는 괄호 앞에 다음 항목을 넣는다. 다른 항목과 구분하도록 끝에 쉼표를 붙인다.

```python
dict(
    id="tteokbokki",
    name="떡볶이",
    cuisine="분식",
    price_hint=7000,
    search_keyword="떡볶이",
    description="떡을 소스에 조리한 분식 메뉴예요.",
    aliases=("떡볶이", "국물떡볶이"),
),
```

| 항목 | 의미와 편집 규칙 |
|---|---|
| id | 고유 식별자. 다른 메뉴와 중복되지 않게 작성하고 같은 메뉴 수정 시 유지 |
| name | 화면에 표시할 대표 메뉴명 |
| cuisine | 위에 나열한 14개 저장 분류 중 하나. 전체는 사용 불가 |
| price_hint | 후보를 좁히는 기준가격. 원 단위 정수이며 실제 매장 가격을 보장하지 않음 |
| search_keyword | 카카오에서 주변 식당을 검색할 검색어 |
| description | 메뉴 설명 |
| aliases | 실제 수집 메뉴와 연결할 다른 표기. 다른 메뉴의 별칭과 중복 불가 |

별칭이 하나뿐인 튜플도 `aliases=("떡볶이",)`처럼 쉼표가 필요하다.
메뉴 이름도 실제 수집 메뉴와 연결하려면 aliases에 포함하는 것이 좋다.

### 2. 메뉴 수정

같은 떡볶이 항목에서 기준가격을 변경한다.

```python
price_hint=8000,
```

설명도 해당 줄을 바꾸면 된다.

```python
description="떡과 어묵을 소스에 조리한 분식 메뉴예요.",
```

같은 메뉴이므로 `id="tteokbokki"`는 유지한다. 이름·음식 종류·검색어·별칭도 같은 방식으로 수정할 수 있다.
별칭 목록에서 지운 표기는 동기화 후 DB 별칭에서도 제거된다.

### 3. 메뉴 삭제와 복원

삭제하려면 `id="tteokbokki"`인 `dict(...),` 전체를 목록에서 지운다.
DB의 카탈로그 행은 삭제하지 않고 `active=False`로 변경하여 추첨 대상에서 제외한다.
식당에서 수집한 실제 메뉴·가격·영업시간은 유지한다.

복원하려면 같은 ID의 항목을 다시 추가하고 동기화한다. 기존 행이 `active=True`로 돌아온다.
ID를 변경하면 이전 메뉴 비활성화와 새 메뉴 추가로 처리된다.

### 4. 파일 저장 후 DB 반영

실행 중인 서버를 종료하고 파일을 저장한 뒤 프로젝트 루트 PowerShell에서 실행한다.

```powershell
cd C:\TeamProject_1
.\.venv\Scripts\python.exe -m app.database.seed
```

출력 예시는 다음과 같다. 숫자는 현재 DB와 편집 내용에 따라 달라진다.

```json
{"inserted": 1, "updated": 10, "deactivated": 0}
```

- inserted: 신규 메뉴 수
- updated: 동기화 목록에 있는 기존 메뉴 수. 실제 변경 필드가 없는 행도 포함
- deactivated: 이번 실행으로 새로 비활성화된 메뉴 수

추가·수정·삭제를 반영하려면 파일 저장 후 위 동기화 명령을 실행한다.
서버 시작 시의 초기화는 누락 항목만 추가하므로 수정·삭제까지 반영하는 명령을 대신하지 않는다.

완료 후 `run.ps1`로 서버를 다시 시작하고 브라우저를 새로고침한다.
전체 목록을 비우면 실수로 모든 메뉴가 비활성화되는 것을 막기 위해 오류가 발생한다.
중복 ID·이름·별칭 등 검증 오류가 발생하면 수정 후 다시 실행한다.
