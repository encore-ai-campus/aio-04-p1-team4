# 운영 점검표

기준일: 2026-11-16. Supabase PostgreSQL·Gemini·DB 조회 기반 추천을 대상으로 한다.

## 실행 전

- `.env`·DB 비밀번호·Gemini/카카오 REST 키가 Git에 포함되지 않았는지 확인한다.
- `MAP_API_KEY`, `KAKAO_JAVASCRIPT_KEY`, `GEMINI_API_KEY`, `GEMINI_MODEL`을 확인한다. 카카오 JavaScript 키의 접속 도메인과 도보 API 사용 권한도 확인한다.
- `DATABASE_URL`이 `SUPABASE_DB_URL`보다 우선하며 실행 환경변수가 `.env`보다 우선한다. 대상 DB와 `Lunchrun` 스키마를 확인한다.
- `alembic_version`이 `0004_csv_import_records`인지 확인한다. 앱 시작은 스키마·상품·대표 메뉴를 자동 구성하지 않는다.
- `.\.venv\Scripts\python.exe --version`으로 가상환경을 확인한다. 실행되지 않으면 Python 설치 경로와 가상환경을 정비한 뒤 시작한다.
- HTTPS에서는 `COOKIE_SECURE=true`를 사용한다.
- 대표 메뉴를 수동 관리할 때는 [seed 명령의 DB 연결 조건](seed_management_v2.md)을 별도로 확인한다.

## 상태와 연결 경로

| 경로 | 확인 대상 |
| :---: | :---: |
| `GET /api/health` | HTTP 서버 생존 |
| `GET /api/readiness` | DB·활성 대표 메뉴·필수 키 설정. 외부 API는 호출하지 않으며 Chromium은 선택 항목 |
| `GET /api/gemini/status` | 모델 목록 조회를 통한 키·모델 접근 상태. 실제 답변 생성은 별도 확인 |
| `/games` | `games/app.py`의 `NODE_ORIGIN`에 지정된 원격 Node 서버 |

준비 상태는 기본 30초 캐시이며 `refresh=true`로 건너뛴다. Gemini 상태는 기본 60초, `refresh=true`일 때 5초 서버 캐시를 사용한다. Gemini 연결 여부는 HTTP 200만 보지 말고 응답의 `status`를 확인한다.

로컬 Node 서버를 실행해도 게임 프록시 대상은 자동 변경되지 않는다. 원격 배포본과 로컬 변경을 구분한다. 모임방 JSON 저장소는 DB와 별도이며 참여 토큰이 포함되므로 공개하지 않는다.

## 요청 제한과 장애

- 채팅 제한 변수는 `CHAT_REQUESTS_PER_MINUTE`(기본 10), `CHAT_REQUESTS_PER_DAY`(기본 100)다.
- FastAPI의 `MAX_REQUEST_BYTES` 기본값은 65536바이트이며 `Content-Length`를 검사한다.
- 게임 서버 POST는 본문 16384바이트, IP당 분당 180회 제한을 사용한다.
- `X-Request-ID`와 `X-Error-Code`로 오류를 추적하고 429 응답의 `Retry-After`를 확인한다.
- 채팅 스트림의 `failed` 이벤트를 처리한다. 시작 후에는 HTTP 200이어도 실패일 수 있다. 프록시가 NDJSON 진행 응답을 버퍼링하지 않도록 한다.
- 추가 설명 생성 실패는 `answer_source=server_fallback`으로 기존 결과를 유지하지만 질문 해석 실패는 별도 오류다.
- 가격·영업시간·휴무 미확인 안내와 후보 없음을 서버 장애와 구분한다. 일반 추천은 DB만 조회하며 지역 변경 시 새 식당을 자동 수집하지 않는다.
- 채팅 세션·요청 제한 상태는 프로세스 메모리다. 서버 재시작·만료 시 사라지며 여러 서버가 공유하지 않는다.
- 로그에 질문 전문·정확한 좌표·키·DB URL·외부 오류 원문을 남기지 않는다.

## 배포 후

위치·조건 설정 → 메뉴 후보·추첨 → 식당 추천 → 가격·주소·영업 후속 질문 → 조건 변경 → 지도·도보 경로를 확인한다. 화면과 `/api/chat/session`의 적용 조건·표시 상품을 대조한다.

모임방 생성·참여·선택·재투표와 최종 결과 공유를 확인한다. API로 방을 생성할 때는 `filters.origin`을 `[위도, 경도]`로 전달한다. 상세 입력은 [API 설계서](API_DESIGN_v1.md)를 따른다.

DB 백업·복구 절차, 실제 데이터 범위, RLS와 접속 역할 권한을 점검한다. 과거 수량·테스트 결과를 현재 점검 결과로 재사용하지 않는다.
