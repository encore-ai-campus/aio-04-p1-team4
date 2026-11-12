# 7단계 통합·운영 검증 안내 v1

- 작성일: 2026-11-10
- 대상: Alembic, readiness, 요청 제한, 요청 ID, JSON 로그, 선택적 실제 통합검사

## 자동 테스트

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_database.py tests\test_chat_sessions.py -v
.\.venv\Scripts\python.exe -m pytest -q
node --test tests\chat-session-ui.test.cjs tests\groq-status.test.cjs tests\location.test.cjs tests\location-flow.test.cjs tests\restaurant-ui.test.cjs tests\map.test.cjs
```

## Alembic 확인

```powershell
.\.venv\Scripts\alembic.exe current
.\.venv\Scripts\alembic.exe check
```

기존 DB가 아직 Alembic에 등록되지 않았다면 백업·스키마 확인 후 `stamp 0001_initial_schema`를 실행한다.

## 상태 API 확인

```text
http://127.0.0.1:8000/api/health
http://127.0.0.1:8000/api/readiness?refresh=true
```

- health: `{"status":"ok"}`
- readiness: 모든 필수 점검이 참이면 HTTP 200과 `ready`
- Chromium 또는 설정이 누락되면 HTTP 503과 `not_ready`

## 요청 보호 확인

- 모든 HTTP 응답에 UUID 형태의 `X-Request-ID`가 있는지 확인한다.
- 분당 제한을 넘긴 채팅은 HTTP 429, `Retry-After`, `X-Error-Code: chat_rate_limit`을 반환해야 한다.
- `MAX_REQUEST_BYTES`보다 큰 요청은 HTTP 413이어야 한다.
- 제한된 요청이 Groq·카카오 API를 호출하지 않아야 한다.

## 실제 외부 통합검사

실제 API 사용량과 카카오 페이지 접근을 명시적으로 허용할 때만 실행한다.

```powershell
$env:LUNCHRUN_LIVE_INTEGRATION = "1"
.\.venv\Scripts\python.exe -m pytest tests\test_guardrail_live.py::LiveIntegrationTests -v
Remove-Item Env:LUNCHRUN_LIVE_INTEGRATION
```

테스트는 임시 SQLite DB를 사용하며 실제 Groq 해석, 카카오 검색, 상세페이지 수집과 스트림 완료 이벤트를 확인한다.

## 작성 시점 결과

- 전체 Python: `89 passed`, `2 skipped`, `36 subtests passed`
- 전체 프론트엔드: `34 passed`
- skip 2건: 실제 Groq 검사, 실제 전체 통합검사
- Starlette `TestClient` 사용 중단 예정 경고 1개는 이번 기능 실패가 아니다.
- 실제 외부 통합검사는 자동 실행하지 않았다.
