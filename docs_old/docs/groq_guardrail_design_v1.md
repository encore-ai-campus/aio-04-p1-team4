# 4단계 Groq 가드레일 설계 v1

- 작성일: 2026-11-10
- 관련 정책: `chatbot_policy_v2.md`

## 처리 흐름

```text
사용자 질문
  -> 세션 쿠키로 최근 상태 조회
  -> 최근 10턴 + 현재 메뉴 + 최근 식당 ID/이름 구성
  -> Groq에 구조화 해석 요청
  -> Pydantic 스키마 및 허용 ID 검증
  -> 서버가 의도별 동작 수행
  -> 성공한 질문/응답과 상태를 세션에 저장
```

Groq는 실행 주체가 아니라 분류기다. 식당 조회나 조건 적용은 검증을 통과한 뒤 서버 코드가 수행한다.

## 주요 파일

- `app/prompts/system_v2.txt`: 역할, 허용 의도, 금지사항
- `app/prompts/examples_v2.json`: 의도별 입력·출력 예시
- `app/prompts/replies_v2.json`: 서버가 사용하는 안전 문구
- `app/chat_policy.py`: Pydantic 스키마와 문맥 메시지 생성
- `app/clients/groq.py`: Groq 호출, 응답 파싱, 1회 안전 재시도
- `app/services.py`: 검증된 의도별 서버 동작
- `app/chat_sessions.py`: 최근 10턴과 `pending_action` 보관
- `app/api.py`: 세션을 서비스에 전달하고 내부 메타데이터를 저장

## 구조화 응답

기본 필드는 다음과 같다.

- `intent`: 수행할 의도
- `menu_id`: 메뉴 대상이 명확할 때만 사용
- `restaurant_id`: 최근 식당 중 대상이 명확할 때만 사용
- `requested_detail`: 가격·주소·영업시간 등 요청 상세
- `condition_patch`: 변경할 조건 값
- `search_after_change`: 조건 변경 뒤 식당 검색까지 원하는지 여부
- `clarification`, `clarification_kind`: 추가 확인이 필요할 때 사용

서로 맞지 않는 조합은 스키마 검증에서 거부한다. 예를 들어 최근 추천 목록에 없는 식당 ID는 실행할 수 없다.

## 재시도 정책

- 재시도함: JSON 파싱 실패, 스키마 위반
- 재시도 횟수: 정확히 1회
- 재시도하지 않음: 인증 오류, 사용량 제한, HTTP 서버 오류, 시간 초과, 네트워크 오류, 응답 잘림
- 최종 형식 오류: 안전한 `clarify`로 전환

잘못된 Groq 원문을 두 번째 요청이나 사용자 응답에 넣지 않아 프롬프트 오염과 내부 정보 노출을 줄인다.

## 개인정보와 사실 정보 경계

- 세션 쿠키에는 UUID만 저장한다.
- Groq에는 최근 추천 대상 식별에 필요한 식당 ID와 이름만 전달한다.
- 가격과 영업 여부는 Groq가 추측하지 않는다.
- API 응답에 사용하는 사실 정보는 DB와 외부 API로 확인한 값이어야 한다.

## 다음 단계 연결점

5단계에서는 `ask_restaurant_detail`을 식당·메뉴·영업시간 테이블 조회에 연결한다. 조회 결과가 없으면 `가격 확인 불가`, `현재 영업 상태 확인 불가`처럼 누락을 명시하며 Groq의 추측으로 보완하지 않는다.
