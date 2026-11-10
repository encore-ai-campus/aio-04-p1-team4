# LunchRun 운영 점검표 v1

- 작성일: 2026-11-10

## 실행 전

- [ ] `.env`가 Git에 포함되지 않았는가?
- [ ] `MAP_API_KEY`, `KAKAO_JAVASCRIPT_KEY`, `GROQ_API_KEY`를 환경별로 분리했는가?
- [ ] `DATABASE_URL`이 대상 DB를 정확히 가리키는가?
- [ ] `alembic current`가 최신 revision인지 확인했는가?
- [ ] `playwright install chromium`을 실행했는가?
- [ ] HTTPS 배포에서는 `COOKIE_SECURE=true`인가?

## 상태 확인

- `GET /api/health`: 프로세스 생존 여부만 확인
- `GET /api/readiness`: DB, 활성 메뉴, Chromium, 카카오·Groq 설정 확인
- readiness는 실제 Groq·카카오 호출을 하지 않으므로 외부 사용량을 소모하지 않음
- 응답의 API 키·DB URL·외부 오류 원문 노출 여부 확인

## 요청 보호

- [ ] `CHAT_REQUESTS_PER_MINUTE`가 트래픽 수준에 맞는가?
- [ ] `CHAT_REQUESTS_PER_DAY`가 무료 Groq 사용량에 맞는가?
- [ ] `MAX_REQUEST_BYTES`가 프록시 제한과 일치하는가?
- [ ] 응답의 `X-Request-ID`를 프록시 로그에서도 유지하는가?
- [ ] NDJSON 응답을 프록시가 버퍼링하지 않는가?

## 로그

JSON 로그에 다음 값만 기록한다.

- 요청 ID, 메서드, 경로, 상태코드, 처리시간
- 외부 오류의 통제된 코드
- 검색·수집·추천 건수

질문 전문, API 키, 정확한 좌표, DB 연결 문자열은 기록하지 않는다.

## 장애 점검

- Groq 장애: 식당 검색을 임의 실행하지 않고 안전 오류 반환
- 카카오 장애: 빈 결과로 위장하지 않고 오류 코드 반환
- 상세수집 일부 실패: 성공 식당과 기존 저장정보로 계속 처리
- 서버 재시작: 메모리 대화와 진행 중 작업이 사라짐을 인지
- 다중 서버: Redis 없이 세션·요청 제한·중복 작업 상태가 공유되지 않음을 인지

## 배포 후

- [ ] `/api/health`가 200인가?
- [ ] `/api/readiness`가 200 `ready`인가?
- [ ] 실제 위치에서 메뉴 추천과 식당 추천이 완료되는가?
- [ ] 같은 요청의 로그가 동일한 `request_id`로 이어지는가?
- [ ] 스트림 취소 후 Playwright 프로세스가 남지 않는가?
- [ ] DB 백업과 복구 절차를 시험했는가?
