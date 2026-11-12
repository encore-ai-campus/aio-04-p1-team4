# 6단계 채팅 스트리밍 설계 v1

- 작성일: 2026-11-10
- 관련 정책: `chatbot_policy_v4.md`

## 처리 구조

```text
브라우저 fetch(POST /api/chat/stream)
  -> FastAPI가 세션별 중복 요청 확인
  -> 작업 Task와 asyncio.Queue 생성
  -> services.chat()에 진행 콜백 전달
  -> 서비스/수집기가 Queue에 이벤트 추가
  -> StreamingResponse가 JSON 한 줄씩 전달
  -> completed 결과를 세션에 저장
  -> 브라우저가 최종 결과만 화면 상태에 적용
```

## JSON Lines 예시

```json
{"event":"started","message":"요청을 시작했어요."}
{"event":"interpreting","message":"질문을 이해하고 있어요."}
{"event":"collecting","message":"식당 상세정보를 수집하고 있어요 (1/3).","completed":1,"total":3}
{"event":"completed","message":"추천 결과가 준비됐어요.","data":{"text":"...","result":{}}}
```

각 줄은 독립된 JSON 객체다. 프론트엔드는 네트워크 청크가 JSON 중간에서 나뉘어도 버퍼에 합친 뒤 줄바꿈 단위로 해석한다.

## 주요 파일

- `app/api.py`: 스트리밍 엔드포인트, Queue, 세션 기록, 안전 오류
- `app/services.py`: 질문 해석·DB·검색·필터 단계 이벤트 생성
- `app/detail_collection.py`: 캐시 판정과 식당별 수집 진행률
- `app/config.py`: 정상 캐시와 실패 재시도 주기
- `frontend/app.js`: NDJSON 파서, 진행 상태, 요청 취소
- `frontend/styles.css`: 진행 스피너 애니메이션

## 일반 API 호환

`POST /api/chat`은 기존처럼 하나의 JSON 응답을 반환한다. 일반 API와 스트리밍 API 모두 같은 `services.chat()`과 같은 세션 기록 함수를 사용하므로 추천 결과가 달라지지 않는다.

## 취소와 오류

- 화면 이동: 브라우저 `AbortController.abort()`
- 클라이언트 연결 종료: 스트리밍 generator가 작업 Task 취소
- 외부 API 오류: 원문 대신 통제된 오류 코드와 안내를 `failed`로 전송
- 예상하지 못한 오류: `chat_stream_error`로 정리
- 성공하지 않은 요청: 대화 세션의 정상 턴으로 기록하지 않음

## 운영 전환

단일 프로세스 테스트에서는 `active_chat_streams` 집합으로 같은 세션의 중복 작업을 막는다. Supabase PostgreSQL 전환과는 별개이며, 다중 서버 또는 재시작 복구가 필요할 때 Redis 작업 상태와 분산 잠금으로 교체한다.
