# LunchRun 챗봇 1~6단계 구현 및 통합 검증

- 작업 대상: C:\temp_resolved
- 작성일: 2026-11-13
- 이 문서는 최종 현황입니다. 이전 단계 문서는 변경 이력으로 보존합니다.

## 1. 단계별 결과

| 단계 | 적용 내용 | 상세 문서 |
|---|---|---|
| 1 | DB 추천 필터 완화, 가격/시간 미확인 안내, 영업 우선·거리순 최대 3곳 | [1단계](chatbot_recommendation_policy_v5_stage1.md) |
| 2 | 메뉴만 추천 후 식당 조회 제안, 현재 메뉴 하나만 제외한 재추천, 명시 메뉴 조회 | [2단계](chatbot_recommendation_policy_v5_stage2.md) |
| 3 | 표시 순서·상품·가격 기억, 순서별 후속 질문, 주소/영업/추천 이유, 과거 문맥 무효화 | [3단계](chatbot_recommendation_policy_v5_stage3.md) |
| 4 | 조건 즉시 적용·전후 비교, 반경 50m 조절, 메뉴 재선정 및 결합 조회 | [4단계](chatbot_recommendation_policy_v5_stage4.md) |
| 5 | Groq 답변 문단 구성, 사실 보존 검증, 실패 시 서버 답변 대체, 지연/사용량 메타데이터 | [5단계](chatbot_recommendation_policy_v5_stage5.md) |
| 6 | 기능·브라우저 회귀 검증, 지도/게임 정책 통일, 최초 질문 규칙 누락 보완, 소량 실제 Groq 확인 | 이 문서 |

## 2. 현재 실행 흐름

1. 사용자가 위치·반경·음식 종류·예산·점심 종료 시각을 설정합니다.
2. Groq가 질문의 의도·대상·조건 변경을 해석합니다.
3. 서버가 SQLAlchemy로 현재 DB의 조건에 맞는 상품·식당을 조회합니다.
4. 메뉴 요청은 메뉴만 뽑습니다. 식당 요청은 그 메뉴의 식당을 최대 3곳 보여줍니다.
5. 서버가 확정한 문장을 Groq가 허용된 도입·연결 표현과 문단으로 구성합니다. 사실 문장은 서버 원문을 보존합니다.
6. 생성 실패 시 서버 문장으로 대체하고 결과·적용 조건·최근 10턴을 세션에 저장합니다.
7. 다음 질문은 화면 조건과 서버 세션의 표시 기록으로 이어갑니다.

추천은 현재 DB에 저장되고 대표 메뉴 ID가 연결된 식당 상품을 사용합니다. 위치를 바꿀 때 카카오로 새 식당을 자동 수집하는 기능을 추가한 작업이 아닙니다. 새 지역의 DB 데이터가 없으면 결과가 없을 수 있습니다. CSV 파일을 실시간 후보 목록으로 읽지 않습니다.

## 3. 현재 질문별 동작

| 질문 예시 | 동작 |
|---|---|
| 메뉴 추천해줘 | 조건 후보 중 하나 선정, 조건과 식당 조회 제안 |
| 다른 메뉴 추천해줘 | 현재 메뉴 하나만 제외, A → B → A 가능 |
| 어떤 메뉴가 있어? | 조건 후보 최대 3개 표시, 사용자 대신 하나를 선정하지 않음 |
| 짜장면 식당 알려줘 | 명시 메뉴의 식당 최대 3곳 |
| 이 메뉴 파는 식당 알려줘 | 현재 메뉴로 조회, 메뉴가 없으면 먼저 선정 안내 |
| 두 번째 식당 가격은? | 실제 두 번째로 표시했던 상품명·가격 |
| 그 식당 주소 알려줘 | 지목한 대상이 명확하면 DB 주소, 불명확하면 대상 확인 |
| 지금 영업 중이야? | 저장 시간표와 질문 시점 한국 시간으로 재계산 |
| 왜 추천했어? | 마지막 추천 종류에 따라 메뉴 조건 또는 식당 추천 이유 |
| 예산을 8천원으로 바꿔줘 | 즉시 적용, 전후 비교, 새 메뉴 선정 |
| 반경을 줄여줘/늘려줘 | 50m 조절, 50~500m 경계 처리 |
| 한식으로 바꾸고 식당도 찾아줘 | 전후 비교, 메뉴 재선정, 해당 식당 조회 |
| 이 메뉴는 어떤 음식이야? | 음식 설명은 제공하지 않는다는 고정 안내 |
| 오늘 날씨 알려줘 | 메뉴 선정 및 식당 선정에 관한 질문만 말씀해주세요. |

음식 설명용 DB 열과 이전 클라이언트 의도는 호환을 위해 남아 있지만 실행 경로에서 음식 설명을 생성하지 않습니다. 범위 밖 질문은 기존처럼 pending 처리합니다. 품절·인분·채식·맵기는 추천 조건으로 사용하지 않습니다.

## 4. 6단계에서 발견하고 수정한 문제

### 지도와 채팅의 영업 상태 차이

지도 상세는 기존 current_open_status를 사용하여 오늘 시간표가 불완전해도 closed가 될 수 있었습니다. 추천·채팅과 같은 recommendation_hours를 사용하도록 통일했습니다. 명시적 폐업은 과거 시간표보다 우선하여 closed로 처리합니다.

### 남아 있던 인분·판매 안내

지도 주변 조회의 인분 미확인 문구를 제거했습니다. 게임은 인분 판정을 하지 않는데도 serving_unverified=false를 '1인분 확인'으로 표현하고 있었습니다. 인분/판매 상태 안내를 제거하고 식당별 가격·영업시간 확인 안내로 바꿨습니다. 가격이 없으면 '미확인원' 대신 '가격 확인 필요'를 표시합니다.

### 최초 합의와 다른 질문 규칙

- 후보 목록 요청에 list_menus 의도를 추가하고 조건 후보를 최대 세 개만 반환합니다. 선택 메뉴·식당 목록은 덮어쓰지 않습니다.
- 음식 설명 요청은 제공 제외 고정 안내로 바꾸었습니다.
- 범위 밖 질문의 답변을 합의한 문구로 맞췄습니다.

### 테스트의 오래된 기대값

게임 프록시 테스트가 배포 주소와 무관하게 로컬 주소를 가정하여 실패했습니다. 운영 주소는 바꾸지 않고 테스트에서만 대상을 고정했습니다. 브라우저 테스트의 옛 인분 안내 기대값도 현재 정책에 맞췄습니다.

## 5. 자동 검증 범위와 결과

최종 수치는 아래 결과 기록에 기입합니다. 기능 테스트에는 DB, 클라이언트 모의 HTTP, 가드레일, 추천, 조건 변경, 후속 질문, 메모리 세션, 외부 서비스 오류 처리가 포함됩니다.

실제 브라우저 통합 검증:

- 홈·게임의 공통 채팅, 조건 변경, 대화 복원, 지도 이동
- 홈 메뉴 후보 → 랜덤 게임 → 지도 → 역순 탐색
- 위치 변경에 따른 후보·지도 상태 갱신

Node 테스트는 공통 상태, 오래된 응답 차단, 조건 즉시 적용, 위치·지도·채팅 동작을 확인합니다. 픽셀/디자인 비교 테스트 전체와 모든 게임 모드의 UI 검증을 수행한 것은 아닙니다. 실제 운영 DB의 전 지역 메뉴·가격·시간표 품질을 검증한 것도 아닙니다.

### 실행 명령

```powershell
cd C:\temp_resolved
$testFiles = Get-ChildItem .\tests -Filter 'test_*.py' -File | Where-Object { $_.Name -notmatch 'browser|design|guardrail_live' } | ForEach-Object { $_.FullName }
.\.venv\Scripts\python.exe -m pytest @testFiles tests/test_chat_browser_flow.py tests/test_db_first_browser.py tests/test_location_browser_flow.py -q -p no:cacheprovider
node --test tests/chat-conditions-stage4.test.cjs tests/chat-session-ui.test.cjs tests/frontend-contract.test.cjs tests/groq-status.test.cjs tests/location-flow.test.cjs tests/location.test.cjs tests/map.test.cjs tests/restaurant-ui.test.cjs tests/shared-state.test.cjs
```

일반 자동 검증은 실제 모델을 호출하지 않습니다.

## 6. 실제 Groq 확인과 제한

실제 검증은 임시 SQLite의 검증용 식당·짜장면·8000원·24시간 시간표를 사용했습니다. 운영 DB와 카카오 검색/상세 수집은 사용하지 않았습니다. 사전 안내한 세 질문에 대해 최대 6회 HTTP 호출 상한을 두었습니다.

| 순서 | 실제 결과 |
|---|---|
| 1. 메뉴 추천해줘 | 질문 해석·답변 구성 성공, 전체 요청 약 1.62초 |
| 2. 이 메뉴 파는 식당 알려줘 | 서버가 HTTP 200으로 응답. 답변 구성 호출이 HTTP 429 사용량 제한에 걸려 server_fallback으로 대체, 전체 요청 약 1.03초. 예상 식당 목록 세부값 단언 전에 테스트가 중단되어 실제 목록 검증 완료로 간주하지 않음 |
| 3. 첫 번째 식당 가격은? | 실제 추가 호출 중단으로 미실행. 모의 API 통합 테스트에서는 검증 완료 |

실제 검증 테스트는 '세 턴 모두 Groq 답변 성공'을 기대하므로 두 번째 턴에서 실패로 기록되었습니다. 서비스는 설계대로 server_fallback으로 응답했습니다. 두 번째 실제 응답의 식당 목록 세부 검증과 세 번째 실제 후속 질문은 완료하지 못했습니다. 이 결과를 전체 실제 검증 성공으로 표시하지 않습니다.

위 시간은 서버 로그의 전체 요청 시간이며 추가 답변 생성 시간만을 뜻하지 않습니다. 최초 실행은 중간 실패 전에 사용량 요약을 출력하지 못하여 실제 토큰 수치·정확한 호출 횟수는 이 보고서에 기입하지 않습니다. 호출 상한은 코드로 제한했습니다. 향후 검증은 중간 실패 시에도 수치를 출력하도록 보완했습니다. 실제 모델 준수율·평균 지연·평균 토큰 사용량을 단 두 턴으로 일반화할 수 없습니다.

사용량 제한이 해제된 후 사용자가 별도로 재검증하려면 다음과 같이 실행할 수 있습니다. 다시 실행할 때마다 최대 6회의 실제 Groq 호출이 발생할 수 있습니다.

```powershell
cd C:\temp_resolved
$env:LUNCHRUN_LIVE_STAGE6 = '1'
.\.venv\Scripts\python.exe -m pytest tests/test_chat_integration_stage6.py -k live_three_turns -q -s -p no:cacheprovider
Remove-Item Env:LUNCHRUN_LIVE_STAGE6
```

테스트 실패 시 표시된 오류 사유를 확인합니다. 외부 사용량 제한이 남아 있으면 반복 실행하지 않습니다. 일반 기능 검증에서는 이 환경변수를 켜지 않습니다.

## 7. 직접 화면에서 확인하는 순서

1. 기존 서버를 Ctrl+C로 종료한 후 C:\temp_resolved에서 .\run.ps1을 실행합니다.
2. http://127.0.0.1:8000/ai 를 열고 Ctrl+F5로 새로고침합니다.
3. 위치·반경·예산·음식 종류·점심 종료 시각을 설정합니다.
4. '어떤 메뉴가 있어?' → 조건에 맞는 후보가 최대 세 개인지 확인합니다.
5. '메뉴 추천해줘' → 메뉴 하나와 조건, 식당 조회 제안을 확인합니다.
6. '다른 메뉴 추천해줘' → 현재 메뉴와 다른 메뉴가 나오는지 확인합니다. 후보가 하나면 다른 후보 없음이 정상입니다.
7. '이 메뉴 파는 식당 알려줘' → 식당 최대 세 곳, 영업 우선·거리순, 누락 안내를 확인합니다.
8. '두 번째 식당 가격은?' → 해당 줄의 실제 상품·표시 가격과 비교합니다. 두 번째가 없으면 대상 확인이 정상입니다.
9. 특정 식당의 주소와 '지금 영업 중이야?'를 묻습니다. 누락 시 정해진 안내가 나오는지 확인합니다.
10. '왜 추천했어?' → 식당 추천 이유를 확인합니다.
11. '예산을 8천원으로 바꾸고 식당도 찾아줘' → 전후 조건, 새 메뉴·목록이 나오고 홈 조건도 바뀌는지 확인합니다.
12. '반경을 줄여줘' → 실제 반경 변화와 안내를 확인합니다. 최소/최대 경계도 확인합니다.
13. 메뉴만 다시 추천받은 뒤 옛 식당 가격을 물으면 과거 목록을 재사용하지 않아야 합니다.
14. 새로고침 후 최근 대화가 복원되는지 확인합니다. 서버 재시작·세션 만료 시 메모리 대화는 사라집니다.
15. 게임 결과에 인분 확인/품절 안내가 없고 지도·채팅이 같은 메뉴·조건의 식당을 보여주는지 확인합니다.

개발자 도구 Network의 /api/chat/stream 최종 completed.data에서 answer_source 및 narration을 확인합니다. groq는 문단 구성 성공, server_fallback은 서버 대체, server는 고정 안내/추가 생성 생략입니다. 실제 사용량 제한으로 첫 질문 해석부터 실패하면 기존 오류 안내가 나오며 임의의 결과를 만들지 않습니다.

개발자 도구 Console의 다음 명령은 현재 세션을 읽기만 합니다.

```javascript
fetch('/api/chat/session').then(r => r.json()).then(console.log)
```

turns는 최대 10턴, conditions/radius_m은 현재 적용값, displayed_restaurants는 표시 순서·상품·가격입니다. 실제 데이터에 없는 누락/폐업 사례를 만들려고 운영 DB를 수정할 필요는 없습니다. 자동 테스트가 해당 사례를 대신 검증합니다.

## 8. 남은 제한

- 실제 Groq 세 턴 완주는 사용량 제한으로 남았습니다. 해제 후 선택적 재검증이 필요합니다.
- 새로운 위치의 식당 자동 수집·갱신, 운영 DB 데이터 충실도 개선은 별도 작업입니다.
- Groq는 사실 문장을 자유롭게 재서술하지 않고 허용 표현·문단만 구성합니다.
- 글자 단위 토큰 스트리밍 대신 진행 이벤트와 최종 답변을 전달합니다.
- 세션은 단일 프로세스 메모리입니다. Redis/다중 서버 지속 저장은 미구현입니다.
- Supabase 이전·인증·배포는 이번 통합 검증 범위가 아닙니다.
- 점심시간은 입력 조건 표시이며 실제 이동·식사시간을 보장하지 않습니다.

### 게임 화면의 실행 경로 주의

games/app.py의 NODE_ORIGIN은 현재 https://lunchrun-games.onrender.com 입니다. 따라서 기본 실행의 /games는 해당 원격 서버가 제공하는 파일을 사용합니다. 이번 로컬 games/dist/app.mjs 수정은 Render 서버에 배포해야 그 화면에 반영됩니다. 이번에는 배포하지 않았고 운영 프록시 주소도 변경하지 않았습니다. 브라우저 통합 테스트는 임시 로컬 Node 서버로 프록시를 대체하여 로컬 수정 파일을 검증했습니다. 이를 원격 Render 화면 검증과 혼동하면 안 됩니다. 로컬 FastAPI의 /ai, /map 및 챗봇 API 변경은 서버 재시작 후 적용됩니다.

## 9. 6단계 변경 파일

새 파일:

- tests/test_chat_integration_stage6.py: 전체 흐름·지도 일치·질문 규칙·선택적 실제 모델 확인
- docs/chatbot_recommendation_policy_v5_stage6.md: 이 최종 보고서

수정 파일:

- app/map_routes.py: 공통 영업 판정 및 옛 인분 문구 제거
- app/db_recommendations.py: 명시적 폐업을 과거 시간표보다 우선
- games/dist/app.mjs: 인분 확인/판매 안내 제거, 가격 미확인 표시
- app/chat_policy.py 및 app/prompts/system_v4.txt: 후보 목록 의도와 설명 제외 규칙
- app/prompts/replies_v4.json: 합의한 범위 밖 질문 문구
- app/services.py: 후보 최대 세 개 조회 및 음식 설명 고정 안내
- app/answer_narration.py: 후보 목록 설명 구성 연결, 음식 설명 고정 안내는 추가 호출 제외
- tests/test_games_proxy.py: 테스트 주소 격리
- tests/test_db_first_browser.py: 현재 정책과 일치하는 브라우저 기대값

파일 삭제·DB 스키마 변경·운영 DB 데이터 변경은 없습니다. 수정 이유는 코드 주석으로 남겼습니다.

## 10. 최종 수치

2026-11-13 최종 검증:

- 기능·브라우저 Python 테스트: 238개 통과, 실제 API 선택 테스트 1개 제외, 하위 검증 59개 통과
- Node 화면/상태 테스트: 29개 통과
- games/dist/app.mjs 문법 검사 통과
- 기존 FastAPI TestClient/httpx 사용 중단 예정 경고 1건
- 별도로 실행한 실제 Groq 세 턴 검증: 두 번째 턴에서 사용량 제한으로 완주 실패. 첫 메뉴 추천 성공과 대체 응답 작동을 확인했고, 이후 실제 호출은 중단함

위 통과 수치는 모의 API·임시 DB와 로컬 브라우저 검증의 결과입니다. 실제 모델 세 턴 완주 또는 원격 Render 화면 배포 성공을 의미하지 않습니다.

## GitHub 브랜치 충돌 해결 기록

khj_backend와 origin/main의 기반 차이를 먼저 확인했습니다. 아래는 병합 전 경로 차이입니다. A는 main에만 존재하는 파일, D는 main에서 제거/이동된 경로, M은 양쪽 내용 차이입니다. branch에만 추가된 기존 문서는 보존합니다. 이전 프론트 파일의 main 이동 경로는 frontend/backup입니다. tmp·환경 비밀값·DB 파일은 스테이징하지 않으며 stash도 보존합니다.

```text
M	.env.example
M	.gitignore
M	.obsidian/workspace.json
A	EXECUTION_GUIDE.md
A	LOCAL_RUN_TROUBLESHOOTING.md
M	README.md
M	alembic/env.py
A	alembic/versions/0003_db_first_schema.py
A	alembic/versions/0004_csv_import_records.py
M	app/api.py
M	app/chat_sessions.py
M	app/collectors/kakao_place.py
M	app/config.py
M	app/database/__init__.py
M	app/database/models.py
M	app/database/seed.py
M	app/database/session.py
A	app/db_recommendations.py
M	app/detail_collection.py
M	app/main.py
A	app/map_routes.py
M	app/menu_catalog.py
M	app/operations.py
M	app/prompts/system_v4.txt
M	app/repositories/place_details.py
M	app/repositories/restaurants.py
M	app/services.py
A	collect_hours_stage4.py
A	docs/db_first_stage1_design.md
A	docs/db_first_stage2_results.md
A	docs/db_first_stage3_catalog_review.md
A	docs/db_first_stage3_import_results.md
A	docs/db_first_stage3_preview.md
A	docs/db_first_stage4_hours_results.md
A	docs/db_first_stage5_flow_results.md
A	docs/db_first_stage6_final_verification.md
D	docs/food_conditions_v2.md
D	docs/food_conditions_v3.md
A	docs/frontend_merge_integration_results.md
A	docs/frontend_merge_stage1_plan.md
A	docs/frontend_merge_stage2_results.md
A	docs/frontend_merge_stage3_results.md
A	docs/frontend_merge_stage4_results.md
A	docs/frontend_merge_stage5_results.md
A	docs/frontend_plain_routes.md
A	docs/live_connections_results.md
D	docs/random_game_flow_v1.md
D	docs/seed_management_v1.md
D	docs/seed_management_v2.md
A	expand_menu_catalog_stage3.py
A	frontend/ai-integration.css
A	frontend/api.js
A	frontend/api_contract.md
M	frontend/app.js
A	frontend/assets/draw.png
A	frontend/assets/gacha.png
A	frontend/assets/ladder.png
A	frontend/assets/location-dialog.css
A	frontend/assets/location-dialog.js
A	frontend/assets/logo.svg
A	frontend/assets/option-draw.png
A	frontend/assets/option-gacha.png
A	frontend/assets/option-ladder.png
A	frontend/assets/option-random.png
A	frontend/assets/option-roulette.png
A	frontend/assets/option-ticket.png
A	frontend/assets/profile-dialog.css
A	frontend/assets/profile-dialog.js
A	frontend/assets/random.png
A	frontend/assets/restaurants.png
A	frontend/assets/result.png
A	frontend/assets/roulette.png
A	frontend/assets/route.png
A	frontend/assets/screen-motion.js
A	frontend/assets/screens/01-conditions.png
A	frontend/assets/screens/02-budget.png
A	frontend/assets/screens/03-end-time.png
A	frontend/assets/screens/04-people.png
A	frontend/assets/screens/05-distance.png
A	frontend/assets/screens/06-solo-games.png
A	frontend/assets/screens/07-draw.png
A	frontend/assets/screens/08-gacha.png
A	frontend/assets/screens/09-ticket.png
A	frontend/assets/screens/10-random-game.png
A	frontend/assets/screens/11-group-games.png
A	frontend/assets/screens/12-group-input.png
A	frontend/assets/screens/13-roulette.png
A	frontend/assets/screens/14-ladder.png
A	frontend/assets/screens/15-ai-input.png
A	frontend/assets/screens/16-menu-result.png
A	frontend/assets/screens/17-restaurants.png
A	frontend/assets/screens/18-route.png
A	frontend/assets/shared-header.css
A	frontend/assets/ticket.png
A	frontend/backup/app.js
A	frontend/backup/groq-status.js
A	frontend/backup/index.html
A	frontend/backup/kakao-sdk.js
A	frontend/backup/location.js
A	frontend/backup/map.js
A	frontend/backup/styles.css
A	frontend/build.cjs
A	frontend/bundle.js
A	frontend/chat.css
A	frontend/chat.js
A	frontend/frontend_main.py
A	frontend/gallery.html
D	frontend/groq-status.js
A	frontend/home-integration.css
M	frontend/index.html
D	frontend/kakao-sdk.js
A	frontend/location-picker.css
A	frontend/location-picker.js
D	frontend/map.js
A	frontend/readme.md
A	frontend/record_revision.py
A	frontend/screens.json
A	frontend/state.js
M	frontend/styles.css
A	frontend/upgrade.cjs
A	games/.gitignore
A	games/README.md
A	games/app.py
A	games/backend.test.mjs
A	games/dist/app.mjs
A	games/dist/assets/gacha-machine.png
A	games/dist/assets/logo.svg
A	games/dist/assets/option-draw.png
A	games/dist/assets/option-gacha.png
A	games/dist/assets/option-ladder.png
A	games/dist/assets/option-random.png
A	games/dist/assets/option-roulette.png
A	games/dist/assets/option-ticket.png
A	games/dist/backend.mjs
A	games/dist/data-layout.css
A	games/dist/engine.mjs
A	games/dist/game-integration.css
A	games/dist/index.html
A	games/dist/minimal-ui.css
A	games/dist/rooms.css
A	games/dist/rooms.mjs
A	games/dist/styles.css
A	games/dist/white-preview.css
A	games/network.mjs
A	games/network.test.mjs
A	games/qr.py
A	games/requirements.txt
A	games/room-store.mjs
A	games/room-store.test.mjs
A	games/server.mjs
A	games/start-demo.cmd
A	import_csv_stage3.py
A	inspect_supabase.py
A	kakao-map/app.js
A	kakao-map/business-hours-data.js
A	kakao-map/business-hours.js
A	kakao-map/cuisine-data.js
A	kakao-map/cuisine.js
A	kakao-map/data.js
A	kakao-map/geolocation-diagnostics.js
A	kakao-map/index.html
A	kakao-map/integration.js
A	kakao-map/location.js
A	kakao-map/map-integration.css
A	kakao-map/map-shell.js
A	kakao-map/menu-catalog-data.js
A	kakao-map/menu-catalog.css
A	kakao-map/menu-catalog.html
A	kakao-map/menu-catalog.js
A	kakao-map/menus.js
A	kakao-map/nearby-data.js
A	kakao-map/nearby-search.js
A	kakao-map/pin-overlaps.js
A	kakao-map/pj.code-workspace
A	kakao-map/routes.js
A	kakao-map/serve.py
A	kakao-map/styles.css
A	kakao-map/walk_routes.py
A	output/frontend_merge_stage2/distance-desktop.png
A	output/frontend_merge_stage2/distance-mobile.png
A	output/frontend_merge_stage2/location-desktop.png
A	output/frontend_merge_stage2/location-mobile.png
A	output/frontend_merge_stage2/merged-desktop.png
A	output/frontend_merge_stage2/merged-mobile.png
A	output/frontend_merge_stage2/reference-desktop.png
A	output/frontend_merge_stage2/reference-mobile.png
A	output/frontend_merge_stage3/merged-group-select-desktop.png
A	output/frontend_merge_stage3/merged-group-select-mobile.png
A	output/frontend_merge_stage3/merged-play-desktop.png
A	output/frontend_merge_stage3/merged-play-mobile.png
A	output/frontend_merge_stage3/merged-result-desktop.png
A	output/frontend_merge_stage3/merged-result-mobile.png
A	output/frontend_merge_stage3/merged-room-entry-desktop.png
A	output/frontend_merge_stage3/merged-room-entry-mobile.png
A	output/frontend_merge_stage3/merged-room-invite.png
A	output/frontend_merge_stage3/merged-room-lobby.png
A	output/frontend_merge_stage3/merged-select-desktop.png
A	output/frontend_merge_stage3/merged-select-mobile.png
A	output/frontend_merge_stage3/reference-play-desktop.png
A	output/frontend_merge_stage3/reference-play-mobile.png
A	output/frontend_merge_stage3/reference-select-desktop.png
A	output/frontend_merge_stage3/reference-select-mobile.png
A	output/frontend_merge_stage4/merged-empty-desktop.png
A	output/frontend_merge_stage4/merged-empty-mobile.png
A	output/frontend_merge_stage4/merged-error-desktop.png
A	output/frontend_merge_stage4/merged-error-mobile.png
A	output/frontend_merge_stage4/merged-loading-desktop.png
A	output/frontend_merge_stage4/merged-loading-mobile.png
A	output/frontend_merge_stage4/merged-proposal-desktop.png
A	output/frontend_merge_stage4/merged-proposal-mobile.png
A	output/frontend_merge_stage4/merged-thread-desktop.png
A	output/frontend_merge_stage4/merged-thread-mobile.png
A	output/frontend_merge_stage4/reference-desktop.png
A	output/frontend_merge_stage4/reference-mobile.png
A	output/frontend_merge_stage5/detail-desktop.png
A	output/frontend_merge_stage5/detail-mobile.png
A	output/frontend_merge_stage5/map-desktop.png
A	output/frontend_merge_stage5/map-mobile.png
A	output/frontend_merge_stage5/menu-desktop.png
A	output/frontend_merge_stage5/menu-mobile.png
A	output/live_connections/groq-chat.png
A	output/live_connections/kakao-map.png
A	output/live_connections/results.json
A	output/screenshots/ai-layout-fixed.jpg
A	output/screenshots/fixed-header-play.jpg
A	output/screenshots/gacha-compact-play.jpg
A	output/screenshots/gacha-play-updated.jpg
A	output/screenshots/game-no-scroll.jpg
A	output/screenshots/games-redesign.jpg
A	output/screenshots/group-games-without-intersection.jpg
A	output/screenshots/home-shared-header.jpg
A	output/screenshots/shared-guest-dialog.jpg
A	output/screenshots/shared-location-dialog.jpg
A	prepare_csv_stage3.py
A	report_hours_stage4.py
M	requirements.txt
A	tests/chat-harness.cjs
M	tests/chat-session-ui.test.cjs
A	tests/frontend-contract.test.cjs
M	tests/groq-status.test.cjs
M	tests/location-flow.test.cjs
A	tests/map-sdk-stub.js
M	tests/map.test.cjs
M	tests/restaurant-ui.test.cjs
A	tests/shared-state.test.cjs
A	tests/test_ai_design.py
A	tests/test_chat_browser_flow.py
M	tests/test_database.py
A	tests/test_db_first_browser.py
A	tests/test_db_first_flow.py
A	tests/test_frontend_static.py
A	tests/test_game_browser_flow.py
A	tests/test_game_design.py
A	tests/test_games_proxy.py
A	tests/test_home_design.py
A	tests/test_location_browser_flow.py
A	tests/test_map_design.py
A	tests/test_map_details.py
A	tests/test_map_routes.py
M	tests/test_menu_catalog.py
M	tests/test_recommendations.py
```
