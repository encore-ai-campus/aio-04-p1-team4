# 백엔드·DB 연결 규격 초안

아래 URL/스키마는 프론트엔드용 제안이며 기존 백엔드에 이미 구현된 API를 의미하지 않습니다. 계약 합의 후 `api.js`와 `app.js`의 호출을 맞춥니다.

## 공통 조건

```json
{
  "budget": 5000,
  "remaining_minutes": 50,
  "distance_m": 500,
  "people": 1,
  "category": "전체",
  "origin": {"latitude": 37.0, "longitude": 127.0},
  "game": "제비뽑기",
  "context": "따뜻한 국물이 먹고 싶어요.",
  "participant_menus": []
}
```

좌표는 위치 권한 허용 후에만 설정하며 위 숫자는 예시입니다. 위치 없는 실 추천은 UI가 차단합니다. DB/AI는 백엔드에서 검증된 후보만 반환해야 합니다. 가격·영업정보를 프론트나 AI가 임의로 만들지 않습니다.

| 요청 | 추가 입력 | JSON 응답 |
| --- | --- | --- |
| POST `/api/menu-decisions` | `method`: `game` 또는 `ai` | `{ "menu": "김치찌개" }` |
| POST `/api/restaurants/search` | `menu` | `{ "restaurants": [...] }` |
| POST `/api/routes` | `origin`, `restaurant_id` | `{ "distance_m": 450, "walk_minutes": 7 }` |

식당 응답 예시:

```json
{"restaurants":[{"id":"restaurant-123","name":"점심식당","menu":"김치찌개","price":9000,"distance_m":450,"walk_minutes":7}]}
```

DB 식당 ID는 변경되지 않는 문자열로 반환합니다. UI는 opaque ID로 다룹니다. 후보 없음은 빈 배열. 가격/시간 미확인 값 처리 정책은 합의가 필요합니다. 입력 범위·좌표·메뉴 판매 여부·가격 최신성·영업 여부는 백엔드에서 재검증해야 합니다.

비정상 요청은 4xx, 서버 오류는 5xx와 JSON 메시지로 응답합니다. UI는 오류·15초 타임아웃을 표시하며 실패 시 데모 데이터로 자동 대체하지 않습니다. 인증 토큰/쿠키·CSRF·회원 저장 정책은 별도 합의 후 `api.js`에 구현합니다.

실제 지도 경로에는 좌표/geometry/도착예상시각 등 응답 확장이 필요합니다. 현재 UI의 경로 이미지는 실좌표 기반 지도가 아닙니다. 백엔드의 JSON 모델이 바뀌면 이 문서와 어댑터를 함께 수정하세요.


UI 03 추가: lunch_end_time은 24시간 HH:mm 문자열입니다. remaining_minutes는 오늘 Asia/Seoul 기준으로 계산하며 지난 종료 시각은 0입니다. 예산 1,000~100,000,000원, 기본 5,000원. 서버에서 재검증하세요.
