# 5단계 DB 챗봇 검증 안내 v1

- 작성일: 2026-11-10
- 대상: DB 메뉴 추천, 재추천, 식당 검색, 식당 후속 질문

## 1. 자동 테스트

프로젝트 루트 `C:\TeamProject_1`의 PowerShell에서 실행한다.

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_recommendations.py tests\test_menu_catalog.py tests\test_recommendation_engine.py -v
```

전체 회귀 테스트:

```powershell
.\.venv\Scripts\python.exe -m pytest -q
node --test tests\chat-session-ui.test.cjs tests\groq-status.test.cjs tests\location.test.cjs tests\location-flow.test.cjs tests\restaurant-ui.test.cjs tests\map.test.cjs
```

작성 시점 결과:

- 전체 Python: `76 passed`, `1 skipped`, `36 subtests passed`
- 전체 프론트엔드: `31 passed`
- Starlette `TestClient` 사용 중단 예정 경고 1개는 이번 기능 실패가 아니다.

## 2. DB 메뉴 사용 확인

서버를 실행한다.

```powershell
.\.venv\Scripts\python.exe -m uvicorn app.main:app --reload
```

브라우저에서 `http://127.0.0.1:8000`을 열고 위치와 조건을 설정한다.

1. `메뉴 추천해줘`라고 질문한다.
2. 응답에 추천 메뉴가 표시되는지 확인한다.
3. 이 질문만으로 카카오 식당 검색 화면이 생성되지 않는지 확인한다.
4. `다른 메뉴 추천해줘`라고 질문한다.
5. 직전 메뉴와 다른 메뉴가 표시되는지 확인한다.

브라우저 Network 탭의 `/api/chat` 응답에서 다음을 확인할 수 있다.

- `result.menu_catalog_demo: false`
- `result.menu.source`: `database` 또는 `catalog`
- 실제 가격이 없으면 `result.menu.price: null`

## 3. 식당 추천 확인

선정 메뉴가 있는 상태에서 `이 메뉴 파는 식당 보여줘`라고 질문한다.

- 카카오 검색 결과가 식당 DB에 저장되는지 확인한다.
- 확인된 추천과 확인 필요 후보가 분리되는지 확인한다.
- 메뉴 가격이 예산을 넘는 식당이 추천 목록에 없는지 확인한다.
- 영업시간 미확인 또는 현재 영업시간 밖 식당이 추천 목록에 없는지 확인한다.

## 4. 후속 질문 확인

식당 추천 결과가 나온 같은 브라우저에서 질문한다.

```text
첫 번째 식당 가격은?
그 식당 지금 영업 중이야?
그 식당 주소 알려줘
어떤 메뉴가 있어?
왜 추천했어?
```

확인 항목:

- 가격이 DB의 `menu.price`와 일치하는가?
- 한국 시간 기준 `영업 중` 또는 `영업 종료`가 표시되는가?
- 주소가 `restaurant.address`와 일치하는가?
- 수집된 메뉴만 표시되는가?
- 후속 질문마다 카카오 검색을 다시 실행하지 않는가?

## 5. 누락 정보 확인

메뉴·가격 또는 영업시간 수집에 실패한 식당은 다음처럼 표시되어야 한다.

- 가격 없음: `가격 확인 불가`
- 메뉴 없음: `메뉴 확인 불가`
- 영업시간 없음: `현재 영업 상태를 알 수 없습니다`
- 주소 없음: `주소는 확인할 수 없습니다`

누락값이 `0원`, 가상의 주소 또는 임의의 `영업 중`으로 표시되면 실패다.

## 6. 현재 제한

실제 Groq 문장 분류는 API 키와 외부 사용량이 필요하므로 기본 자동 테스트에서는 모의 응답을 사용한다. 상세수집 중 단계별 스트리밍 메시지와 스피너 개선은 다음 단계에서 구현한다.
