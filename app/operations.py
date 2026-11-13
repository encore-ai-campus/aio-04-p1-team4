"""7단계: 외부 사용량을 소비하지 않는 운영 준비 상태 점검."""

from __future__ import annotations

from pathlib import Path

from playwright.sync_api import Error as PlaywrightError
from playwright.sync_api import sync_playwright
from sqlalchemy import func, select, text

from .config import Settings
from .database import Database, MenuCatalog


def _playwright_browser_available() -> bool:
    """브라우저를 실행하지 않고 설치된 Chromium 실행 파일 존재만 확인한다."""

    try:
        with sync_playwright() as manager:
            return Path(manager.chromium.executable_path).is_file()
    except (PlaywrightError, OSError):
        return False


def readiness_report(database: Database, settings: Settings) -> tuple[dict, int]:
    """DB·메뉴·브라우저·필수 설정을 점검하고 응답과 HTTP 상태를 반환한다."""

    checks: dict[str, object] = {
        "database": False,
        "menu_catalog": False,
        "menu_catalog_count": 0,
        "playwright_chromium": False,
        "kakao_configured": bool(settings.map_api_key.get_secret_value()),
        "groq_configured": bool(settings.groq_api_key.get_secret_value()),
    }
    try:
        with database.session_factory() as session:
            session.execute(text("SELECT 1"))
            count = session.scalar(
                select(func.count())
                .select_from(MenuCatalog)
                .where(MenuCatalog.active.is_(True))
            ) or 0
        checks["database"] = True
        checks["menu_catalog_count"] = count
        checks["menu_catalog"] = count > 0
    except Exception:
        # 연결 문자열과 DB 오류 원문은 상태 응답에 포함하지 않는다.
        pass

    checks["playwright_chromium"] = _playwright_browser_available()
    required = [
        checks["database"],
        checks["menu_catalog"],
        checks["kakao_configured"],
        checks["groq_configured"],
    ]
    ready = all(value is True for value in required)
    return {
        "status": "ready" if ready else "not_ready",
        "database_backend": database.engine.dialect.name,
        "recommendation_source": "database",
        "optional_checks": ["playwright_chromium"],
        "checks": checks,
    }, (200 if ready else 503)
