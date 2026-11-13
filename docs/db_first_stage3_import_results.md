# 3단계 Supabase 실제 적재 및 검증 결과

작업 경로: C:\temp_resolved. 실행일: 2026-11-12.

## 승인 범위와 스키마

사용자 승인에 따라 식당·전체 정제 상품을 보존하고 대표 메뉴 152종 연결안을 적용했다. 모든 업무 테이블과 CSV 적재 이력은 대소문자를 구분하는 PostgreSQL 스키마 `"Lunchrun"`에만 저장했다.

앞 단계에서 public에 생성되어 있던 빈 식당 업무 테이블 7개와 alembic_version은 ALTER TABLE SET SCHEMA로 이동했다. public에는 users·guestbook만 남겨 두었다. 이번 적재에서 public에 테이블을 생성하거나 데이터를 적재하지 않았다.

애플리케이션 SQLAlchemy 연결은 schema_translate_map과 명시적 search_path를 사용한다. Supabase 풀러가 최초 연결 옵션의 search_path를 반영하지 않는 것을 확인해, 연결 체크아웃 시 `SET search_path TO "Lunchrun"`을 명시적으로 실행한다. Alembic 온라인·오프라인 버전 테이블도 Lunchrun으로 지정했다.

## 실제 적재 결과

| 테이블 | 행 수 |
|---|---:|
| restaurant | 2,174 |
| menu | 35,231 |
| menu_catalog | 152 |
| menu_alias | 167 |
| place_detail_status | 2,174 |
| restaurant_match | 584 |
| business_hours | 0 |
| csv_import_record | 39,041 |

대표 메뉴 연결 상품 2,969건, 그중 가격 known 상품 2,376건을 트랜잭션 내부에서 확인했다. 모든 검증이 통과한 뒤 커밋했다. 적재 배치 ID는 `5013c9fca345ef7716cc5402e2bf5cc5f3cbb1334c086b548f2bb169a738e9b1`이다.

## 미확인·검토 대상 보존

| 상품 분류 | 건수 | 실제 메뉴 연결 |
|---|---:|---|
| linked | 2,969 | 대표 메뉴 FK 설정 |
| review_unmapped_dish | 22,858 | FK NULL |
| review_set_or_portion | 4,351 | FK NULL |
| excluded_beverage | 3,456 | FK NULL, 상품 자체 보존 |
| excluded_side_or_addon | 914 | FK NULL, 상품 자체 보존 |
| excluded_alcohol | 683 | FK NULL, 상품 자체 보존 |

상품별 분류·연결 규칙·인분 확인 상태·원본 행 번호는 csv_import_record의 menus 레코드 payload에 보존했다. 식당·대표 메뉴·별칭·매칭·검토·제외 예정 자료도 같은 배치로 기록했다. 메뉴 테이블 자체의 가격 상태·판매 상태·출처·확인 시각도 유지했다.

메뉴명 없음 343행, 가격 충돌 상품 13그룹의 원본 26행, 분류 검토 대상 원본 4행을 합쳐 373행을 raw_held_row로 보존했다. 이 행들을 임의로 정상 상품으로 만들거나 가격을 추측하지 않았다. 매칭 review·not_found 상태는 restaurant_match에 유지했다.

전체 상품 35,231건의 판매 상태는 unknown이다. 인분 미확인 상품도 판매·1인 식사 적합성이 검증됐다고 간주하지 않는다. 수집 상태의 menu_status=success는 CSV 메뉴 자료를 보유한다는 뜻이며 판매·영업 검증 완료를 의미하지 않는다. hours_status는 pending으로 남겼다.

## 적재 후 새 연결 검증

- 실제 current_schema(): Lunchrun.
- 마이그레이션 버전: 0004_csv_import_records.
- public 테이블: users, guestbook.
- 상품의 식당 FK 누락: 0.
- 상품의 대표 메뉴 FK 누락: 0.
- 중복 카카오 ID: 0.
- 같은 식당·정규화 상품명 중복: 0.
- 모든 상품에 대해 분류 기록 건수와 예정 자료의 분류 집계 일치.
- 업무·검토 테이블 8개에 RLS 활성화. anon/authenticated 테이블 권한 회수.
- FastAPI 시작 성공, /api/health 및 /api/chat/session HTTP 200.

## 관련 파일과 후속 단계

- import_csv_stage3.py: Lunchrun 스키마만 대상으로 하는 승인 적재 도구. 기존 데이터가 있으면 중단하여 중복 재실행을 막는다. 예외 발생 시 전체 트랜잭션을 롤백한다.
- alembic/versions/0004_csv_import_records.py: 검토·출처 보존 테이블 추가.
- tmp/csv_stage3_catalog_review/import_result.json: 실제 커밋 결과. summary.json은 적재 전 예정 결과 스냅샷이다.
- inspect_supabase.py: Lunchrun 스키마 읽기 전용 점검으로 변경.

이번 단계는 데이터 적재까지다. 사용자 요청에서 DB만 조회하는 추천 흐름으로의 교체와 place_url 기반 영업시간 추가 수집은 아직 진행하지 않았다. 기존 상세 수집 경로는 같은 식당의 메뉴를 교체할 수 있으므로, 별도 수집을 실행하기 전에 출처별 갱신·보존 규칙을 적용해야 한다. 현재 데이터만으로 현재 영업 중인 식당 추천이 완성됐다고 볼 수 없다.

사용자 요청에 따른 커밋·push는 실행하지 않았다.
