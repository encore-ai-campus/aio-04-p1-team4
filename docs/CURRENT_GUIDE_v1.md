# 현재 코드 구조·수정 가이드

기준일: 2026-11-16. [API 설계서](API_DESIGN_v1.md)와 [DB 설계서](DB_DESIGN_v1.md)가 상세 기준입니다.

## 현재 처리 흐름

채팅은 화면 위치·조건 → Gemini 질문 해석 → 서버의 조건 적용·DB 조회 → 답변 구성·검증 → 응답·세션 저장 순서입니다. 일반 메뉴·식당 조회는 Gemini 질문 해석 없이 DB를 조회하며 신규 식당 수집은 별도 관리 작업입니다.

- 모델: app/clients/gemini.py. 설정은 app/config.py와 GEMINI_* 환경변수.
- 해석 지침: app/prompts/system_v4.txt.
- 퓨샷 예시: app/prompts/examples_v3.json.
- 고정 안내: app/prompts/replies_v4.json.
- 실행 계약: app/chat_policy.py의 QuestionInterpretation/ConditionPatch.
- 문단 구성: app/prompts/narration_v1.txt 및 app/answer_narration.py.
- 위 파일들은 코드가 읽지만 docs의 MD 파일은 실행 입력이 아닙니다.

## 기능을 바꾸려면

| 대상 | 코드 | 주의 |
|---|---|---|
| 추천·재추천·조건 변경·후속 질문 | app/services.py | 해석 결과만 신뢰하지 않고 서버가 실제 조건·대상 확정 |
| 반경·예산·영업시간 | app/db_recommendations.py | 홈·게임·지도·채팅의 공통 기준 |
| 요청 필드 | app/schemas.py | 프론트와 API 문서도 함께 갱신 |
| 음식 종류 | app/food_types.py | 화면 선택지·카탈로그 CHECK·migration도 확인 |
| 대표 메뉴 수동 관리 | app/database/seed.py | 직접 실행할 때 전체 목록 동기화. 목록 밖 메뉴 비활성화 가능 |
| 표시 가격·순서 기억 | app/chat_sessions.py | 실제 표시 상품의 당시 금액을 유지 |
| 화면 조건 동기화 | frontend/state.js, frontend/chat.js | 오래된 응답이 새 조건을 덮어쓰지 않도록 유지 |
| 게임 연결 | games/app.py, games/server.mjs | 기본 프록시는 Render. 로컬 실행과 구분 |

현재 메뉴 하나만 제외하여 재추천합니다. 후보 목록 요청은 최대 3개를 보여주고 하나를 대신 선택하지 않습니다. 식당은 최대 3곳이며 미확인 정보는 안내하고 명시적 휴무·폐업·시간 밖·예산 초과는 제외합니다. 음식 설명·품절·인분·맵기·채식 필터는 제공하지 않습니다.

## 데이터와 상태

Supabase PostgreSQL의 restaurant.id는 내부 UUID이고 kakao_id와 다릅니다. menu_catalog는 대표 메뉴, menu는 실제 식당 상품입니다. 원화 가격은 menu.price이며 price_hint를 쓰지 않습니다. 상품 FK가 연결되지 않은 메뉴는 일반 추천에 나타나지 않습니다.

서버 시작은 `0004_csv_import_records` revision을 검사하며 테이블·상품·대표 메뉴를 자동 구성하지 않습니다. seed.py는 수동 도구이고 `DATABASE_URL`만 읽습니다. 앱은 `DATABASE_URL`이 없으면 `SUPABASE_DB_URL`을 사용하므로, 수동 관리 전에 [메뉴 관리 가이드](seed_management_v2.md)의 대상 DB 조건을 확인합니다.

요일 0=월요일, 6=일요일. 같은 요일의 여러 구간으로 브레이크 타임을 표현합니다. 종료가 다음날이면 ends_next_day=true. open/closed/unknown은 저장 컬럼이 아니라 조회 시 계산합니다.

최근 10턴과 표시 식당은 메모리, 화면 상태는 sessionStorage, 게임 방은 JSON 파일입니다. 로그인·Redis·다중 인스턴스 상태 공유는 미구현입니다.

## 직접 점검

1. health로 생존, readiness로 DB·메뉴·필수 설정을 확인합니다. Chromium은 현재 optional입니다.
2. 메뉴 후보 → 메뉴 선정 → 식당 조회 → 순서별 가격·주소·영업 질문을 확인합니다.
3. 조건 변경 전후, 반경 50/500 경계, 후보 없음, 가격/시간 NULL, 과거 목록 무효화를 확인합니다.
4. /api/chat/session과 스트림 응답을 개발자 도구에서 비교합니다.
5. 추가 설명 생성에 실패하면 answer_source=server_fallback으로 기존 결과를 유지합니다. 질문 해석 실패 자체는 별도 오류입니다.

실행 전 `.\.venv\Scripts\python.exe --version`으로 가상환경을 확인합니다. Python 경로가 유효하지 않으면 환경을 정비한 뒤 서버·테스트를 실행합니다. 외부 모델·운영 DB를 사용하는 테스트는 대상과 설정을 확인한 뒤 수행합니다.
