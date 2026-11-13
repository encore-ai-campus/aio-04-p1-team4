# 챗봇 추천 정책 v5 — 5단계: Groq 답변 구성

- 대상 프로젝트: C:\temp_resolved
- 이전 단계: [4단계 조건 즉시 적용](chatbot_recommendation_policy_v5_stage4.md)
- 기존 문서는 보존하고 이 문서에 5단계 변경분을 기록합니다.

## 1. 역할과 구현 범위

지금까지 Groq는 질문을 실행 계획으로 해석하고, 서버가 추천과 답변 문장을 모두 만들었습니다. 이제 서버 결과가 확정된 뒤 Groq에 한 번 더 요청하여 답변의 도입·연결 표현과 문단 구성을 정합니다.

| 역할 | 담당 |
|---|---|
| 질문 의도·대상·조건 변경 해석 | Groq의 기존 interpret 호출 |
| 메뉴 선정·예산 적용·식당 정렬·가격·주소·영업 판정 | 서버와 DB |
| 도입/연결 표현 선택·문단 구성 | Groq의 새 compose_answer 호출 |
| 사실 문장 삽입·누락/순서 검증·실패 대체 | 서버 |

**자유로운 사실 재서술은 허용하지 않습니다.** 자연어 문장을 자유롭게 생성한 뒤 모든 의미 왜곡을 자동 검증하는 것은 보장하기 어렵습니다. 이번 구현은 서버의 사실 문장과 필수 안내를 그대로 보존하고 Groq가 허용된 표현과 문단 구성을 선택하는 방식입니다. 결과가 이전과 비슷할 수 있으며, 답변이 달라 보이지 않는다고 해서 반드시 Groq가 실패한 것은 아닙니다. 응답의 answer_source로 확인합니다.

예를 들어 기존 식당 목록 앞에 `확인한 내용을 정리해드릴게요.`를 붙이거나 메뉴·조건과 식당 목록을 별도 문단으로 나눌 수 있습니다. 식당명·상품·가격·주소·영업 상태와 목록 순서는 바꾸지 못합니다.

## 2. 내부 흐름

1. 기존 Groq 해석 및 서버의 추천/후속 답변 처리를 실행합니다.
2. 서버 답변을 줄별 사실 문장으로 나눠 0부터 ID를 붙입니다.
3. 현재 질문, 최근 최대 10턴, 적용 조건, 선택 메뉴, 최대 3곳의 식당, 후속 질문 결과, 사실 문장을 답변 구성 전용 프롬프트로 전달합니다.
4. Groq는 허용된 opening/closing과 fact_ids를 가진 JSON 문단 계획만 반환합니다.
5. 서버는 ID가 원래 순서대로 정확히 한 번씩 모두 포함되었는지, 허용되지 않은 문구·추가 필드가 없는지 검사합니다.
6. 검증을 통과하면 각 ID를 원래 서버 문장으로 치환하여 답변을 구성합니다. 구조화된 메뉴·식당·적용 조건은 수정하지 않습니다.
7. 실패하면 추가 재시도 없이 원래 서버 답변을 사용합니다. 일반/스트림 API와 세션 저장에 같은 동작을 적용합니다.

전체 메뉴 후보 목록이나 DB 전체를 전송하지 않습니다. 대화 이력은 최신 10턴에 한하여 질문 500자·답변 1500자로 제한합니다. 위치는 설명에 필요한 이름만 추가하며 정확한 좌표·인증키를 답변 구성에 넣지 않습니다. 주소 질문 등 필요한 DB 정보는 서버가 확정한 사실 문장/상세 결과에 포함됩니다.

조건 변경 시에는 요청 당시 값이 아니라 실제 적용 후 조건·반경을 전달합니다. 새 메뉴 추천 응답에 식당 목록이 비어 있으면 과거 목록으로 채우지 않습니다.

## 3. 검증과 대체 답변

다음 출력은 거부합니다.

- 사실 문장 누락·중복·순서 변경 또는 범위 밖 ID
- 허용 목록 밖 도입/마무리 표현
- 임의 식당·가격·주소·영업 문장, 추가 text 필드
- 중복 JSON 키, 잘린 응답, 잘못된 형식, 도구 호출·거절 응답
- 세션 저장 범위를 넘는 최종 답변 길이

가격 미확인·영업시간 미기재·조건 변경 전후·최소/최대 반경 안내 등은 서버 사실 문장에 포함되어 통째로 보존됩니다. 누락 정보를 추측하도록 요청해도 문장을 추가할 수 없습니다.

답변 구성의 사용량 제한·인증 오류·연결 실패·시간 초과·형식 오류는 원래 서버 답변으로 대체합니다. 추천 결과와 변경 조건을 버리지 않습니다. 요청 자체를 사용자가 취소하면 취소를 유지합니다.

**질문 해석 단계까지 실패한 경우는 다릅니다.** 실행할 의도를 확정하지 못했으므로 기존 오류 안내를 반환합니다. Groq 사용량이 이미 소진되어 첫 해석 호출이 실패하면 서버 추천 답변으로 무조건 우회하는 기능은 아닙니다.

범위 밖 질문, 모호한 확인 질문, 미확정 식당 대상 안내는 고정 서버 답변을 사용하고 추가 호출을 생략합니다.

## 4. 설정과 응답 시간·사용량

새 패키지 설치는 필요하지 않습니다. 기존 Pydantic/httpx를 사용합니다. 설정 기본값은 다음과 같습니다.

```dotenv
GROQ_NARRATION_ENABLED=true
GROQ_NARRATION_TIMEOUT_SECONDS=8
```

필요하면 C:\temp_resolved\.env에 추가하고 서버를 재시작합니다. 실제 .env나 인증키는 이번 작업에서 변경하지 않았으며 .env.example에 예시만 추가했습니다. 운영 환경변수는 .env보다 우선합니다.

- 정상 추천/후속 질문: 기존 질문 해석 외에 답변 구성 호출 1회 추가
- 답변 구성 출력 상한: 기존 GROQ_MAX_COMPLETION_TOKENS와 512 중 작은 값
- 답변 구성 HTTP 제한시간: 기본 8초, 별도 재시도 없음
- 질문 해석의 기존 재시도·제한시간은 유지
- 최근 10턴을 두 단계에 전달하므로 입력 토큰도 증가할 수 있음
- 추가 실제 지연·사용량은 실행 시 메타데이터로 확인하며 실제 서비스 비용/속도를 미리 단정하지 않음

GROQ_NARRATION_ENABLED=false이면 추가 설명 호출만 생략합니다. 질문 해석·추천·조건 변경·후속 질문은 기존 방식으로 동작합니다.

## 5. 진행 표시와 진단 정보

스트림에 generating_answer 이벤트와 `답변을 정리하고 있어요.` 안내를 추가했습니다. 기존 스피너와 진행 상태 표시가 이를 사용합니다. 최종 답변을 토큰/글자 단위로 출력하는 기능은 이번 변경에 포함되지 않습니다.

최종 응답에 다음 정보를 추가합니다.

| 필드 | 의미 |
|---|---|
| answer_source=groq | Groq 문단 계획이 검증을 통과함. 사실 문장 자체는 서버 원문 |
| answer_source=server_fallback | 설명 생성/검증 실패로 서버 답변 사용 |
| answer_source=server | 비활성화 또는 고정 안내로 추가 호출 생략 |
| narration.elapsed_ms | 추가 답변 구성 단계의 경과 시간. 전체 요청 시간과 다름 |
| narration.usage | Groq가 반환한 답변 구성 호출의 prompt/completion/total 토큰 숫자. 미제공이면 null |
| narration.reason | 생략/실패 사유 코드. 예: disabled, fixed_reply, groq_timeout, narration_validation |

토큰 정보는 **추가 답변 구성 호출에 한정**되며 질문 해석까지 합친 총량은 아닙니다. 서버 로그에는 통제된 사유 코드만 기록하며 질문·위치·키·외부 응답 원문을 추가하지 않습니다.

## 6. 직접 검증

기존 서버 창에서 Ctrl+C로 종료 후 PowerShell에서 실행합니다.

```powershell
cd C:\temp_resolved
.\run.ps1
```

http://127.0.0.1:8000/ai 를 열고 Ctrl+F5로 새로고침합니다. 위치·예산·음식 종류·반경·점심 종료 시각을 설정합니다.

1. `메뉴 추천해줘`: 메뉴·조건·식당 조회 제안이 유지되는지 확인합니다. 진행 중 답변 정리 안내가 나올 수 있습니다. 응답이 빠르면 상태 문구를 눈으로 보기 어려울 수 있습니다.
2. `이 메뉴 파는 식당 알려줘`: 최대 3곳의 실제 상품명·가격·누락 안내가 그대로 표시되는지 확인합니다.
3. `첫 번째 식당 가격은?`: 앞서 표시한 상품 가격을 답하는지 확인합니다.
4. `왜 추천했어?`: 마지막 추천 종류에 맞는 이유 문구가 유지되는지 확인합니다.
5. `예산을 8천원으로 바꿔줘`: 변경 전후·재선정 메뉴가 나오고 홈의 조건도 반영되는지 확인합니다.
6. 개발자 도구 Network에서 /api/chat/stream 응답의 마지막 completed 이벤트를 펼칩니다. data.answer_source와 data.narration을 확인합니다. 성공 여부는 문체 변화만으로 판단하지 않습니다.
7. 해당 DB에 미확인 가격/영업시간 식당이 있으면 필수 확인 문구가 유지되는지 확인합니다. 없다면 아래 자동 검증을 사용하며 운영 DB를 바꿀 필요는 없습니다.

### 설명 비활성화 확인

.env에 GROQ_NARRATION_ENABLED=false를 지정하고 재시작한 뒤 같은 질문을 합니다. answer_source=server, narration.reason=disabled여야 합니다. 질문 해석은 여전히 Groq를 사용합니다. 확인 후 true로 되돌리고 재시작합니다.

### 시간 초과 대체 확인

자동 테스트가 권장됩니다. 실제로 확인하고 싶다면 설명 기능을 true로 두고 GROQ_NARRATION_TIMEOUT_SECONDS=0.001로 매우 짧게 설정한 뒤 재시작합니다. 설명 요청이 제한시간을 초과하면 server_fallback과 groq_timeout으로 기존 서버 답변이 나와야 합니다. 환경에 따라 결과가 다를 수 있으므로 Network에서 사유를 확인합니다. 확인 후 기본값 8로 복구하고 재시작합니다. 질문 해석용 키를 삭제하는 방식은 이 검증에 적합하지 않습니다.

실제 API 검증은 Groq 사용량을 소모합니다. 기존 세션별 요청 제한도 그대로 적용됩니다.

## 7. 자동 검증과 변경 파일

```powershell
cd C:\temp_resolved
.\.venv\Scripts\python.exe -m pytest tests/test_answer_narration_stage5.py tests/test_chat_conditions_stage4.py tests/test_chat_followups_stage3.py tests/test_recommendations.py tests/test_chat_sessions.py tests/test_chat_policy_v2.py tests/test_db_first_flow.py tests/test_recommendation_policy_stage1.py tests/test_groq_client.py tests/test_groq_context.py tests/test_locations.py tests/test_chat_browser_flow.py -q -p no:cacheprovider
```

임시 SQLite, 모의 Groq/카카오, MockTransport를 사용합니다. 실제 Groq·운영 DB를 호출하지 않습니다. 브라우저 통합 검증은 실제 화면·임시 서버를 사용하고 외부 모델 응답만 모의 처리합니다.

새 파일:

- app/answer_narration.py: 계획 계약, 문장 보존 검증, 문단 구성, 실패 대체
- app/prompts/narration_v1.txt: 답변 구성 전용 지침
- tests/test_answer_narration_stage5.py: 변조·누락·시간 초과·대체 답변·사용량 검증
- docs/chatbot_recommendation_policy_v5_stage5.md: 이 문서

수정 파일:

- app/clients/groq.py: 설명 구성용 추가 호출, 오류·사용량 정리
- app/config.py 및 .env.example: 추가 호출 활성화·제한시간 설정
- app/api.py: 일반/스트림 공통 답변 구성과 세션 저장 연결
- tests/test_recommendations.py: 기존 회귀 테스트의 설명 호출 모의 처리
- tests/test_locations.py, test_ai_design.py, test_db_first_browser.py: 기존 테스트의 실제 추가 네트워크 호출 차단
- tests/test_chat_browser_flow.py: 실제 브라우저에 성공한 문단 구성 결과가 표시되는 경로 검증

파일 삭제·DB 스키마 변경·실제 DB 수정은 없습니다. 기존 SQLite/SQLAlchemy 및 향후 Supabase 연결 방식은 그대로입니다. 변경된 내용은 주석으로 설명했습니다.

## 8. 검증 결과

최종 실행 결과는 아래에 기록합니다. 실제 Groq의 문단 계획 준수율·추가 응답 시간·사용량은 운영 API로 측정하지 않았습니다.

2026-11-13: 관련 12개 테스트 파일 143개 및 15개 하위 검증 통과. 실제 브라우저 성공 경로 검증 포함. 수정 Python 파일의 문법 확인도 통과했습니다. 기존 FastAPI TestClient/httpx 사용 중단 예정 경고 1건이 있으며 실패는 없습니다. 실제 Groq 호출과 운영 DB 수정은 수행하지 않았습니다.
