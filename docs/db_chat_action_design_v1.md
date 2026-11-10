# 5단계 DB 챗봇 실행 설계 v1

- 작성일: 2026-11-10
- DB 실행 정책 작성 당시 자료: [정책 v3 보관본](../docs_old/docs/chatbot_policy_v3.md)
- 현재 사용 안내: [프로젝트 README](../README.md), [현재 정책 v4](chatbot_policy_v4.md)

## 처리 흐름

```text
사용자 질문
  -> Groq가 구조화된 의도·메뉴 ID·식당 ID·상세 항목 반환
  -> Pydantic이 허용 메뉴와 최근 식당 대상 검증
  -> services.py가 의도별 DB 동작 선택
     ├─ 메뉴만 추천: menu_catalog.py 조회
     ├─ 식당 추천: 카카오 검색 -> restaurant 저장 -> 상세정보 필터
     └─ 후속 질문: 기존 Restaurant/Menu/BusinessHours 조회
  -> 서버가 검증된 값으로 응답 문장 생성
  -> 선택 메뉴와 최근 식당 ID를 채팅 세션에 저장
```

## 파일별 역할

- `app/menu_catalog.py`: 위치·반경·예산·음식 종류에 맞는 메뉴 후보 생성
- `app/services.py`: 의도별 실행, 카카오 검색, DB 후속 답변 구성
- `app/recommendation_engine.py`: 메뉴 별칭 비교와 현재 영업 여부 계산
- `app/database/models.py`: 메뉴 카탈로그, 식당, 메뉴, 영업시간 모델
- `app/chat_policy.py`: Groq 결과와 허용 메뉴·식당 ID 검증
- `app/chat_sessions.py`: 선택 메뉴와 최근 추천 식당 ID 보관

## 메뉴 후보 응답 구분

- `source=database`: 주변 식당의 확인 메뉴와 예산 이내 가격 근거가 있음
- `source=catalog`: 실제 주변 근거가 부족하여 카탈로그 기준으로 선정
- `price_verified=true`: `verified_price`가 실제 수집 가격임
- `price_verified=false`: `price_hint`는 후보 필터 기준일 뿐 실제 가격이 아님
- `menu_catalog_demo=false`: 서비스의 임시 Python 배열을 사용하지 않음

## 후속 질문 재사용

후속 질문은 세션의 `restaurant_ids` 또는 `candidate_restaurant_ids`에서 대상을 찾는다. 식당을 식별한 다음 같은 요청에서 새 카카오 검색이나 상세수집을 실행하지 않고 현재 DB 값을 읽는다. 따라서 답변 속도가 빠르고 외부 페이지 장애가 기존 정상 데이터를 지우지 않는다.

## 영업 상태 계산

`current_open_status()`는 현재 한국 요일과 시각을 일반 구간, 브레이크 타임으로 나뉜 복수 구간, 익일 종료 구간에 비교한다. 반환 상태는 `open`, `closed`, `unknown`이며 DB 테이블에는 현재 상태를 저장하지 않는다.

## PostgreSQL 전환 고려

조회와 저장은 SQLAlchemy ORM을 사용한다. SQLite 전용 SQL을 추천 서비스에 직접 넣지 않았으므로 Supabase PostgreSQL 이전 시에는 연결 URL, 드라이버와 마이그레이션을 중심으로 변경할 수 있다.
