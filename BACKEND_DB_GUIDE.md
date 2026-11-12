# 처음부터 이해하는 LunchRun 백엔드·DB 점검 가이드

- 작성일: 2026-11-10
- 대상: Python·FastAPI·DB를 배우면서 이 프로젝트를 직접 관리하려는 개발자
- 목적: 코드를 한꺼번에 이해하려고 하기보다, 사용자 요청 하나를 따라가며 확인하고 작은 단위로 수정하기

## 1. 지금 내가 맡아야 할 역할

현재 코드는 기능이 빠르게 늘어난 상태입니다. 지금 해야 하는 일은 파일을 모두 외우는 것이 아니라, **원하는 동작을 정하고 실제 동작과 비교한 뒤, 차이가 생기는 위치를 찾는 것**입니다.

당신은 이 프로젝트에서 다음 세 역할을 맡습니다.

| 역할 | 해야 할 일 | 예시 |
|---|---|---|
| 기능을 결정하는 사람 | 사용자의 어떤 말을 어떻게 처리할지 정하기 | “김치찌개 먹고 싶어”는 김치찌개를 선택해야 함 |
| 데이터를 확인하는 사람 | 추천 근거가 DB에 실제로 있는지 확인하기 | 김치찌개 9,000원이라는 메뉴 행이 존재하는가? |
| 변경을 검증하는 사람 | 수정 전 실패와 수정 후 성공을 비교하기 | 지정 메뉴가 바뀌지 않고 카카오 검색도 불필요하게 호출되지 않는가? |

코드를 작성하는 도구에 요청할 때도 이 세 가지를 구체적으로 알려주면 됩니다. “가드레일 고쳐줘”보다 “명시한 메뉴를 선택하고, 조건 충돌 시 임의 대체하지 않게 해줘”가 검증하기 쉽습니다.

## 2. 먼저 알아둘 용어

| 용어 | 쉬운 설명 | 프로젝트 예 |
|---|---|---|
| 프론트엔드 | 사용자가 보고 누르는 화면 | `frontend/app.js` |
| 백엔드 | 화면의 요청을 받아 처리하는 서버 | FastAPI |
| API | 화면과 서버 또는 서버와 외부 서비스가 대화하는 통로 | `/api/chat/stream` |
| 요청/응답 | 화면이 보낸 데이터/서버가 돌려준 결과 | 질문과 조건/추천 결과 |
| 스키마 | 데이터의 형식과 규칙 | 예산은 정수, 반경은 50~500m |
| ORM | Python 객체로 DB를 다루게 하는 도구 | SQLAlchemy |
| PK | 행 하나를 구분하는 고유 식별값 | `restaurant.id` |
| FK | 다른 테이블의 행을 가리키는 연결값 | `menu.restaurant_id` |
| 세션 | 한 브라우저의 현재 대화 상태 | 선택 메뉴와 최근 식당 ID |
| 캐시 | 다시 가져오지 않고 재사용하는 저장정보 | 최근 수집한 영업시간 |
| 마이그레이션 | DB 구조 변경을 순서대로 기록·적용하는 작업 | Alembic revision |
| 가드레일 | AI의 해석과 실행을 제한하는 규칙 | 알려진 메뉴 ID만 허용 |
| 스트리밍 | 완료 전 처리 상황을 조금씩 전달하는 방식 | 수집 중 1/3 |

Python의 `None`, JSON의 `null`, SQL의 `NULL`은 각각 사용하는 곳이 다르지만 모두 값이 없음을 나타낼 때 사용합니다. 빈 문자열 `""`, 숫자 `0`, `False`는 별개의 실제 값입니다. 가격 미확인을 `0원`으로 저장하면 잘못된 추천이 나올 수 있습니다.

## 3. 코드는 이 순서로 읽으세요

한 번에 모든 파일을 읽지 말고, 아래 순서에서 매번 “이 파일이 무엇을 받아 무엇을 넘기는지”만 먼저 파악하세요.

| 순서 | 파일 | 확인 질문 |
|---|---|---|
| 1 | [app/schemas.py](app/schemas.py) | 화면에서 보내야 하는 위치·조건·질문 형식은 무엇인가? |
| 2 | [app/api.py](app/api.py) | 어느 주소로 들어온 요청이 어느 함수로 연결되는가? |
| 3 | [app/services.py](app/services.py) | 질문 의도별로 메뉴 선정·검색·DB 조회 중 무엇을 하는가? |
| 4 | [app/chat_policy.py](app/chat_policy.py)와 [프롬프트 폴더](app/prompts/) | AI에게 어떤 의도와 필드를 허용하는가? |
| 5 | [app/menu_catalog.py](app/menu_catalog.py) | 랜덤 후보가 어떤 조건으로 정해지는가? |
| 6 | [app/database/models.py](app/database/models.py) | 저장할 표와 열은 어떤 구조인가? |
| 7 | [app/recommendation_engine.py](app/recommendation_engine.py) | 무엇을 추천·후보·제외로 판정하는가? |
| 8 | [app/detail_collection.py](app/detail_collection.py) | 언제 다시 수집하고 언제 저장정보를 재사용하는가? |
| 9 | [app/place_details.py](app/place_details.py)와 [저장 함수](app/repositories/place_details.py) | 문자열을 어떻게 변환하고 기존 데이터를 교체하는가? |
| 10 | [app/main.py](app/main.py), [설정](app/config.py), [DB 연결](app/database/session.py) | 서버 시작·종료·환경변수·DB 세션은 어떻게 관리하는가? |

외부 통신이 의심될 때만 `app/clients/`와 `app/collectors/`를 추가로 읽으세요. 처음부터 Playwright DOM 선택자까지 이해할 필요는 없습니다.

## 4. 요청 하나를 끝까지 따라가 보기

먼저 `짜장면 식당 보여줘`라는 한 문장만 선택합니다.

1. 브라우저는 질문과 위치·조건·현재 메뉴 ID를 `/api/chat/stream`으로 보냅니다.
2. `api.py`는 세션과 요청 제한을 확인하고 `services.chat()`을 호출합니다.
3. Groq가 `search_restaurants`와 메뉴 ID를 반환합니다.
4. `chat_policy.py`가 의도와 ID의 형식을 검사합니다.
5. `services.py`가 `menu_catalog.py`를 통해 현재 조건에 맞는 메뉴를 확인합니다.
6. 카카오 검색 결과를 `restaurant`에 저장합니다.
7. 필요한 식당의 메뉴·영업시간을 수집하거나 기존 정보를 사용합니다.
8. 추천 엔진이 영업 여부·메뉴·가격을 검사합니다.
9. `completed` 이벤트가 최종 결과를 전달합니다.
10. 세션에는 질문·답변과 선택 메뉴·최근 식당 ID가 기록됩니다.

각 단계가 잘되는지 확인하면 “AI가 이상해요”를 “Groq가 메뉴 ID를 누락했어요” 또는 “DB에 해당 메뉴가 없어요”로 좁힐 수 있습니다.

## 5. 처음에는 수정하지 말고 현재 상태를 기록하세요

프로젝트 루트에서 다음 명령을 실행합니다.

```powershell
cd C:\TeamProject_1
git status --short
.\.venv\Scripts\python.exe -m pytest -q
```

기존 수정 파일이 많다면 현재 변경 목록을 먼저 보관하세요. 본인이 의도한 변경을 확인한 후 커밋하면 이후 비교가 쉬워집니다. `.env`와 DB 파일을 한꺼번에 커밋하지 않도록 주의하세요.

이어서 서버를 실행합니다.

```powershell
.\.venv\Scripts\python.exe -m uvicorn app.main:app --reload
```

다음 주소에서 상태를 확인합니다.

- `/api/health`: 서버가 응답하는지
- `/api/readiness?refresh=true`: DB·활성 메뉴·Chromium 실행파일·키 설정이 있는지
- `/docs`: 서버가 받는 요청 형식과 API 목록
- `/api/chat/session`: 같은 브라우저의 최근 대화와 현재 선택 상태

readiness의 키 설정 `true`는 “키 문자열이 있음”이라는 뜻입니다. 실제 인증 성공은 채팅과 검색으로 확인해야 합니다. Chromium도 설치파일 존재만 검사하므로 수집 성공 여부는 별도로 확인합니다.

## 6. 브라우저에서 내 요청 확인하기

1. F12로 개발자 도구를 엽니다.
2. Network 탭을 선택하고 채팅 질문을 보냅니다.
3. `/api/chat/stream` 요청을 엽니다.
4. Payload에서 `message`, `menu_id`, `conditions`, `location`, `radius_m`을 확인합니다.
5. Response에서 `completed` 또는 `failed` 이벤트를 찾습니다.
6. `completed.data.result.menu`와 추천 식당 목록을 확인합니다.

화면에서 예산을 바꿨다고 생각했는데 Payload에 이전 예산이 있으면 화면 상태 문제입니다. Payload는 맞는데 추천 후보가 잘못되면 서버의 해석·필터를 확인하면 됩니다.

질문 원문과 좌표는 Network에 표시되므로 이를 다른 사람에게 공유할 때는 개인정보와 키를 지우세요. API 키를 로그에 추가해 확인하는 방식은 피합니다.

## 7. DB를 직접 확인하는 방법

현재 기본 파일은 `data/lunchrun.db`입니다. `.env` 또는 운영 환경변수에 `DATABASE_URL`이 있으면 다른 파일이나 서버를 사용할 수 있으므로 먼저 실제 연결 대상을 확인하세요. 비밀번호가 든 URL은 공유하지 않습니다.

SQLite를 열 수 있는 DB 보기 도구에서 파일을 열고, 처음에는 조회 전용으로 확인합니다. 아래 SQL은 데이터를 바꾸지 않는 `SELECT` 문입니다. Python 코드를 새로 만들 필요 없이 DB 도구의 SQL 실행 창에서 사용할 수 있습니다.

### A. 추천 메뉴 목록

```sql
SELECT id, name, cuisine, search_keyword, price_hint, active
FROM menu_catalog
ORDER BY cuisine, name;
```

확인할 것: 김치찌개의 ID가 `kimchi`인지, 활성 상태인지, 검색어와 기준가격이 올바른지.

### B. 저장된 식당

```sql
SELECT id, name, cuisine, address, place_url
FROM restaurant
ORDER BY name;
```

확인할 것: 카카오 ID가 다른 지점과 섞이지 않았는지, 식당명과 주소가 실제 검색 결과와 맞는지.

### C. 실제 메뉴와 가격

```sql
SELECT r.name AS restaurant_name, m.name AS menu_name,
       m.price, m.price_status
FROM menu AS m
JOIN restaurant AS r ON r.id = m.restaurant_id
ORDER BY r.name, m.name;
```

`menu_catalog.price_hint`와 이 쿼리의 `menu.price`는 다릅니다. 전자는 후보 선정 기준이고 후자가 매장 수집 가격입니다.

### D. 수집 성공 여부

```sql
SELECT r.name, s.menu_status, s.hours_status,
       s.last_attempt_at, s.last_success_at, s.error_code
FROM restaurant AS r
LEFT JOIN place_detail_status AS s ON s.restaurant_id = r.id
ORDER BY r.name;
```

| 상태 | 의미 | 다음 확인 |
|---|---|---|
| `pending` | 아직 확인 대기 | 요청당 3곳 제한에 걸렸는가? |
| `success` | 해당 정보 수집·파싱 성공 | 실제 행과 값이 맞는가? |
| `missing` | 페이지를 읽었지만 정보가 없음 | 상세페이지에도 정보가 없는가? |
| `fetch_failed` | 페이지 접근 실패 | Chromium 설치, 접근 URL, 네트워크 |
| `parse_failed` | 읽은 내용을 해석하지 못함 | 페이지 구조·표현과 파서 규칙 |

### E. 요일별 영업 구간

```sql
SELECT r.name, h.day_of_week, h.holiday,
       h.start_time, h.end_time, h.ends_next_day, h.sequence
FROM business_hours AS h
JOIN restaurant AS r ON r.id = h.restaurant_id
ORDER BY r.name, h.day_of_week, h.sequence;
```

요일은 월요일 `0`부터 일요일 `6`입니다. `holiday`는 `True=휴무`, `False=휴무 아님`, `NULL=미확인`입니다. SQLite 도구에서는 True/False를 1/0으로 표시할 수 있습니다.

11~15시와 17~21시로 두 행이 있다면 15~17시는 영업 구간이 아닙니다. 18~다음 날 02시는 `ends_next_day=True`로 표현합니다.

## 8. 먼저 검토할 기능과 결정할 정책

다음 항목은 고쳤다고 가정하지 말고 실제 동작을 확인한 후 수정할 과제입니다.

### 우선순위 1: 명시한 메뉴가 랜덤 메뉴로 바뀌는 문제

현재 `select_menu` 의도는 없습니다. `recommend_menu`에서는 메뉴 ID를 받지 않도록 제한하므로 “김치찌개 먹고 싶어”가 일반 추천으로 해석되면 랜덤 추첨이 실행될 수 있습니다.

당신이 결정할 정책:

- “김치찌개 먹고 싶어”는 메뉴만 선택할 것인가, 식당까지 자동 검색할 것인가?
- 예산이나 음식 종류와 충돌하면 조건 변경을 물을 것인가?
- DB 카탈로그에 없는 메뉴는 어떤 안내를 할 것인가?

확인·수정 위치: `system_v2.txt`, `examples_v2.json`, `QuestionInterpretation`, `services.chat()`. 프롬프트만 변경하면 새 의도가 Pydantic에서 거부될 수 있으므로 네 부분을 함께 설계해야 합니다.

완료 기준: 김치찌개를 명시하면 다른 메뉴가 나오지 않고, 조건 충돌 시 이유가 표시되는가?

### 우선순위 2: 조건 변경 뒤 동작

현재 서버는 `suggested_patch`와 `search_after_change`를 반환하고 화면은 적용 버튼으로 조건을 반영합니다. 화면의 `applyChatPatch()`는 적용 후 다시 추천을 요청하라고 안내합니다.

당신이 결정할 정책: “한식으로 바꿔줘”라고 했을 때 즉시 적용할지, 확인 버튼을 유지할지, 적용 후 메뉴를 자동으로 다시 뽑을지 정하세요. 자동 검색까지 원한다면 프론트와 서버를 함께 연결해야 합니다.

### 우선순위 3: 메뉴 후보가 예상보다 적은 경우

주변에 확인된 실제 메뉴 근거가 하나라도 있으면 카탈로그 후보는 섞지 않습니다. 카탈로그에 없는 실제 메뉴는 추첨 후보로 자동 등록되지 않습니다.

예를 들어 주변 확인 메뉴가 짜장면 하나이면, 전체 음식 조건이어도 최초 추첨 후보가 짜장면 하나일 수 있습니다. 이 정책을 유지할지, 다른 카탈로그 메뉴도 제안할지 결정하세요.

### 우선순위 4: 영업시간 미확인과 실패 후 기존 데이터

실패 시 기존 메뉴·영업시간 행은 남지만 상태가 실패로 바뀌면 추천에서 제외될 수 있습니다. “이전 정상 데이터를 일정 기간 허용할지”는 별도 정책입니다. 보존과 추천 재사용은 같은 뜻이 아닙니다.

일부 요일만 수집됐을 때 다른 요일을 단순 `closed`로 봐도 되는지도 점검하세요. 정보 부족과 실제 휴무를 혼동하지 않도록 사례를 모으는 것이 좋습니다.

### 우선순위 5: 메뉴 이름 연결 정확도

현재 대표명·별칭이 실제 메뉴명에 포함되는지 비교합니다. “수제 왕돈까스”는 돈가스로 연결되지만 비슷한 글자가 다른 음식에도 포함될 수 있습니다. 실제 DB 메뉴명을 보면서 잘못 연결되는 예시를 테스트로 남기세요.

## 9. 메뉴 데이터와 테이블 구조는 다르게 수정하세요

### 기존 메뉴의 이름·설명·기준가격만 바꾸는 경우

기존 `menu_catalog` 행의 값을 수정하는 데이터 변경입니다. 테이블 열이 바뀌는 것이 아니므로 일반적으로 새 스키마 마이그레이션은 필요하지 않습니다.

`database/seed.py`를 고쳐도 이미 있는 DB 행은 덮어쓰지 않습니다. 해당 DB 행을 어떻게 갱신할지 별도로 정해야 합니다. 테스트용 DB에서 먼저 확인하세요.

### 메뉴 카탈로그를 확장하는 경우

새 `menu_catalog` 행과 필요한 `menu_alias`를 준비합니다. 현재 음식 종류는 DB 체크 제약과 Pydantic 허용값으로 제한됩니다. 새 분류를 추가하려면 카탈로그 행만 넣는 것으로 끝나지 않을 수 있습니다.

### 새 열을 추가하는 경우

예: `restaurant`에 전화번호를 추가한다면 모델과 Alembic 마이그레이션, 저장 로직, API 반환·화면 사용 여부를 함께 검토합니다. `create_all()`은 기존 테이블에 새 열을 추가하지 않습니다.

기존 DB는 백업·구조 확인 후 기준선을 등록해야 합니다. 아직 등록 여부를 모르는 상태에서 `stamp head`를 먼저 실행하지 마세요. [마이그레이션 안내](docs/database_migration_guide_v1.md)를 참고하세요.

## 10. 수정은 이 순서로 한 가지씩 하세요

1. 재현 문장을 적습니다. 예: “김치찌개 먹고 싶어”.
2. 현재 조건과 현재 응답을 적습니다. 예: 전체·12,000원·500m, 짬뽕 응답.
3. 기대 동작을 한 문장으로 정합니다. 예: 김치찌개 선택, 식당 검색은 별도 요청 시 실행.
4. 요청 Payload와 DB를 확인해 문제 위치를 좁힙니다.
5. 관련 파일만 수정합니다.
6. 수정한 행동을 검증할 테스트를 추가하고 실행합니다.
7. 같은 문장을 브라우저에서 다시 입력합니다.
8. 관련 조건 충돌·누락 데이터·후속 질문도 확인합니다.
9. 변경 이유와 검증 결과를 새 버전 MD에 기록합니다.

프롬프트는 기존 파일을 보존하고 새 버전을 만든 뒤 `chat_policy.py`의 경로 상수를 최신 파일로 바꿉니다. 새 파일을 만들기만 하면 실행에 반영되지 않습니다.

## 11. 수정 종류별로 실행할 테스트

| 수정 대상 | 우선 실행할 테스트 |
|---|---|
| 질문 의도·프롬프트·응답 계약 | `test_chat_policy.py`, `test_chat_policy_v2.py`, `test_groq_context.py` |
| 추천·후속 질문 실행 | `test_recommendations.py` |
| 메뉴 후보·별칭 | `test_menu_catalog.py`, `test_recommendation_engine.py` |
| 영업시간·가격 파싱·수집 | `test_place_details.py`, `test_recommendation_engine.py` |
| DB 모델·마이그레이션 | `test_database.py` |
| 세션·요청 제한·상태 API | `test_chat_sessions.py` |
| 화면 스트림·변경안 적용 | `restaurant-ui.test.cjs`, `chat-session-ui.test.cjs` |

예: 추천과 가격 후속 질문을 바꿨다면 다음부터 실행합니다.

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_recommendations.py -v
```

관련 테스트가 통과한 다음 전체 Python 회귀 테스트로 다른 동작에 영향이 없는지 확인합니다.

```powershell
.\.venv\Scripts\python.exe -m pytest -q
```

모의 테스트 통과는 실제 Groq의 모든 문장을 보장하지 않습니다. 대표 문장은 브라우저에서도 확인하고, 필요할 때만 [README의 실제 API 검사](README.md#테스트)를 실행하세요.

## 12. 결과를 기록하는 양식

이 표를 복사해 하나의 기능씩 기록하면 됩니다.

| 항목 | 기록 |
|---|---|
| 확인할 기능 | 명시 메뉴 선택 |
| 사용자 문장 | 김치찌개 먹고 싶어 |
| 위치·반경·예산·음식 종류 | 직접 입력 |
| 현재 응답 | 직접 입력 |
| 기대 응답 | 김치찌개 선택 |
| 요청 menu_id와 해석 intent | 확인할 수 있는 값 기록 |
| DB 관련 행 | menu_catalog의 kimchi 등 |
| 원인 후보 | 해석 누락 / 검증 / 후보 조회 / 화면 상태 |
| 변경 파일 | 실제 변경 후 기록 |
| 검증 결과 | 테스트 출력과 브라우저 재현 결과 |

처음 점검은 “명시 메뉴 선택”, “랜덤 후보가 만들어지는 기준”, “조건 변경 후 자동 동작” 세 가지부터 시작하세요. 이 흐름을 이해하면 외부 수집과 DB의 역할도 연결해서 이해하기 쉬워집니다.
