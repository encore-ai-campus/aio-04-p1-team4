# Groq → Gemini 전환 가이드

채팅봇의 AI 호출을 Groq에서 Google Gemini(무료 티어)로 교체한 내용과 설정 방법을 정리한다.

## 변경 요약

| 구분 | Before (Groq) | After (Gemini) |
|---|---|---|
| 클라이언트 | `app/clients/groq.py` (`GroqClient`, `GroqError`) | `app/clients/gemini.py` (`GeminiClient`, `GeminiError`) |
| API 엔드포인트 | `https://api.groq.com/openai/v1/chat/completions` | `https://generativelanguage.googleapis.com/v1beta/openai/chat/completions` |
| 상태 확인 엔드포인트 | `GET /api/groq/status` | `GET /api/gemini/status` |
| 모델 목록 확인 | `GET /openai/v1/models` | `GET /v1beta/openai/models` |
| 오류 코드 | `groq_*` | `gemini_*` |
| 답변 출처 표시 | `answer_source: "groq"` | `answer_source: "gemini"` |
| 운영 점검 항목 | `checks.groq_configured` | `checks.gemini_configured` |

Gemini의 OpenAI 호환 엔드포인트를 사용하므로 기존 OpenAI 형식의 메시지·`response_format: json_object`·`choices[0].message.content` 파싱 로직은 그대로 유지된다. 질문 해석 → 의도 검증 → 서버 실행 → 답변 구성의 5단계 구조와 가드레일은 변경 없다.

## 환경변수

`.env` (또는 배포 환경변수)에 아래를 설정한다. `GEMINI_API_KEY`는 Google AI Studio(https://aistudio.google.com)에서 무료로 발급한다.

```dotenv
# 필수
GEMINI_API_KEY=발급받은_키

# 선택 (기본값 사용 가능)
GEMINI_MODEL=gemini-3.5-flash-lite
GEMINI_TIMEOUT_SECONDS=30
GEMINI_NARRATION_ENABLED=true
GEMINI_NARRATION_TIMEOUT_SECONDS=8
GEMINI_MAX_COMPLETION_TOKENS=2048
```

| 변수 | 기본값 | 설명 |
|---|---|---|
| `GEMINI_API_KEY` | (없음) | 필수. 미설정 시 채팅 호출에서 `gemini_config`(503) 반환 |
| `GEMINI_MODEL` | `gemini-3.5-flash-lite` | 사용할 Gemini 모델명. 무료 티어에서 사용 가능한 모델만 지정 |
| `GEMINI_TIMEOUT_SECONDS` | `30` | 질문 해석 호출의 전체 제한시간(초) |
| `GEMINI_NARRATION_ENABLED` | `true` | `false`면 5단계 답변 구성 AI 호출을 건너뛰고 서버 문장 사용 |
| `GEMINI_NARRATION_TIMEOUT_SECONDS` | `8` | 답변 구성 호출 제한시간(초). 실패해도 서버 답변으로 폴백 |
| `GEMINI_MAX_COMPLETION_TOKENS` | `2048` | 출력 토큰 상한. Gemini는 사고(thinking) 토큰도 이 한도에 포함하므로 Groq 시절(1024)보다 넉넉하게 설정 |

참고:

- 답변 구성(`compose_answer`)은 코드에서 `min(512, GEMINI_MAX_COMPLETION_TOKENS)`로 제한되므로 별도 조정이 필요 없다.
- 식당 상세 답변(주소·메뉴·영업시간)은 서버가 만든 문자열을 그대로 쓰며 모델 토큰을 소비하지 않는다.
- `GROQ_*` 환경변수는 더 이상 읽지 않는다. `.env`에 남아 있어도 무시된다.
- Gemini 2.5 계열(`gemini-2.5-flash` 등)은 신규 사용자에게 폐기되어 404를 반환한다. `gemini-3.5-flash-lite`를 기본값으로 사용하며, 더 높은 품질이 필요하면 `gemini-3.5-flash`로 바꿀 수 있다(응답이 느려질 수 있음).

## 오류 코드

외부 오류는 `X-Error-Code` 헤더와 `narration.reason`에 아래 코드로만 노출된다(응답 원문·키는 포함하지 않음).

`gemini_config`, `gemini_auth`, `gemini_permission`, `gemini_rate_limit`, `gemini_request`, `gemini_model`, `gemini_upstream`, `gemini_timeout`, `gemini_connection`, `gemini_response`, `gemini_truncated`, `gemini_policy`

## 확인 방법

1. 서버 재시작 후 `GET /api/gemini/status` 호출 → `status: "connected"` 확인.
2. `GET /api/readiness`의 `checks.gemini_configured`가 `true`인지 확인.
3. 채팅에서 추천 요청 → `answer_source`가 `"gemini"` 또는 `"server_fallback"`인지 확인.

## 테스트

- `tests/test_gemini_client.py`, `test_gemini_status.py`, `test_gemini_context.py`는 모의 HTTP 전송(`httpx.MockTransport`)으로 실제 키 없이 검증한다.
- `LUNCHRUN_LIVE_GEMINI=1`을 설정하면 `test_guardrail_live.py`가 실제 Gemini를 소량 호출해 해석 품질을 검사한다(기본은 스킵).
