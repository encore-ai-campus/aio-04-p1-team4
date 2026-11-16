# 대표 메뉴 수동 관리

기준일: 2026-11-16. 대상은 Supabase PostgreSQL의 `menu_catalog`·`menu_alias`다. 상세 스키마는 [DB 설계서](DB_DESIGN_v1.md)를 참고한다.

## seed.py의 역할

`app/database/seed.py`는 대표 메뉴와 별칭을 관리하는 수동 도구다. 현재 PostgreSQL 구성에서는 서버 시작이나 일반 추천 요청이 이 목록을 자동 동기화하지 않는다. 추천은 DB의 저장 데이터를 조회한다.

수동 동기화는 새 대표 메뉴 추가, 기존 메뉴의 이름·분류·호환 필드·별칭 갱신, 목록에서 빠진 메뉴의 `active=False` 처리, 같은 ID로 다시 추가한 메뉴의 활성화를 수행한다.

실제 식당 상품인 `menu`의 가격·상품 연결·영업시간은 수정하지 않는다. 대표 메뉴를 추가해도 해당 지역의 실제 상품이 `menu.menu_catalog_id`로 연결되지 않으면 추천 후보가 생기지 않는다.

## 실행 전 DB 연결 확인

| 실행 경로 | DB 연결 변수 |
| :---: | :---: |
| FastAPI 앱 | `DATABASE_URL` 우선, 없으면 `SUPABASE_DB_URL` |
| Alembic | 별도 실행 인자·설정이 없으면 `DATABASE_URL` 우선, 없으면 `SUPABASE_DB_URL` |
| seed.py 수동 명령 | `DATABASE_URL`만 사용 |

**현재 seed 명령은 `SUPABASE_DB_URL`을 읽지 않는다.** 실행 전 프로젝트 루트의 `.env` 또는 실행 환경의 `DATABASE_URL`에 의도한 Supabase 연결 주소를 설정한다. `SUPABASE_DB_URL`만 설정한 상태에서는 실행하지 않는다. 실행 환경에 있는 `DATABASE_URL`은 `.env`보다 우선하므로 대상이 같은지 확인한다. 연결 주소와 비밀번호를 출력하지 않는다.

`Lunchrun` 스키마와 `0004_csv_import_records` revision을 먼저 준비한다. seed 명령은 스키마 생성·revision 적용을 수행하지 않는다. 절차는 [DB 마이그레이션 안내](database_migration_guide_v1.md)를 따른다.

## 메뉴 추가·수정

저장소 루트 기준 `app/database/seed.py`의 `DEFAULT_MENU_CATALOG` 목록을 편집한다. 아래는 형식 예시다. 기존 ID·이름·별칭과 중복되지 않는지 확인한 뒤 사용한다.

```python
dict(
    id="tteokbokki",
    name="떡볶이",
    cuisine="분식",
    price_hint=None,
    search_keyword="떡볶이",
    description="떡볶이 메뉴 안내",
    aliases=("떡볶이", "국물떡볶이"),
),
```

| 항목 | 편집 규칙 |
| :---: | :---: |
| id | 최대 40자. 같은 메뉴를 수정할 때 유지 |
| name | 최대 100자. 다른 대표 메뉴와 정규화 이름 중복 불가 |
| cuisine | `전체`를 제외한 14개 저장 분류 중 하나 |
| price_hint | 호환용 참고 가격. `None` 또는 0 이상 정수. 현재 추천·예산 판정에 사용하지 않음 |
| search_keyword | 최대 100자. 호환 필드이며 현재 일반 추천에서 카카오 검색을 실행하지 않음 |
| description | 최대 500자, 비어 있지 않은 설명 |
| aliases | 각각 최대 100자의 별칭 목록·튜플. 정규화한 별칭은 전체에서 중복 불가 |

동기화 검증은 `id`, `name`, `search_keyword`, `description`에 비어 있지 않은 문자열을 요구한다. 별칭 하나만 쓸 때도 `aliases=("떡볶이",)`처럼 쉼표를 붙인다. 별칭을 편집하는 것만으로 기존 실제 상품의 FK가 자동 갱신되지는 않는다.

저장 분류는 한식, 중식, 일식/회, 양식, 분식, 패스트푸드, 치킨, 도시락/구내식당, 뷔페식, 냉면, 고기, 카페/빵, 술집, 기타다. 원본 업태와의 관계는 [음식 종류 매핑](food_conditions_v3.md)을 참고한다.

## 비활성화와 복원

목록에서 메뉴를 제거하면 DB 행을 삭제하지 않고 `active=False`로 바꾼다. 같은 ID로 다시 추가하면 활성화된다. ID를 바꾸면 기존 메뉴 비활성화와 새 메뉴 생성으로 처리하므로 단순 수정에는 ID를 유지한다.

동기화는 전체 목록을 대상으로 하며 목록에 없는 다른 운영 메뉴도 비활성화할 수 있다. 별칭도 전체 카탈로그 기준으로 다시 구성한다. 일부 항목만 담은 목록을 전체 운영 카탈로그에 동기화하지 않는다.

## 변경 내용 반영

가상환경·대상 DB·수정한 전체 목록을 확인한 뒤 저장소 루트 PowerShell에서 실행한다.

```powershell
.\.venv\Scripts\python.exe -m app.database.seed
```

출력 형식 예시:

```json
{"inserted": 1, "updated": 10, "deactivated": 0}
```

`updated`는 목록에 있던 기존 메뉴 수이며 값이 실제 변경되지 않은 행도 포함한다. `deactivated`는 이번 실행에서 새로 비활성화된 메뉴 수다. 빈 목록과 중복 ID·이름·별칭 등은 검증 오류로 처리한다.

동기화는 트랜잭션 단위로 반영한다. **파일 저장이나 서버 재시작만으로는 Supabase에 메뉴 변경이 반영되지 않는다.** 실행 후 활성 상태·별칭·실제 상품 연결과 추천 응답을 확인한다.
