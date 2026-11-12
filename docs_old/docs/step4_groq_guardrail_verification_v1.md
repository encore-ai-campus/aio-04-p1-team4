# 4단계 Groq 가드레일 검증 안내 v1

- 작성일: 2026-11-10
- 대상: 의도 분류, 최근 문맥, 대상 제한, 안전 재시도, 확인 대기

## 1. 자동 테스트

프로젝트 루트 `C:\TeamProject_1`의 PowerShell에서 실행한다.

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_chat_policy_v2.py tests\test_groq_context.py tests\test_groq_client.py -v
```

추천 동작과 세션 연결까지 확인하려면 다음을 실행한다.

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_recommendations.py tests\test_chat_sessions.py -v
```

전체 회귀 테스트:

```powershell
.\.venv\Scripts\python.exe -m pytest -q
node --test tests\chat-session-ui.test.cjs tests\groq-status.test.cjs tests\location.test.cjs tests\location-flow.test.cjs tests\restaurant-ui.test.cjs tests\map.test.cjs
```

## 2. 선택적인 실제 Groq 검증

`.env`에 유효한 `GROQ_API_KEY`가 있을 때만 실행한다. 무료 API 사용량을 소비할 수 있다.

```powershell
$env:LUNCHRUN_LIVE_GROQ = "1"
.\.venv\Scripts\python.exe -m pytest tests\test_guardrail_live.py -v
Remove-Item Env:LUNCHRUN_LIVE_GROQ
```

일반 자동 테스트는 Groq를 모의 처리하므로 인터넷 연결이나 API 사용량이 필요 없다.

## 3. 브라우저 직접 확인

서버 실행:

```powershell
.\.venv\Scripts\python.exe -m uvicorn app.main:app --reload
```

브라우저에서 `http://127.0.0.1:8000`을 열고 위치와 조건을 설정한 뒤 아래 순서로 질문한다.

1. `메뉴 추천해줘` → 메뉴와 적용 조건이 표시되는지 확인
2. `다른 메뉴 추천해줘` → 직전 메뉴와 다른 메뉴인지 확인
3. `이 메뉴 파는 식당 보여줘` → 같은 선택 메뉴로 식당을 조회하는지 확인
4. `반경을 줄여줘` → 원하는 반경을 묻는지 확인
5. `우주의 나이는?` → `메뉴 및 식당 선정에 맞는 대화를 입력해주세요.`가 표시되는지 확인

## 4. 세션 문맥 확인

질문을 보낸 브라우저에서 `http://127.0.0.1:8000/api/chat/session`을 연다.

- `turns`가 최근 10턴 이하인지 확인한다.
- 현재 `selected_menu`가 유지되는지 확인한다.
- 반경을 값 없이 변경했을 때 `pending_action.kind`가 `change_radius`인지 확인한다.
- 이후 정상 추천 질문이 성공하면 `pending_action`이 `null`로 바뀌는지 확인한다.
- 최근 식당은 전체 상세정보가 아니라 ID 목록으로 저장되는지 확인한다.

## 5. 기대되는 안전 동작

- Groq가 잘못된 JSON을 반환하면 한 번만 다시 요청한다.
- 두 번 모두 잘못되면 서버 오류나 원문 대신 확인 안내가 나온다.
- 최근 추천 목록에 없는 식당 ID는 후속 질문 대상으로 실행되지 않는다.
- 지원 범위 밖 질문이 현재 조건과 메뉴를 변경하지 않는다.
- API 키, 내부 프롬프트와 Groq의 잘못된 원문이 화면에 표시되지 않는다.

## 6. 현재 단계의 제한

식당 후속 질문의 대상 식별은 구현됐지만, 가격·주소·영업시간을 DB에서 읽어 답하는 실제 동작은 5단계 작업이다. 4단계에서 이 질문에 상세 사실 답변이 나오지 않는 것은 정상이다.

## 7. 작성 시점 검증 결과

- 4단계 핵심 Python 테스트: `31 passed`, `15 subtests passed`
- 전체 Python 회귀 테스트: `71 passed`, `1 skipped`, `36 subtests passed`
- 전체 프론트엔드 테스트: `31 passed`
- Python 구문 컴파일, v2 JSON 유효성, Git 공백 검사: 통과

Python 테스트의 Starlette `TestClient` 사용 중단 예정 경고 1개는 기존 테스트 도구의 호환성 안내이며 이번 기능 실패가 아니다. 실제 Groq API 호출은 사용량을 소비할 수 있어 자동으로 실행하지 않았다.
