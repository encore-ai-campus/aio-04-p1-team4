# DB 구축 2단계: Supabase 연결 및 스키마 적용 결과

작업 경로: C:\temp_resolved. 완료일: 2026-11-12.

## 연결과 적용

SUPABASE_DB_URL을 읽어 PostgreSQL + psycopg 3로 실제 접속했다. 연결 주소와 비밀번호는 이 문서에 기록하지 않는다. 적용 전 public에는 users, guestbook만 있었으며 두 테이블은 변경하지 않았다.

Alembic 0001 → 0002 → 0003_db_first_schema 적용 완료. 식당 업무 테이블 7개와 alembic_version이 추가되었다. 이번 단계에서 CSV·실제 식당·기본 카탈로그 데이터는 적재하지 않았다.

| 테이블 | 적용 내용 |
|---|---|
| restaurant | PostgreSQL UUID PK, 카카오 ID 별도 nullable unique, 네이버 ID, 운영 상태 |
| menu | 식당 UUID FK, 대표 메뉴 nullable FK, 실제 가격·상태 일치 제약, 판매 상태, 출처·확인 시각 |
| menu_catalog | 기존 카탈로그 유지, 후속 단계에서 기준가격 대체 추천 제거 예정 |
| menu_alias | 대표 메뉴별 별칭 및 고유 정규화명 |
| business_hours | 식당 UUID FK, 요일별 구간과 출처·확인 시각 |
| place_detail_status | UUID PK/FK, 메뉴·시간표별 마지막 성공 시각 추가 |
| restaurant_match | 미확정 후보와 매칭 근거, 식당 삭제 시 검토 이력 보존 |

## 1단계 설계와 단계적 전환 차이

- menu_catalog의 cuisine, search_keyword, description, price_hint는 기존 API·게임 코드가 참조하므로 이번 단계에서 삭제하지 않았다. DB 중심 후보·추천 경로 교체 후 제거하거나 nullable 전환할 예정이다. 최종 스키마 정리까지 끝났다는 의미는 아니다.
- 원본 분류는 신규 category_raw 열을 중복 추가하지 않고 기존 category_name에 보존한다.
- 기존 정수 상품·별칭·시간표 ID는 INTEGER 자동 생성 방식을 유지했다. 신규 매칭 이력 ID는 BIGSERIAL이다. 내부 식당 PK·관련 FK는 실제 PostgreSQL UUID다. 향후 IDENTITY/BIGINT 일괄 전환은 별도 마이그레이션으로 처리할 수 있다.
- 기존 last_success_at·error_code는 호환용으로 유지하고 항목별 성공 시각을 추가했다.
- 기존 SQLite 테스트는 문자열 식당 ID와 create_all 경로를 유지한다. 0003은 PostgreSQL 전용이며 SQLite Alembic head 업그레이드는 지원하지 않는다. 과거 SQLite 마이그레이션 테스트 전체를 통과했다고 주장하지 않는다.
- 0003은 확인된 빈 식당 스키마를 재구성하는 전환이다. 식당 업무 테이블에 행이 있으면 중단한다. 기존 데이터가 있는 다른 DB의 UUID 전환에는 별도 보존 마이그레이션이 필요하다.

## 애플리케이션 연결

- 앱·Alembic은 DATABASE_URL 우선, SUPABASE_DB_URL 다음, 로컬 SQLite 기본값 순으로 선택한다.
- PostgreSQL에서는 앱 시작 시 자동 create_all·seed를 실행하지 않는다. 적용된 0003 버전을 검사한다.
- 카카오 저장소는 카카오 ID로 기존 식당을 조회하고 신규 식당에 UUID를 생성한다. PostgreSQL 검색 결과 ID를 내부 UUID로 연결해 기존 지도·후속 질문 경로에 전달한다.
- 상세수집은 내부 UUID로 DB를 조회하고 외부 페이지 검증에는 별도의 카카오 ID를 전달한다.
- 수집 저장 시 출처와 확인 시각·항목별 마지막 성공 시각을 기록한다.
- 사용자 요청 중 카카오 검색·상세수집하는 기존 추천 흐름은 아직 남아 있다. DB 전용 추천은 후속 단계다.

## 접근 제한

업무 테이블 7개에 RLS를 활성화하고 anon/authenticated 테이블 권한을 회수했다. 브라우저 publishable key로 직접 이 테이블을 읽는 정책은 만들지 않았다. 현재 접근 경로는 서버의 PostgreSQL 연결이다. 관리자 연결은 RLS를 우회할 수 있으므로 추후 배포 역할을 별도로 설계한다.

## 검증 결과

- 실제 Supabase 접속 성공.
- ORM과 실제 업무 테이블 비교: 스키마 차이 0건. users·guestbook은 비교 대상에서 제외.
- 시험 데이터로 UUID 생성, 실제 메뉴 연결, 가격 미확인/known 불일치 차단 확인.
- 대표 메뉴 삭제 시 상품 연결 SET NULL 확인.
- 식당 삭제 시 상품 CASCADE, 매칭 이력 연결 SET NULL 확인.
- 시험 트랜잭션 롤백 후 restaurant 0행 확인. CSV 적재 없음.
- 업무 테이블 7개 RLS 활성화 확인.
- FastAPI lifespan 시작 성공, /api/health 및 /api/chat/session HTTP 200.
- 저장·상세정보·추천 회귀 테스트: 35 passed. 이는 SQLite 격리 테스트이며 Supabase의 실데이터 추천 검증은 아니다.

## 다음 단계

CSV 분리·매칭·중복 정리 및 대표 메뉴 연결을 거쳐 데이터를 적재한다. 그 후 DB 조회 후보 생성과 지도·챗봇 경로를 전환한다. 현재는 카탈로그와 식당이 비어 있으므로 추천 결과가 없는 상태가 정상이다. 이 문서 작성 과정에서 커밋·push는 실행하지 않았다.
