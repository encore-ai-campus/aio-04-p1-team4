# 프로젝트 문서

기준일: 2026-11-16. 현재 코드의 설계·관리·운영 문서를 안내한다.

| 구분 | 문서 | 내용 |
| :---: | :---: | :---: |
| 소개 | [프로젝트 README](../README.md) | 기능·팀 정보·시연·구조·실행 방법 |
| 소개 | [소개 PDF](대시보드_구현결과물_LUNCHRUN.pdf) | 프로젝트 소개와 주요 화면 |
| 코드 | [코드 가이드](CURRENT_GUIDE_v1.md) | 주요 파일과 기능별 수정 위치 |
| API | [Markdown](API_DESIGN_v1.md) / [PDF](API설계서_LUNCHRUN.pdf) | 요청·응답·오류·화면 연결 |
| DB | [Markdown](DB_DESIGN_v1.md) / [PDF](DB설계서_LUNCHRUN.pdf) | 테이블·ERD·추천 데이터 판정·접근 관리 |
| 화면 | [화면설계서](화면설계서_LUNCHRUN.pdf) | 화면 구성과 변경 이력 |
| 관리 | [대표 메뉴 수동 관리](seed_management_v2.md) | seed 명령의 대상 DB·동기화·비활성화 |
| 관리 | [음식 종류 매핑](food_conditions_v3.md) | 화면 분류와 식당 원본 업태의 대응 |
| 운영 | [DB 마이그레이션](database_migration_guide_v1.md) | Supabase 스키마·버전·적용 전제조건 |
| 운영 | [운영 점검표](operations_checklist_v1.md) | 환경변수·상태·연결·장애 점검 |

API·DB의 Markdown과 PDF는 같은 내용을 기준으로 관리한다. 화면설계서는 변경 이력을 포함하며 거리 조절 단위는 현재 코드와 같은 50m다.

데이터 구축·당시 검증 기록은 [과거 기록 목록](../docs_old/README.md)에 구분해 보관한다. 당시 행 수·모델·설정·테스트 결과를 현재 운영 상태로 해석하지 않는다.
