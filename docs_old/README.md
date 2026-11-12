# 이전 구현 문서 보관함

- 분류일: 2026-11-10
- 기준: 현재 소스의 실제 파일 경로, 의도 계약, DB 추천, 세션, 스트리밍 동작과 비교

아래 13개 문서는 현재 코드와 어긋나는 설명 또는 현재 정상 기준으로 사용하기 어려운 수치를 포함하여 옮겼습니다. 파일 내용은 당시 기록을 유지하며, 원래 상대 경로를 이 폴더 아래에 보존했습니다. 삭제한 문서는 없습니다.

현재 사용 안내는 [프로젝트 README](../README.md), [백엔드·DB 점검 가이드](../BACKEND_DB_GUIDE.md), [챗봇 가드레일 가이드](../CHATBOT_GUARDRAIL_GUIDE_v1.md)를 참고하세요.

| 보관 문서 | 이동 사유 |
|---|---|
| [README_demo.md](README_demo.md) | 새로고침 후 대화·조건 초기화, 예시 메뉴 중심 경로 등 이전 동작을 설명 |
| [CHAT_POLICY_GUIDE.md](CHAT_POLICY_GUIDE.md) | 현재 미사용 프롬프트 파일과 삭제된 `services.MENUS`, `eligible_menus`를 수정 대상으로 안내 |
| [GUARDRAIL_VALIDATION.md](GUARDRAIL_VALIDATION.md) | 2026-11-08의 재시도 없는 이전 가드레일·테스트 기록 |
| [INTEGRATION_QA.md](INTEGRATION_QA.md) | 상세 메뉴·가격 미검증 등 이전 데모의 통합 결과와 점검 기준 |
| [chatbot_policy_v1.md](docs/chatbot_policy_v1.md) | 임시 메뉴 배열 사용을 현재 구현으로 설명하고 이후 기능을 계획으로 기술 |
| [chatbot_policy_v2.md](docs/chatbot_policy_v2.md) | DB 식당 후속답변을 아직 다음 단계 작업으로 설명 |
| [chatbot_policy_v3.md](docs/chatbot_policy_v3.md) | 스트리밍·스피너를 아직 다음 단계 범위로 설명하는 이전 정책 |
| [chat_session_design_v1.md](docs/chat_session_design_v1.md) | pending 모델만 준비됐고 Groq 연결은 미구현이라고 설명 |
| [groq_guardrail_design_v1.md](docs/groq_guardrail_design_v1.md) | 이전 replies_v2 적용 경로와 DB 후속답변 연결 전 상태를 설명 |
| [step2_menu_catalog_verification_v1.md](docs/step2_menu_catalog_verification_v1.md) | 특정 당시 DB 행 수와 초기 카탈로그 수를 현재 확인 기준으로 제시 |
| [step3_chat_session_verification_v1.md](docs/step3_chat_session_verification_v1.md) | 현재 늘어난 테스트와 다른 고정 통과 개수를 정상 기준으로 제시 |
| [step4_groq_guardrail_verification_v1.md](docs/step4_groq_guardrail_verification_v1.md) | 식당 DB 사실 답변이 나오지 않는 것을 정상으로 안내 |
| [step5_db_chat_verification_v1.md](docs/step5_db_chat_verification_v1.md) | 화면 채팅을 일반 `/api/chat` 기준으로 확인하며 스트리밍을 미구현으로 설명 |

단순히 파일의 버전이 v1이거나 검증 결과가 과거 기록이라는 이유만으로 모두 옮기지는 않았습니다. 현재 코드와 일치하는 메뉴 카탈로그·DB 실행·스트리밍·마이그레이션·운영 설계와 최신 단계 검증 문서는 `docs`에 유지했습니다.

보관본 내부의 파일명과 실행 명령은 당시 기준이며 자동으로 현재 버전에 맞춰 변경하지 않았습니다. 내용을 재사용하려면 최신 코드와 대조하세요.
