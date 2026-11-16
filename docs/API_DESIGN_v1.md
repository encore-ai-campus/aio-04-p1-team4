# LunchRun API 설계서

| 항목 | 값 |
|---|---|
| 기준일 | 2026-11-16 |
| 서비스명 | LunchRun |
| 목적 | 위치와 식사 조건에 맞는 메뉴·식당을 조회하고, 채팅으로 조건 변경과 식당 관련 질문을 처리한다. |
| Base URL | 로컬 환경: `http://127.0.0.1:8000`. API 경로는 `/api`, `/map/api`를 사용한다. |
| 인증 방식 | 로그인 인증은 사용하지 않는다. 채팅 세션은 `lunchrun_session` 쿠키(UUID4, HttpOnly, SameSite=Lax, Path=/, 유효기간 86400초)로 식별한다. 게임 모임방은 `Authorization: Bearer <방 토큰>`으로 접근한다. |
| 데이터 형식 | 요청·응답: `application/json`. 채팅 스트림: `application/x-ndjson`(한 줄당 JSON 객체). |

현재 구현된 API를 기준으로 작성했으며, 요청·응답 예시에는 가상 데이터를 사용한다.

## 1. 공통 규칙

- Pydantic 요청 모델은 `extra="forbid"` 설정에 따라 정의되지 않은 필드를 거부한다. 도보 경로는 별도 검증을 사용하며, 게임 프록시는 요청 원문을 전달한다.
- `null`은 값이 없거나 확인되지 않은 상태다. 가격 0원이나 영업 종료로 해석하지 않는다.
- 영업 상태는 `Asia/Seoul` 시간대를 기준으로 판정하며, 확인 시각은 ISO 8601 형식으로 반환한다.
- 내부 식당 `id`와 카카오 장소 `kakao_id`는 별개이며 문자열로 처리한다. PostgreSQL의 `restaurant.id`는 UUID다.
- 추천·지도·게임의 식당 후보는 저장된 DB에서 조회한다. 위치 변경 시 식당 데이터를 새로 수집하지 않는다.
- 요청 본문 크기는 `Content-Length`로 검사한다. `MAX_REQUEST_BYTES`의 기본값은 65536바이트다.
- FastAPI 응답에는 `X-Request-ID`가 포함된다. 외부 서비스 오류에는 `X-Error-Code`, 요청 제한 시에는 `Retry-After`가 추가될 수 있다. 채팅 응답에는 `Cache-Control: no-store`를 설정한다.
- 채팅 요청은 세션별 분당 10회(`chat_requests_per_minute`), 일 100회(`chat_requests_per_day`)로 제한한다. 최근 대화 10턴은 프로세스 메모리에 저장되며 서버 재시작 또는 세션 만료 시 삭제된다.

## 2. 공통 요청 모델 (Pydantic)

요청 모델은 `app/schemas.py`에 정의되어 있다.

### 2.1 Coordinates: 위치 좌표

```python
class Coordinates(BaseModel):
    model_config = ConfigDict(extra="forbid")
    lat: float = Field(ge=-90, le=90, allow_inf_nan=False, strict=True)   # 필수
    lng: float = Field(ge=-180, le=180, allow_inf_nan=False, strict=True) # 필수
```

| 필드 | 타입 | 필수 | 제약·설명 |
|---|---|---|---|
| lat | number | Y | 위도 -90~90. NaN·무한대·범위 밖 거부 |
| lng | number | Y | 경도 -180~180. NaN·무한대·범위 밖 거부 |

### 2.2 SelectedLocation: 선택 위치

```python
class SelectedLocation(Coordinates):
    name: str = Field(min_length=1, max_length=200)                 # 필수
    address: str = Field(default="", max_length=500)                # 선택
    source: Literal["geolocation", "address", "place"]               # 필수
    accuracy: float | None = Field(default=None, ge=0, allow_inf_nan=False)  # 선택
```

| 필드 | 타입 | 필수 | 기본값·제약 |
|---|---|---|---|
| lat / lng | number | Y | 2.1과 동일 |
| name | string | Y | 1~200자 |
| address | string | N | 기본 `""`, 최대 500자 |
| source | enum | Y | `geolocation` / `address` / `place` |
| accuracy | number \| null | N | 기본 null, 0 이상(미터) |

### 2.3 Conditions: 식사 조건

```python
class Conditions(BaseModel):
    model_config = ConfigDict(extra="forbid")
    minutes: int = Field(default=30, ge=1, le=120)
    budget: int = Field(default=10000, ge=1000, le=100000)
    cuisine: FoodType = "전체"
```

| 필드 | 타입 | 필수 | 기본값·제약 |
|---|---|---|---|
| minutes | integer | N | 기본 30분, 1~120분. 추천 조건으로 사용하며 실제 소요시간과 다를 수 있음 |
| budget | integer | N | 기본 10000, 1000~100000원 |
| cuisine | enum | N | 기본 `전체`. 전체, 한식, 중식, 일식/회, 양식, 분식, 패스트푸드, 치킨, 도시락/구내식당, 뷔페식, 냉면, 고기, 카페/빵, 술집, 기타 |

채팅에서 조건을 변경할 때 사용하는 `ConditionPatch`의 `minutes` 범위는 10~120분이다.

### 2.4 RecommendationRequest: 추천·후보·주변 식당 조회

```python
class RecommendationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    location: SelectedLocation          # 필수 — 중첩 모델
    radius_m: int = Field(default=500, ge=50, le=500, strict=True)  # 선택
    conditions: Conditions = Field(default_factory=Conditions)      # 선택 — 중첩 모델
    menu_id: str | None = Field(default=None, max_length=40)        # 선택
```

| 필드 | 타입 | 필수 | 기본값·제약·설명 |
|---|---|---|---|
| location | SelectedLocation | Y | 기준 위치. 중첩 객체 |
| radius_m | integer | N | 기본 500, 50~500m, 정수만 허용(strict) |
| conditions | Conditions | N | 생략 시 2.3 기본 조건. 중첩 객체 |
| menu_id | string \| null | N | 최대 40자. 지정/현재 대표 메뉴 ID |

요청 예시:

```json
{
  "location": {"lat": 37.48, "lng": 126.88, "name": "예시 위치", "source": "place"},
  "radius_m": 500,
  "conditions": {"minutes": 30, "budget": 10000, "cuisine": "중식"},
  "menu_id": "noodle"
}
```

### 2.5 ChatRequest: 채팅 요청

```python
class ChatRequest(RecommendationRequest):
    message: str = Field(min_length=1, max_length=500)
```

| 필드 | 타입 | 필수 | 제약·설명 |
|---|---|---|---|
| message | string | Y(채팅만) | 입력 원문 1~500자를 검증한 뒤, 서비스에 전달할 때 앞뒤 공백을 제거(strip) |

```json
{"location":{"lat":37.48,"lng":126.88,"name":"예시 위치","source":"place"},"radius_m":500,"conditions":{"minutes":30,"budget":10000,"cuisine":"중식"},"menu_id":"noodle","message":"첫 번째 식당 가격은?"}
```

### 2.6 LocationSearchRequest: 위치 검색

```python
class LocationSearchRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    query: str = Field(min_length=1, max_length=100)
    kind: Literal["address", "place"] = "place"
```

| 필드 | 타입 | 필수 | 기본값·제약 |
|---|---|---|---|
| query | string | Y | 입력 원문 1~100자를 검증한 뒤 앞뒤 공백 제거. 공백만 입력하면 거부 |
| kind | enum | N | 기본 `place`, `address`도 허용 |

## 3. 공통 응답 모델

응답 필드는 실제 반환 값을 기준으로 정리했다. Swagger에 표시되지 않는 필드가 포함되어 있으며, 필수로 명시하지 않은 필드는 응답에 따라 생략될 수 있다.

### 3.1 MenuCandidate: 대표 메뉴 후보

| 필드 | 타입 | 설명 |
|---|---|---|
| id / name / cuisine | string | 대표 메뉴 ID·이름·분류 |
| search_keyword / description | string | 후보 검색어·메뉴 안내 |
| source | string | 현재 `database` |
| price_verified | boolean | 연결 후보들의 가격이 모두 확인됐는지 |
| verified_price / verified_price_max | integer \| null | 확인 가격의 최소/최대. 전부 없으면 null |
| price_hint | null | 호환용. 실제 예산 판정에 사용하지 않음 |
| nearby_restaurant_count | integer | 조건에 맞는 중복 없는 식당 수 |
| serving_status / serving_unverified | string / boolean | 인분 판정에 사용하지 않는 호환 필드 |
| warnings | string[] | 누락·확인 필요 안내 |
| emoji / catalog_demo / price | string / boolean / integer \| null | 추천 응답에 추가되는 화면 호환 필드 |

### 3.2 RestaurantRecommendation: 추천 식당·상품

| 필드 | 타입 | 설명 |
|---|---|---|
| id | string | 내부 식당 ID. PostgreSQL에서는 UUID |
| kakao_id | string \| null | 외부 카카오 장소 ID |
| name / category / address | string \| null | 이름·분류·주소 |
| lat / lng | number | 식당 좌표 |
| place_url | string \| null | 상세 페이지 링크 |
| distance_m | integer | 출발점과 직선거리(m). 도보거리 아님 |
| menu_id / menu_name / product_id | string / string / integer | 대표 메뉴 ID·실제 상품명·menu 행 ID |
| price / price_status | integer \| null / enum | 원화 표시가격, `known`/`missing`/`variable` |
| menu_verified | boolean | 연결된 실제 상품 존재 |
| open_status | enum | 목록은 `open`/`unknown`. 상세는 `closed`도 가능 |
| recommendation_kind / source | string | `recommendation` / `database` |
| serving_status / serving_unverified / availability_status | 호환 필드 | 인분·품절 필터로 사용하지 않음 |
| warnings | string[] | 가격 확인 불가·시간 미기재·휴무 확인 안내 |
| menu_verified_at | datetime \| null | 상품 확인 시각(ISO 8601) |

### 3.3 RecommendationResult: 추천 결과

| 필드 | 타입 | 설명 |
|---|---|---|
| demo / menu_catalog_demo / constraints_verified | boolean | 현재 `false`. 가격·영업시간 등의 확인 범위는 `verified_fields`와 `unverified_fields` 참조 |
| source | string | `database` |
| menus | MenuCandidate[] | 조건 후보 |
| menu | MenuCandidate \| null | 선정 메뉴. 후보 없음이면 null |
| restaurants | RestaurantRecommendation[] | 식당당 상품 1개, 최대 3곳. 영업 확인 식당을 우선하며 각 그룹 내 거리순 정렬 |
| candidate_restaurants | array | 호환용 빈 배열. 확인 필요 식당도 restaurants에 포함 |
| message | string | 결과 안내 |
| has_more | boolean | 현재 false. 페이지 이동 기능 없음 |
| verified_fields / unverified_fields | string[] | 확인 범위 안내 |
| location / radius_m | SelectedLocation / integer | 요청에 사용한 위치·반경 |

## 4. 엔드포인트 정의

### 4.1 상태 API

| 기능           | Method | URL                  | 설명                                      |
| ------------ | ------ | -------------------- | --------------------------------------- |
| 프로세스 생존 확인   | GET    | `/api/health`        | HTTP 서버 응답 확인         |
| 준비 상태 확인     | GET    | `/api/readiness`     | DB·메뉴 카탈로그·필수 설정을 외부 API 호출 없이 확인       |
| Gemini 연결 확인 | GET    | `/api/gemini/status` | 모델 목록 조회로 API 키·모델 접근 상태 확인 |

### 4.2 메뉴·추천 API

| 기능 | Method | URL | 설명 |
|---|---|---|---|
| 메뉴 후보 목록 | POST | `/api/menus/candidates` | 조건에 맞는 대표 메뉴 후보만 반환. 식당 검색·AI 호출 없음 |
| 메뉴 추첨 | POST | `/api/menus/draw` | 조건에 맞는 메뉴 하나를 무작위 선정. 식당 목록 없음 |
| 식당 추천 | POST | `/api/recommendations` | 선정 메뉴를 파는 저장 식당 최대 3곳 반환 |

세 경로 모두 Body는 `RecommendationRequest`(2.4)다.

### 4.3 AI 채팅 API

| 기능 | Method | URL | 설명 |
|---|---|---|---|
| 대화(단일 JSON) | POST | `/api/chat` | 질문 해석·DB 조회·답변 생성·세션 저장 |
| 대화(스트림) | POST | `/api/chat/stream` | 채팅 처리 과정과 최종 결과를 NDJSON으로 반환 |
| 세션 복원 | GET | `/api/chat/session` | 쿠키 세션의 최근 대화·조건·표시 식당 복원 |

### 4.4 위치 API

| 기능 | Method | URL | 설명 |
|---|---|---|---|
| 주소/장소 검색 | POST | `/api/locations/search` | 카카오 로컬 API로 검색. 검색어는 요청 본문으로 전달 |
| 좌표→주소 | POST | `/api/locations/reverse` | Geolocation 좌표를 도로명 주소로 변환 |

### 4.5 지도 API

| 기능 | Method | URL | 설명 |
|---|---|---|---|
| 상품명 검색 | GET | `/map/api/menu-search` | DB 상품 부분 검색, 최대 100건 |
| 식당 상세 | GET | `/map/api/restaurants/{restaurant_id}` | 저장된 메뉴·영업시간·영업 상태 |
| 주변 식당 | POST | `/map/api/nearby` | 추천과 동일한 DB 조건 판정의 지도용 조회 |
| 도보 경로 | POST | `/map/api/walking-route` | 서버가 카카오 도보 길찾기 API를 대신 호출(REST 키 보호) |

### 4.6 화면·설정·정적 경로

| Method | URL | 입력 | 출력 |
|---|---|---|---|
| GET | `/` | 없음 | 홈 HTML |
| GET | `/ai`, `/budget`, `/time`, `/distance`, `/people`, `/group-input`, `/play`, `/result` | 없음 | 같은 홈 HTML 셸. pathname으로 화면 구분 |
| GET | `/conditions` | 없음 | 307 → `/` |
| GET | `/restaurants`, `/route` | 없음 | 307 → `/map/` |
| GET | `/config.json` | 없음 | `{"apiBase":""}`, no-store |
| GET | `/api/public-config` | 없음 | `{"kakaoJavascriptKey":"공개 JS 키"}`. REST/Gemini 키는 반환하지 않음 |
| GET | `/map` | 없음 | 307 → `/map/` |
| GET | `/map/` | 없음 | 지도 HTML |
| GET | `/map/config.json` | 없음 | `{"javascriptKey":"공개 JS 키"}`, no-store |
| GET | `/map/{filename}` | 파일명 | 허용 html/css/js만. 없으면 404 |
| GET/HEAD | `/static/{path}`, `/` 아래 정적 파일 | 상대 경로 | 파일. 없으면 404 |
| GET | `/docs`, `/redoc`, `/openapi.json` | 없음 | Swagger / ReDoc / 명세 JSON |

### 4.7 게임 프록시 및 Node API

| 기능 | Method | URL | 설명 |
|---|---|---|---|
| 게임 화면 프록시 | GET | `/games` | query 유지, 307 → `/games/` |
| 게임 전체 프록시 | GET, POST | `/games/`, `/games/{path:path}` | 요청을 Node 서버로 원문 전달. 연결 실패 502 |

게임 프록시의 연결 대상은 `games/app.py`의 `NODE_ORIGIN`에 설정된 `https://lunchrun-games.onrender.com`이다. 로컬 Node 서버의 기본 포트는 4174이며, 연결 대상을 바꾸려면 `NODE_ORIGIN`을 수정해야 한다. 주 앱의 경로는 `/games`, `games.app`을 독립 실행할 때의 경로는 `/game`이다.

아래 표는 Node 서버의 경로다. FastAPI를 통해 호출할 때는 `/games`를 앞에 붙인다.

| Method | Node 경로 | 입력 | 성공 출력 |
|---|---|---|---|
| GET | `/api/network` | 없음 | `publicUrl`/`localUrl`/`phoneNote` |
| POST | `/api/rooms` | `nickname`, 선택 `title`, `filters` | 201 `{"code","token"}` |
| POST | `/api/rooms/{code}/join` | `nickname` | 200 `{"code","token"}` |
| GET | `/api/rooms/{code}` | 방 토큰 | RoomView |
| POST | `/api/rooms/{code}/start` | `round`, 방장 토큰 | `{"ok":true}` |
| POST | `/api/rooms/{code}/select` | `round`, `choices`(string[]), 참여자 토큰 | `{"ok":true}` |
| POST | `/api/rooms/{code}/revote` | `round`, 방장 토큰 | `{"ok":true}` |
| POST | `/api/rooms/{code}/reset` | `round`, 방장 토큰 | `{"ok":true}` |
| POST | `/api/rooms/{code}/remove` | `round`, `id`(참여자), 방장 토큰 | `{"ok":true}` |
| POST | `/api/rooms/{code}/draw` | `round`, 방장 토큰 | `{"targetId","endsAt"}` |
| GET | `/api/rooms/{code}/qr.svg` | 방코드 | `image/svg+xml`. 생성 불가 503 |
| POST | `/api/menus/candidates`, `/api/recommendations`, `/api/locations/search`, `/api/locations/reverse` | 대응 백엔드 입력 | 백엔드 JSON 전달. 실패를 게임 502 오류로 변환 |

POST 요청은 같은 출처에서만 허용하며 `Origin`을 검사한다. IP당 분당 180회, 본문 크기 16384바이트로 제한한다. 오류는 `{"error":"문구"}`로 반환하며, 방 접근 토큰은 `Authorization: Bearer <token>`으로 전달한다.

`filters`는 필수 `origin`(출발 좌표, `[위도, 경도]`), `selectedLocation`(위치), `budget`(원), `time`(분), `distance`(m), `categories`(음식 종류 배열), 선택적 `lunchDeadline`(epoch ms)/`location`(표시명)을 사용한다. `selectedLocation`에 좌표가 있어도 `origin`은 별도로 전달해야 한다. 백엔드 요청으로의 변환은 `games/dist/backend.mjs`의 `gameRequest`에서 처리한다.

방 생성 예시(로컬 Node 경로; FastAPI 경유 시 `/games` 접두사):

```http
POST /api/rooms
Content-Type: application/json
```

```json
{"nickname":"참여자","title":"오늘 점심","filters":{"origin":[37.48,126.88],"selectedLocation":{"lat":37.48,"lng":126.88,"name":"예시 위치","source":"place"},"budget":10000,"time":30,"distance":500,"categories":["중식"]}}
```

생성 응답 예: `{"code":"123456","token":"발급된_방_토큰"}`. 이후 방 조회와 동작 요청에는 발급된 토큰을 `Authorization: Bearer <token>`으로 전달한다.

## 5. 기능별 요청·응답 상세

### 5.1 GET /api/health

- 입력: 없음.
- 출력 200: `{"status":"ok"}`.

### 5.2 GET /api/readiness

| 입력 위치 | 필드 | 타입 | 필수 | 기본값 | 설명 |
|---|---|---|---|---|---|
| Query | refresh | boolean | N | false | true면 30초 서버 캐시를 건너뜀 |

- 출력 200 `ready` / 503 `not_ready`. 필드: `status`(string), `database_backend`(string), `recommendation_source`(`database`), `optional_checks`(string[]), `checks`(object).
- `checks`: `database`, `menu_catalog`, `menu_catalog_count`, `playwright_chromium`, `kakao_configured`, `gemini_configured` (모두 boolean/integer). Chromium은 `optional_checks`에 포함되며 필수 준비 조건이 아니다.
- 외부 API를 호출하지 않는다. `Cache-Control: no-store`.

### 5.3 GET /api/gemini/status

| 입력 위치 | 필드 | 타입 | 필수 | 기본값 | 설명 |
|---|---|---|---|---|---|
| Query | refresh | boolean | N | false | true면 5초 캐시, 아니면 60초 캐시 |

- 모델 목록을 조회해 API 키와 모델 접근 상태를 확인한다. 답변 생성 여부는 검사하지 않는다.
- 출력 200: `status`(`connected`/`disconnected`/`unknown`), `code`(string), `message`(string), `checked_at`(UTC ISO datetime), `cached`(boolean). 연결 여부는 HTTP 상태가 아닌 `status` 필드로 판단한다. `no-store`.

### 5.4 POST /api/menus/candidates

- 입력 Body: `RecommendationRequest`. 이 경로에서는 `menu_id`를 사용하지 않는다.
- 출력 200:

| 필드 | 타입 | 설명 |
|---|---|---|
| menus | MenuCandidate[] | 조건 후보 목록 |
| message | string | 결과 안내 |
| location | SelectedLocation | 요청한 위치 |
| radius_m | integer | 요청한 반경 |

메뉴 후보 목록만 반환하며, 선택된 메뉴(`menu`)와 식당 목록은 포함하지 않는다. 입력 오류는 422다.

### 5.5 POST /api/menus/draw

- 입력 Body: `RecommendationRequest`. 이 경로에서는 `menu_id`를 사용하지 않는다.
- 출력 200: `RecommendationResult`. `menu`에 추첨된 메뉴 1개를 반환하며 `restaurants`는 빈 배열이다. 후보가 없으면 `menu=null`, 빈 목록과 안내 문구를 반환한다. 실제 상품이 연결된 메뉴만 추첨 대상에 포함한다. 입력 오류는 422다.

### 5.6 POST /api/recommendations

- 입력 Body: `RecommendationRequest`. `menu_id`가 있으면 해당 후보 선택, 없으면 무작위 메뉴 선택.
- 출력 200: `RecommendationResult`. 식당을 최대 3곳 반환한다. 가격·영업시간이 확인되지 않은 식당은 `warnings`와 함께 포함할 수 있다. 휴무·폐업·영업시간 외·예산 초과가 확인된 항목은 제외하며, 인분과 품절 여부는 판정하지 않는다. 후보가 없어도 200을 반환한다. 입력 오류는 422다.

식당 항목 예시(일부 필드 발췌):

```json
{"id":"00000000-0000-4000-8000-000000000001","kakao_id":"123456","name":"예시 중식당","menu_id":"noodle","menu_name":"짜장면","product_id":1,"price":8000,"price_status":"known","distance_m":120,"open_status":"open","warnings":[]}
```

### 5.7 POST /api/chat

- 입력 Body: `ChatRequest` + `lunchrun_session` 쿠키. Gemini가 질문을 해석하고 서버가 DB 조회와 조건 변경을 처리한 뒤, 답변을 구성해 세션에 저장한다.
- 성공 200. 입력 422, 요청 제한 429, 모델 해석 실패 502/503/504. 설명 생성만 실패하면 확보한 결과를 보존해 200 `server_fallback`으로 반환한다.

출력 필드:

| 필드 | 타입 | 필수 | 설명 |
|---|---|---|---|
| text | string | Y | 최종 표시 답변 |
| suggested_patch | object \| null | Y | 이전 호환 필드. 현재는 `applied_patch`로 즉시 적용 |
| result | RecommendationResult \| null | Y | 추천 결과. 상세/안내 질문은 null 가능 |
| applied_patch | object | N | 실제 바뀐 `budget`/`cuisine`/`radius_m`/`minutes` |
| search_performed | boolean | N | 조건 변경과 식당 조회를 함께 했는지 |
| menu_options | `{id,name}[]` | N | 후보 목록 요청, 최대 3개 |
| restaurant_detail | object | N | 식당 후속 질문에 대한 상세 정보 |
| restaurant_guidance | boolean | N | 선택 메뉴로 식당 찾기를 안내할지 |
| answer_source | enum | Y | `gemini` / `server_fallback` / `server` |
| narration | object | Y | `status`, 선택적 `reason`/`elapsed_ms`/`usage` |
| location / radius_m / conditions | 공통 모델 | Y | 실제 적용 후 값 |
| session_version | integer | Y | 저장 후 세션 변경 번호 |

`restaurant_detail`은 `restaurant_id`/`restaurant_name`/`requested_detail`(`price`,`hours`,`address`,`menu`,`reason`)/`place_url` 및 종류별 `product_id`/`menu_name`/`price`, `address`, `open_status`/`holiday_unknown`, `menus`를 가질 수 있다. 조회 결과에 따라 일부 필드가 생략될 수 있다.

가격 질문에는 앞서 표시한 상품의 금액을 사용하며, 주소와 현재 영업 상태는 DB에서 다시 조회한다. 식당을 특정할 수 없는 질문에는 대상 확인을 요청한다.

`narration.status`는 `success`/`fallback`/`skipped`다. `elapsed_ms`는 추가 설명 생성에 걸린 시간이다. `usage`는 `prompt_tokens`/`completion_tokens`/`total_tokens` 등 수집된 사용량을 포함하며, 없으면 null이다. Gemini는 서버가 확정한 사실 문장을 유지하고 추가 설명을 구성한다.

조건 변경 시 변경 전후 값과 새 메뉴를 안내한다. 반경 증감은 50m 단위로 처리하고 50~500m 범위로 제한하며, 상·하한에 도달하면 실제 변경량을 안내한다. 후보가 없어도 변경된 조건은 유지한다.

추가 설명 비활성화 상태의 가격 후속 질문 200 응답 예시:

```json
{
  "text": "예시 중식당의 짜장면 가격은 8,000원입니다. 예산 이내 (앞서 표시한 가격 기준)",
  "suggested_patch": null,
  "result": null,
  "restaurant_detail": {
    "restaurant_id": "00000000-0000-4000-8000-000000000001",
    "restaurant_name": "예시 중식당",
    "requested_detail": "price",
    "product_id": 1,
    "menu_name": "짜장면",
    "price": 8000
  },
  "restaurant_guidance": true,
  "answer_source": "server",
  "narration": {"status": "skipped", "reason": "disabled"},
  "location": {"lat": 37.48, "lng": 126.88, "name": "예시 위치", "source": "place"},
  "radius_m": 500,
  "conditions": {"minutes": 30, "budget": 10000, "cuisine": "중식"},
  "session_version": 3
}
```

### 5.8 POST /api/chat/stream

- 입력은 `/api/chat`과 동일. 응답 시작 전 중복 스트림 409·요청 제한 429·입력 422 가능.
- 시작 후 HTTP 200 `application/x-ndjson`. 한 줄당 JSON 객체. `Cache-Control: no-store`, `X-Accel-Buffering: no`, 신규 세션이면 `Set-Cookie`.
- 같은 세션의 스트림은 한 개만 허용하며 연결 종료 시 실행 작업을 취소한다.

이벤트:

| 이벤트 | 주요 필드 | 의미 |
|---|---|---|
| `started` | event, message | 연결 시작 |
| `interpreting` | event, message | 질문 해석 |
| `checking_database` | event, message | DB 확인 |
| `searching` | event, message | DB 식당 목록 조회 |
| `filtering` | event, message | 조건 판정 완료 |
| `generating_answer` | event, message | 문단 구성 |
| `completed` | event, message, data | `data`는 `/api/chat` 최종 출력과 동일 |
| `failed` | event, message, code | 시작 후 오류. HTTP 200이어도 실패 이벤트 |

```text
{"event":"started","message":"요청을 시작하고 있어요."}
{"event":"interpreting","message":"질문을 이해하고 있어요."}
{"event":"completed","message":"추천 결과가 준비됐어요.","data":{"text":"예시 답변","result":null}}
```

예시의 `data`는 축약했다. 실행 과정에 따라 일부 이벤트만 발생할 수 있다. 응답은 처리 단계별 이벤트와 최종 결과로 구성되며 토큰 단위로 전송하지 않는다.

### 5.9 GET /api/chat/session

- Body와 Query는 사용하지 않는다. 기존 세션 쿠키를 사용하며, 쿠키가 없으면 새로 발급한다.
- 응답 200 `no-store`. 상태가 없으면 `{"exists":false,"turns":[]}`만 반환한다.

상태가 있을 때 출력:

| 필드 | 타입 | 설명 |
|---|---|---|
| exists | boolean | true |
| turns | array | 최대 10턴: `user_message`/`assistant_message`/`created_at` |
| conditions / location / radius_m | 공통 모델 \| null | 마지막 상태 |
| selected_menu | object \| null | `id`/`name`/`cuisine`/`description`/`emoji`/`source=session` |
| restaurant_guidance | boolean | 선택 메뉴와 마지막 의도 기준 |
| displayed_restaurants | array | 순서대로 `restaurant_id`/`name`/`product_id`/`menu_id`/`menu_name`/`price`, 최대 3개 |
| last_recommendation_kind | `menu`/`restaurant` \| null | 마지막 추천 종류 |
| restaurant_ids / candidate_restaurant_ids | string[] | 호환용 식당 ID 목록 |
| pending_action | object \| null | `kind`/`original_message`, 선택적 `current_value`/`restaurant_ids` |
| last_intent / version | string \| null / integer | 의도·세션 변경 번호 |

`pending_action.kind`는 `change_radius`/`change_budget`/`select_restaurant`/`unsupported_input`.

### 5.10 POST /api/locations/search

| 필드 | 타입 | 필수 | 설명 |
|---|---|---|---|
| query | string | Y | 입력 원문 1~100자를 검증한 뒤 앞뒤 공백 제거. 공백만 입력하면 거부 |
| kind | enum | N | 기본 `place`, `address`도 허용 |

- 출력 200: `items`(SelectedLocation[]), `has_more`(boolean). `items.source`는 `place`/`address`.
- 입력 422, 카카오 API 오류는 HTTP 상태와 `X-Error-Code`로 전달한다.

```json
{"query":"가산디지털단지역","kind":"place"}
```

```json
{"items":[{"lat":37.481,"lng":126.882,"name":"예시 장소","address":"예시 주소","source":"place","accuracy":null}],"has_more":false}
```

### 5.11 POST /api/locations/reverse

- 입력 Body: `Coordinates`(lat/lng만).
- 출력 200: `{"address":"예시 도로명 주소"}` 또는 `{"address":null}`. 주소 없음과 외부 오류를 구분한다. 입력 422, 외부 오류는 502/503/504 등 코드에 따라 다르다.

### 5.12 GET /map/api/menu-search

| 입력 위치 | 필드 | 타입 | 필수 | 설명 |
|---|---|---|---|---|
| Query | query | string | Y | 앞뒤 공백 제거 후 1~100자. 누락·빈 문자열·길이 초과 시 422 |

- 요청 예: `GET /map/api/menu-search?query=짜장면`
- 출력 200: `has_more`(boolean), `items[{restaurant_id,restaurant_name,address,place_url,menu_name,price,price_status}]`. 최대 100개이며 101번째가 있으면 `has_more=true`. 다음 페이지 파라미터는 없다. 상품명 부분 검색이며 반경·가격·영업 필터를 적용한 추천과 다르다.

### 5.13 GET /map/api/restaurants/{restaurant_id}

- Path `restaurant_id`: string, 필수, 내부 ID 사용. PostgreSQL은 UUID 형식을 검사하며 잘못된 ID/없는 식당 모두 404.

| 출력 필드 | 타입 | 설명 |
|---|---|---|
| id / name / place_url | string \| null | 식당 식별·링크 |
| open_status | `open`/`closed`/`unknown` | 현재 한국 시간 계산 |
| holiday_unknown | boolean | 영업 구간 안이지만 휴무 여부 미확인 |
| checked_at | datetime \| null | 시간표/상세 마지막 성공 시각 |
| menus | array | `name`, `price`(integer/null), `price_status` |
| business_hours | array | `day`(월0~일6), `holiday`(boolean/null), `start`/`end`(HH:mm/null), `next_day`(boolean), `last_order`(HH:mm/null) |

영업시간은 요일과 `sequence` 순으로 반환한다. 브레이크 타임이 있으면 같은 요일의 영업시간을 여러 구간으로 나누어 표시한다. 상세 메뉴에는 추천 조건에서 제외된 상품도 포함될 수 있다.

### 5.14 POST /map/api/nearby

- 입력 Body: `RecommendationRequest`. `menu_id`가 있으면 해당 상품으로 제한. 없으면 특정 메뉴를 무작위 선정하지 않고 조건 상품들에서 식당 목록을 생성한다.
- 출력 200: `restaurants`(RestaurantRecommendation[]), `candidate_restaurants`([]), `has_more`(false), `source`(`database`), `message`(string). 같은 위치·조건·`menu_id`라면 `/api/recommendations`와 공통 필터·정렬을 사용한다. 입력 오류는 422다.

### 5.15 POST /map/api/walking-route

| 필드 | 타입 | 필수 | 설명 |
|---|---|---|---|
| origin | object | Y | 출발 `lat`/`lng`. 유한 숫자 및 위경도 범위 검사 |
| destination | object | Y | 도착 `lat`/`lng`. 같은 검사 |

```json
{"origin":{"lat":37.48,"lng":126.88},"destination":{"lat":37.481,"lng":126.882}}
```

- 출력 200: `distance`(number, m), `duration`(number, 초), `paths`(경로 구간 배열), `steps`(string[] 안내). 각 경로 점은 `[lng,lat]` 순서로 요청 객체와 다르다. 같은 지점은 거리/시간 0과 빈 경로일 수 있다.
- 오류: 잘못된 좌표 400, 경로 없음 422, 외부 형식 문제 502, 키·권한·연결·한도 등 503. 업무 오류는 `{"error":"안내"}`.
- `Origin` 헤더가 있고 현재 서버와 다르면 403 detail 오류다. JSON 객체가 아닌 Body는 모델 검증 422 가능.
- 도보 경로 API를 사용하려면 카카오 계정에 해당 API의 사용 권한이 필요하다.

## 6. 표준 에러 응답

### 6.1 에러 본문 형식

| API 계열 | 에러 본문 | 비고 |
|---|---|---|
| FastAPI 일반 | `{"detail":"안내 문구"}` | HTTPException·검증 오류 |
| FastAPI 모델 검증 422 | `{"detail":[{loc,type,msg,...}]}` | Pydantic 검증 오류 배열 |
| 도보 경로 | `{"error":"안내 문구"}` | `walk_routes.RouteError` |
| Node 게임 | `{"error":"안내 문구"}` | `RoomError` 및 서버 공통 |
| 채팅 스트림 | `{"event":"failed","message":"...","code":"..."}` | HTTP 200 NDJSON 내부 이벤트 |

오류 본문은 API 계열별로 위 형식을 따른다. 진단 코드는 `X-Error-Code` 헤더 또는 스트림 `failed` 이벤트의 `code` 필드로 전달한다.

### 6.2 HTTP 상태 코드

| HTTP | 의미 |
|---|---|
| 200 | 정상. 후보 없음·설명 실패 시 서버 대체도 포함 |
| 201 | 게임 방 생성 성공 |
| 307 | 화면 주소 이동(`/conditions`→`/`, `/restaurants`·`/route`→`/map/`, `/games`→`/games/`) |
| 400 | 도보·게임 입력 형식 오류 |
| 401 | 게임 방 토큰 없음/불일치 |
| 403 | 게임 권한(방장 아님)·도보 Origin 불일치 |
| 404 | 식당·방·파일·API 없음 |
| 405 | 게임 서버 미지원 메서드 |
| 409 | 채팅 중복 스트림, 방 라운드/상태 충돌, 이미 시작된 방 |
| 410 | 게임 방 24시간 만료 |
| 413 | 본문 크기 제한(미들웨어 `max_request_bytes`, 게임 16384바이트) |
| 422 | Pydantic 필드 검증·도보 경로 검증 오류 |
| 429 | 채팅 세션별 레이트 리밋(분 10/일 100), 게임 IP 분당 180회, 방 수 상한 |
| 502 | 외부 API·게임 프록시 업스트림 오류 |
| 503 | 외부 서비스 미설정/불가, 준비 안 됨, QR 생성 불가 |
| 504 | 외부 API 시간 초과 |

### 6.3 에러 코드 (`X-Error-Code` 헤더 / 스트림 `code`)

| 코드 | 발생 API | 의미 |
|---|---|---|
| `kakao_timeout` | 위치, 추천, 채팅 | 카카오 검색 시간 초과(504) |
| `kakao_connection` | 위치, 추천, 채팅 | 카카오 연결 실패 |
| `kakao_auth` | 위치, 추천, 채팅 | 카카오 REST 키 인증 실패 |
| `kakao_service_disabled` | 위치 | 앱의 카카오맵·로컬 서비스 비활성화 |
| `kakao_permission` | 위치, 추천, 채팅 | 카카오 로컬 API 권한 없음 |
| `kakao_rate_limit` | 위치, 추천, 채팅 | 카카오 사용 한도(503) |
| `kakao_upstream` | 위치, 추천, 채팅 | 카카오 비정상 응답 |
| `kakao_response` | 위치 | 카카오 응답 형식 오류 |
| `gemini_config` | 채팅, 상태 | Gemini API 키 미설정(503) |
| `gemini_auth` | 채팅, 상태 | Gemini 키 인증 실패(503) |
| `gemini_permission` | 채팅, 상태 | 모델 사용 권한 없음(503) |
| `gemini_rate_limit` | 채팅, 상태 | Gemini 사용 한도(503) |
| `gemini_request` | 채팅 | Gemini 요청 옵션 오류(502) |
| `gemini_model` | 채팅, 상태 | 모델 이름/사용 가능 여부 문제(503) |
| `gemini_timeout` | 채팅 | Gemini 응답 시간 초과(504) |
| `gemini_connection` | 채팅 | Gemini 연결 실패(503) |
| `gemini_upstream` | 채팅 | Gemini 비정상 응답 |
| `gemini_response` | 채팅 | Gemini 응답 형식 오류 |
| `gemini_truncated` | 채팅 | 출력 토큰 한도로 응답 절단 |
| `gemini_policy` | 채팅 | 프롬프트·안내문 파일 설정 오류(503) |
| `chat_rate_limit` | 채팅 | 세션별 요청 제한(429, `Retry-After` 포함) |
| `chat_stream_error` | 채팅 스트림 | 스트림 내부 처리 실패(failed 이벤트) |

### 6.4 4xx·5xx 예외 상황별 처리 규칙

- **422 (입력 검증)**: `extra="forbid"` 위반·범위 밖 값·타입 불일치는 Pydantic이 `detail` 배열로 반환한다. 클라이언트는 `detail[0].msg` 또는 고정 문구로 안내한다. 추천 후보 없음은 오류가 아니라 200 + `menu=null`/빈 목록이다.
- **413**: 미들웨어가 `Content-Length` 초과를 외부 호출 전에 거부한다. 게임 서버는 본문을 16384바이트에서 끊는다.
- **429**: 채팅은 세션별 분/일 카운터 초과 시 `Retry-After` 헤더와 `chat_rate_limit` 코드. 스트림 시작 전 거부이므로 NDJSON이 아닌 일반 JSON 오류다.
- **409**: 같은 세션의 활성 스트림 중복, 게임 방의 `round` 불일치·상태 전이 위반(이미 시작/선택 불가 단계). 클라이언트는 방 상태를 재조회해 화면을 맞춘다.
- **410**: 게임 방 24시간 만료. 새 방 생성을 안내한다.
- **502/503/504 (외부 의존)**: 카카오·Gemini 오류는 내부 정보가 포함되지 않은 안내 문구와 코드로 반환한다. Gemini의 추가 설명 생성만 실패하면 기존 결과를 유지하고 HTTP 200과 `answer_source=server_fallback`을 반환한다. 질문 해석에 실패한 경우에는 오류로 처리한다. 도보 경로의 외부 오류는 `{"error": ...}` 형식이다.
- **스트림 내부 실패**: `/api/chat/stream`은 시작 후 예외를 `failed` 이벤트로 변환해 HTTP 200을 유지한다. 클라이언트는 `event==="failed"`를 오류로 처리해야 한다.
- **게임 프록시**: 업스트림 연결 실패는 502 `게임 서버에 연결할 수 없습니다...`. Node 측 업무 오류는 상태 코드와 `{"error"}` 본문을 그대로 전달한다.

## 7. 화면-API 연결표

| 화면·동작 | API |
|---|---|
| 위치 선택 | `/api/locations/search`, `/api/locations/reverse` |
| 홈·게임 후보/추첨 | `/api/menus/candidates`, `/api/menus/draw` |
| AI 대화/복원 | `/api/chat/stream`, `/api/chat/session` |
| 조건 변경 | 별도 PATCH API 없이 자연어 채팅 |
| 지도 조회 | `/map/api/nearby`, `/map/api/menu-search`, `/map/api/restaurants/{id}` |
| 식당 추천·도보 | `/api/recommendations`, `/map/api/walking-route` |
| 게임 방 | `/games/api/rooms` 및 하위 동작 |

## 8. API 연동 시 유의사항

- 요청 필드의 필수 여부, 생략 시 기본값, `null` 허용 여부와 값 범위를 구분해 처리한다.
- 추천 후보가 없는 경우는 HTTP 200과 `menu=null` 또는 빈 목록으로 반환되므로, 요청 실패와 구분해 안내한다.
- 채팅 스트림은 HTTP 200으로 시작한 뒤에도 `failed` 이벤트가 발생할 수 있다. HTTP 상태와 함께 이벤트 종류를 확인해 오류를 처리한다.
- 식당 상세 조회에는 내부 식당 ID를 사용한다. `kakao_id`와 혼용하지 않으며, `distance_m`의 직선거리와 도보 경로 API의 이동거리를 구분해 표시한다.
- 선택적 응답 필드는 생략될 수 있으므로, 필드 존재 여부와 `null`을 확인한 뒤 화면에 반영한다.
- `/games`는 원격 Node 서버로 연결되는 프록시다. 로컬 게임 서버 실행만으로 연결 대상이 바뀌지 않으므로, 연동 대상과 배포 버전을 확인한다.
