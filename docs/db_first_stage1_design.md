# DB 중심 추천 전환: 1단계 구조 및 저장 규칙

작업 기준: `C:\temp_resolved`. 작성일: 2026-11-12.

## 이번 단계의 범위

현재 SQLAlchemy 모델과 제공된 CSV를 비교해 목표 스키마를 확정한다. 이 문서의 ERD는 목표 구조이며 아직 실제 모델·테이블을 변경한 결과가 아니다. 실제 Supabase 연결, 테이블 변경, 데이터 이전·적재는 다음 단계에서 실행한다.

SQLAlchemy는 SQLite 전용 문법이 아니다. 동일 모델을 PostgreSQL 방언으로 변환할 수 있다. SQLite PRAGMA는 SQLite 연결에서만 실행되므로 PostgreSQL SQL로 치환하지 않는다. 이번 코드 변경은 애플리케이션과 Alembic이 일반 PostgreSQL URI를 설치된 psycopg 3 드라이버로 일관되게 처리하도록 보완하는 것이다. 기존 SQLite 개발·테스트 경로는 유지한다.

## 자료와 확인된 데이터

- 기준 보고서: `C:\Users\Playdata\Desktop\단위프로젝트\LunchRun_시험용내부DB_1-6단계_구현_및_검증_보고서.pdf`.
- 메뉴 원본: `C:\Users\Playdata\Downloads\menu_example.before-kakao-ids.csv`.
- 매칭 자료: 같은 Downloads 폴더의 `confirmed_matches.csv`, `unresolved_restaurants.csv`, `resolution_report.csv`.
- 이전 읽기 분석 결과: 메뉴 원본 36,160행, 식당명·주소 조합 2,188개, 메뉴명과 양수 가격이 함께 있는 행 31,023개. 카카오 ID 없는 행 11,272개. 숫자는 원본 행 기준이며 최종 식당·상품 수가 아니다.
- 확정 매칭 264행은 고유 카카오 ID 254개로 연결된다. 검토 필요 197행, 미발견 123행은 확정 데이터와 분리한다.
- 제공 CSV에는 영업시간이 없다. 가격 출처에는 네이버가 포함되어 있어 카카오 식당 URL과 메뉴 출처 URL을 구분해야 한다.

## 현재 모델과 목표 구조

| 대상 | 현재 | 목표 |
|---|---|---|
| restaurant | 카카오 문자열 ID가 PK | 내부 UUID PK, nullable·unique 카카오 ID, 네이버 ID 별도 |
| menu | 식당 FK, 이름, 가격, 가격 상태 | 대표 메뉴 FK, 판매 상태, 출처와 확인 시각 추가 |
| menu_catalog | 분류·기준가격·설명·검색어 보유 | 대표명·정규화명·활성 여부 중심으로 축소 |
| menu_alias | 대표 메뉴별 별칭 | 유지 |
| business_hours | 요일별 영업 구간 | 유지, 출처와 확인 시각 추가 |
| place_detail_status | 식당별 수집 결과 | 유지, 정보 상태와 재수집 실패를 구분 |
| restaurant_match | 없음 | 원본 식당과 카카오 후보의 검토 이력 |

기존 식당 ID 변경은 URL 값만 바꾸는 작업이 아니다. 자식 FK, API 요청·응답, 세션의 식당 ID, 지도 선택 상태, 수집기의 카카오 ID 사용을 함께 이전해야 한다. 내부 식당 ID와 외부 카카오 ID를 혼용하지 않는다.

## 최종 ERD

```mermaid
erDiagram
    RESTAURANT ||--o{ MENU : sells
    MENU_CATALOG o|--o{ MENU : groups
    MENU_CATALOG ||--o{ MENU_ALIAS : aliases
    RESTAURANT ||--o{ BUSINESS_HOURS : opens
    RESTAURANT ||--o| PLACE_DETAIL_STATUS : tracks
    RESTAURANT o|--o{ RESTAURANT_MATCH : resolves
    RESTAURANT {
        uuid id PK
        text kakao_id UK "NULL 허용"
        text naver_id "NULL 허용"
        text name
        text cuisine
        text category_raw
        double latitude
        double longitude
        text address
        text place_url "NULL 허용"
        text operating_status
        timestamptz updated_at
    }
    MENU {
        bigint id PK
        uuid restaurant_id FK
        text menu_catalog_id FK "NULL 허용"
        text name
        text normalized_name
        integer price "NULL 허용"
        text price_status
        text availability_status
        text source_provider
        text source_url
        timestamptz verified_at "NULL 허용"
    }
    MENU_CATALOG {
        text id PK
        text name UK
        text normalized_name UK
        boolean active
    }
    MENU_ALIAS {
        bigint id PK
        text menu_catalog_id FK
        text name
        text normalized_name UK
    }
    BUSINESS_HOURS {
        bigint id PK
        uuid restaurant_id FK
        smallint day_of_week
        boolean holiday "NULL 허용"
        time start_time
        time end_time
        boolean ends_next_day
        integer sequence
        text source_url
        timestamptz verified_at
    }
    PLACE_DETAIL_STATUS {
        uuid restaurant_id PK,FK
        text menu_status
        text hours_status
        timestamptz last_attempt_at
        timestamptz menu_last_success_at
        timestamptz hours_last_success_at
        text last_error_code
    }
    RESTAURANT_MATCH {
        bigint id PK
        uuid restaurant_id FK "확정 전 NULL"
        text source_name
        text source_address
        text candidate_kakao_id
        text match_status
        text reason
        timestamptz reviewed_at
    }
```

`restaurant_match.restaurant_id`는 매칭 확정 전 NULL을 허용한다. BIGINT 식별자는 PostgreSQL IDENTITY로 자동 생성하고 UUID는 애플리케이션에서 생성한다. 시각은 TIMESTAMPTZ, 영업 시각은 TIME WITHOUT TIME ZONE으로 저장한다. 영업 시각 해석 기준은 Asia/Seoul이다.

## CSV 열 대응

| CSV | 저장 대상 | 규칙 |
|---|---|---|
| 카카오ID | restaurant.kakao_id | 문자열, 빈 값은 NULL, 확정 매칭만 보완 |
| 네이버장소ID | restaurant.naver_id | 문자열, 빈 값은 NULL |
| 지점명·주소 | restaurant.name·address | 원본 매칭 근거 보존 |
| 위도·경도 | restaurant.latitude·longitude | 숫자·범위 검사, 반경은 사용자 좌표로 계산 |
| 업태구분명·카카오분류(추가가게) | category_raw 및 cuisine | 원문 보존 후 서비스 분류로 명시적 매핑 |
| 메뉴명 | menu.name·normalized_name | 상품명 보존, 공백 정리만으로 의미가 다른 상품을 합치지 않음 |
| 가격(원)·가격원문 | price·price_status | 원문은 적재 검토 자료에 보존 |
| 품절표기 | availability_status | 명시적 품절만 sold_out, 빈 값은 unknown |
| 출처·출처링크 | source_provider·source_url | 카카오 place_url과 별도 저장 |
| 확인일시 | menu.verified_at | 출처·해당 행과 대응하는 유효 시각만 사용 |
| 메뉴설명·메뉴종류 | 원본 자료 | 초기 추천 필수 필드에서 제외 |

매칭 CSV의 distance_m은 매칭 근거 값이다. 사용자와 식당 사이 거리로 재사용하지 않는다. resolution_report는 전체 보고서이며 확정·미해결 파일과 합쳐 별도 식당으로 중복 등록하지 않는다.

## 저장·검증 규칙

1. 가격: known이면 양수 원화 정수가 필요하다. missing·variable이면 price=NULL이다. 빈 가격을 0원으로 변환하지 않는다. 예산 충족 후보는 known 및 price<=예산인 상품이다.
2. 판매: available·sold_out·unknown으로 구분한다. unknown은 판매 중 확인을 뜻하지 않는다. 초기 후보는 sold_out을 제외하되 unknown은 미확인 표시로 허용한다. 실제 판매 보장은 하지 않는다.
3. 상품: 세트·사이즈·인분은 보존한다. 초기에는 식당+정규화된 전체 상품명을 중복 키로 사용하고, 같은 키에 가격 충돌이 있으면 검토 대상으로 분리한다. 2인 세트 가격을 임의로 1인 가격으로 나누지 않는다. 1인 예산 추천용 식사인지 대표 메뉴 연결 시 검토한다.
4. 대표 메뉴: 메뉴 설명·기준가격·검색어는 후보 선정에서 사용하지 않는다. 실제 상품에 대표 메뉴 FK를 연결하고 후보 대표 메뉴는 중복 제거한다. 미연결 상품은 목록 조회 가능하지만 자동 메뉴 추첨에서는 제외한다.
5. 분류: 초기에는 restaurant.cuisine을 기준으로 통일한다. 메뉴별 음식 종류가 필요해지면 분류 관계를 추가 설계한다. '전체'는 검색 옵션이며 저장 분류가 아니다.
6. 영업: 요일은 0=월요일~6=일요일, 브레이크 타임은 실제 영업 구간을 분리한다. 익일 영업을 구분하고 open/closed는 조회 시 계산한다. 공휴일·임시휴무는 추정하지 않는다.
7. 수집: 실패해도 마지막 정상 메뉴·시간표는 삭제하지 않는다. 마지막 실패와 마지막 성공 시각을 함께 보관한다. 영업 검증은 사용 가능한 마지막 정상 시간표와 최신성 기준으로 판단하며, 최신성 유효기간은 적재 전 운영 설정으로 확정한다.
8. 출처 충돌: 더 최근의 동일 상품·동일 매장 확인값만 갱신 후보로 삼고, 날짜가 같거나 매장·상품 일치가 불확실하면 자동 덮어쓰지 않는다. 추정값을 실제 확인값으로 저장하지 않는다.
9. 운영: operating_status는 operating·closed·unknown. closed는 제외하고 unknown은 영업 여부를 시간표로 확인할 수 있어도 폐업 여부 미확인임을 보존한다.
10. 데이터 삭제: 식당 삭제 시 메뉴·영업시간·상태는 CASCADE. 대표 메뉴 삭제 시 실제 메뉴 연결은 SET NULL. 매칭 이력은 식당 삭제 시 연결만 SET NULL로 보존한다.

## place_url 추가 수집

CSV로 식당·메뉴·가격을 먼저 구성한다. 확정된 카카오 URL에서 요일별 시간표, 휴무, 브레이크 타임, 익일 영업을 추가 수집한다. 추가 메뉴·가격·품절·폐업 표시는 페이지에 실제 표시된 경우에만 반영한다. URL이 있다는 이유로 정보가 있다고 간주하지 않는다. review 후보는 식당 일치를 확인한 후 수집한다.

## PostgreSQL 연결 기준과 이번 구현

현재 requirements.txt에는 psycopg[binary]가 이미 있다. app/database/session.py와 alembic/env.py에서 postgres://·postgresql:// 주소를 postgresql+psycopg://로 통일한다. 명시적으로 지정한 드라이버는 변경하지 않는다. 비밀번호를 로그에 출력하지 않는다.

Supabase 대시보드 Connect의 Direct 또는 Session pooler 주소를 사용하고, 해당 호스트의 접속 가능 여부를 확인한다. 연결 문자열에 sslmode=require를 지정한다. 마이그레이션은 Direct/Session 연결을 사용한다. 브라우저에 DB 접속 비밀번호를 전달하지 않는다.

```dotenv
DATABASE_URL=postgresql+psycopg://USER:URL_ENCODED_PASSWORD@HOST:5432/postgres?sslmode=require
```

실제 .env는 이번 단계에서 변경하지 않았다. 새 스키마는 Alembic으로 생성·변경해야 한다. 현재 앱의 create_all과 seed 자동 실행은 후속 단계에서 PostgreSQL 운영 경로와 분리한다. 기존 모델의 PostgreSQL 컴파일 성공이 목표 ERD의 구축 완료를 뜻하지 않는다.

## 다음 단계와 완료 기준

1. 확정된 Supabase 개발 프로젝트와 전용 연결 주소 준비.
2. Alembic 새 리비전 작성: 내부 식당 ID 및 자식 FK 전환, 신규 필드·매칭 테이블 추가. 기존 ID→내부 ID 대응을 보존한다.
3. CSV 검증·식당 중복 병합·매칭 검토 후 상품 적재. 미확정 후보는 검토 이력으로 분리한다.
4. 실제 메뉴를 대표 메뉴에 연결하고 시간표를 보완한다.
5. 홈·게임·AI·지도에서 공통 DB 조회 함수를 사용한다. 현재 카카오 검색·수집 경로는 아직 교체하지 않았다.
6. 실제 PostgreSQL에서 마이그레이션과 되돌리기·FK·가격 제약·중복 방지·반경 검색·시간표 판정을 검증한다. 연결정보 없는 상태에서 실제 DB 검증 완료로 보고하지 않는다.

수정 예정 파일: app/database/models.py, seed.py, 신규 Alembic 리비전, repositories/restaurants.py, menu_catalog.py, recommendation_engine.py, services.py, api.py, map_routes.py 및 식당 ID를 사용하는 화면·세션·수집기. seed.py는 기존 사용자 수정과 충돌하지 않도록 별도 검토한다.

## 참고

- https://docs.sqlalchemy.org/en/21/dialects/postgresql.html
- https://supabase.com/docs/guides/database/connecting-to-postgres
