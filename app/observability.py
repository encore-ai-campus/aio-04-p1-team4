"""7단계: 민감정보 없이 요청 단위로 추적 가능한 JSON 로그."""

from __future__ import annotations

import json
import logging
from contextvars import ContextVar
from datetime import datetime, timezone
from uuid import UUID, uuid4


request_id_context: ContextVar[str] = ContextVar("request_id", default="-")


def request_id_from_header(value: str | None) -> str:
    """UUID 형식의 요청 ID만 재사용하고 나머지는 서버에서 새로 만든다."""

    if value:
        try:
            return str(UUID(value))
        except (ValueError, AttributeError):
            pass
    return str(uuid4())


class JsonFormatter(logging.Formatter):
    """운영 수집기가 읽을 수 있는 한 줄 JSON 로그 포맷."""

    _allowed = {
        "event",
        "method",
        "path",
        "status_code",
        "duration_ms",
        "error_code",
        "searched_count",
        "collected_count",
        "cached_count",
        "recommended_count",
        "candidate_count",
    }

    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "request_id": request_id_context.get(),
        }
        for key in self._allowed:
            value = getattr(record, key, None)
            if value is not None:
                payload[key] = value
        return json.dumps(payload, ensure_ascii=False, separators=(",", ":"))


def configure_logging() -> logging.Logger:
    """LunchRun 로거에만 핸들러를 붙여 타 라이브러리 로그를 덮어쓰지 않는다."""

    logger = logging.getLogger("lunchrun")
    if not logger.handlers:
        handler = logging.StreamHandler()
        handler.setFormatter(JsonFormatter())
        logger.addHandler(handler)
    logger.setLevel(logging.INFO)
    logger.propagate = False
    return logger
