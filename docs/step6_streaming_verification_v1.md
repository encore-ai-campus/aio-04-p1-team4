# 6단계 스트리밍·스피너 검증 안내 v1

- 작성일: 2026-11-10
- 대상: 진행 이벤트, 캐시 재사용, 일부 실패, 중복 차단, 화면 취소

## 1. 자동 테스트

프로젝트 루트 `C:\TeamProject_1`에서 실행한다.

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_recommendations.py tests\test_place_details.py -v
```

전체 Python 회귀 테스트:

```powershell
.\.venv\Scripts\python.exe -m pytest -q
```

프론트엔드 테스트:

```powershell
node --test tests\chat-session-ui.test.cjs tests\groq-status.test.cjs tests\location.test.cjs tests\location-flow.test.cjs tests\restaurant-ui.test.cjs tests\map.test.cjs
```

## 2. 브라우저 직접 확인

```powershell
.\.venv\Scripts\python.exe -m uvicorn app.main:app --reload
```

1. `http://127.0.0.1:8000`을 열고 위치와 조건을 설정한다.
2. `이 메뉴 파는 식당 보여줘`라고 질문한다.
3. 채팅창에 스피너와 처리 단계가 차례로 바뀌는지 확인한다.
4. 상세수집이 필요하면 `(0/3)`, `(1/3)` 같은 진행률이 표시되는지 확인한다.
5. 완료되면 진행 메시지가 사라지고 최종 답변과 식당 결과가 표시되는지 확인한다.

## 3. Network 탭 확인

브라우저 개발자 도구에서 `/api/chat/stream` 요청을 선택한다.

- 메서드: `POST`
- Content-Type: `application/x-ndjson`
- Cache-Control: `no-store`
- `started`가 첫 이벤트인지 확인
- `completed` 또는 `failed`가 마지막 이벤트인지 확인
- `completed.data`에 기존 `/api/chat`과 같은 최종 결과가 있는지 확인

## 4. 캐시 재사용 확인

같은 위치와 메뉴로 식당 추천을 연속 요청한다.

- 첫 요청: 필요한 식당에 `collecting` 표시
- 다음 요청: 최신 저장정보에 `using_cache` 표시
- 두 번째 요청에서 동일 식당 상세페이지를 다시 열지 않는지 확인

기본 정상 캐시는 168시간, 실패 재시도는 60분이다. 테스트 목적으로 바꾸려면 `.env`에 값을 설정하고 서버를 다시 시작한다.

## 5. 취소와 중복 확인

- 수집 중 다른 화면으로 이동하면 이전 요청이 취소되고 새 화면에 실패 문구가 추가되지 않아야 한다.
- 처리 중에는 입력과 빠른 질문 버튼이 비활성화되어야 한다.
- 같은 세션에서 강제로 두 스트림을 동시에 요청하면 두 번째 요청은 HTTP 409를 반환해야 한다.
- 실패 이벤트 후 스피너와 `busy` 상태가 해제되어 다시 질문할 수 있어야 한다.

## 6. 현재 제한

실제 상세페이지 수집 속도와 성공 여부는 카카오 페이지 구조와 Playwright 환경에 영향을 받는다. 현재 구현은 단일 서버 프로세스용이며 Redis 작업 복구는 포함하지 않는다.

## 7. 작성 시점 검증 결과

- 전체 Python: `81 passed`, `1 skipped`, `36 subtests passed`
- 전체 프론트엔드: `34 passed`
- Python 구문, 환경설정 로딩과 Git 공백 검사: 통과
- Starlette `TestClient` 사용 중단 예정 경고 1개는 이번 기능 실패가 아니다.
- 실제 Groq·카카오 API 호출은 외부 사용량과 페이지 접근을 발생시키므로 자동 테스트에서 실행하지 않았다.
