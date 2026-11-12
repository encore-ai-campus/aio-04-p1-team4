"""API 키나 웹 서버 없이도 DB 초기화·저장·조회를 실행하는 진입점."""
from app.database.cli import main

if __name__ == '__main__':
    raise SystemExit(main())
