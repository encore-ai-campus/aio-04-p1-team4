# 3단계 메모리 채팅 세션 검증 안내 v1

- 작성일: 2026-11-10
- 대상: 최근 10턴, 현재 추천 상태, HttpOnly 쿠키와 새로고침 복원

## 자동 테스트

프로젝트 루트 `C:\TeamProject_1`의 PowerShell에서 실행한다.

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_chat_sessions.py tests\test_recommendations.py -v
```

정상 결과는 17개 테스트 통과다. 세션 자체 테스트는 다음 명령으로 따로 실행할 수 있다.

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_chat_sessions.py -v
```

전체 Python 회귀 검증:

```powershell
.\.venv\Scripts\python.exe -m pytest -q
```

작성 시점 결과는 `62 passed, 1 skipped, 37 subtests passed`이다. Starlette TestClient 사용 중단 예정 경고 1개는 이번 기능 실패가 아니다.

프론트엔드 세션 복원과 기존 화면 회귀 검증:

```powershell
node --test tests\chat-session-ui.test.cjs tests\groq-status.test.cjs tests\location.test.cjs tests\location-flow.test.cjs tests\restaurant-ui.test.cjs tests\map.test.cjs
```

정상 결과는 `31 passed`이다.

## 브라우저 쿠키 확인

서버를 실행한다.

```powershell
.\.venv\Scripts\python.exe -m uvicorn app.main:app --reload
```

1. 브라우저에서 `http://127.0.0.1:8000`을 연다.
2. 위치를 설정하고 채팅 질문을 한 번 보낸다.
3. 개발자 도구의 Application 또는 저장소 탭에서 Cookies를 연다.
4. `lunchrun_session` 쿠키를 확인한다.
5. `HttpOnly`가 켜지고 `SameSite`가 `Lax`인지 확인한다.

쿠키 값은 UUID 형태여야 하며 질문·메뉴명·위치 정보가 들어 있으면 안 된다.

## 저장 상태 확인

채팅을 한 번 성공한 뒤 같은 브라우저에서 아래 주소를 연다.

```text
http://127.0.0.1:8000/api/chat/session
```

다음 항목을 확인한다.

- `exists: true`
- `turns`에 사용자 질문과 챗봇 답변이 한 쌍으로 존재
- `conditions`, `location`, `radius_m`이 질문 당시 값과 일치
- `selected_menu`가 있으면 ID와 이름 표시
- 식당 전체 정보 대신 `restaurant_ids`, `candidate_restaurant_ids`만 저장
- 응답 헤더 `Cache-Control: no-store`

## 새로고침 확인

1. 채팅 질문을 두세 번 보낸다.
2. 브라우저를 새로고침한다.
3. 최근 질문과 답변이 다시 표시되는지 확인한다.
4. 위치·예산·음식 종류·반경이 마지막 성공 채팅 당시 값으로 복원되는지 확인한다.
5. 선정 메뉴가 있었다면 다음 질문에서 해당 메뉴 ID가 다시 요청에 포함될 준비가 됐는지 Network 탭에서 확인한다.

## 세션 분리 확인

일반 브라우저와 시크릿 창에서 각각 질문을 보낸다. 두 창의 `lunchrun_session` 값이 다르고 대화 내용이 섞이지 않으면 정상이다.

## 서버 재시작 제한 확인

1. 채팅 후 서버를 완전히 종료한다.
2. 서버를 다시 실행한다.
3. `/api/chat/session`을 다시 확인한다.

쿠키가 남아 있어도 `exists: false`가 나오는 것이 현재 메모리 방식의 정상 동작이다. Redis 또는 영구 저장소를 연결하기 전에는 서버 재시작 후 대화를 복원하지 않는다.

## 직접 확인 체크리스트

- 최근 10턴만 남고 현재 조건과 메뉴 상태는 유지되는가?
- 잘못된 쿠키가 새 UUID4 쿠키로 교체되는가?
- 다른 브라우저의 대화가 섞이지 않는가?
- 새로고침 후 최근 대화와 조건이 복원되는가?
- 실패한 Groq·카카오 요청이 정상 대화 턴으로 저장되지 않는가?
- 서버 재시작 시 메모리 세션이 사라진다는 제한이 안내됐는가?
- 쿠키에 실제 질문·위치·식당 정보가 들어가지 않는가?
