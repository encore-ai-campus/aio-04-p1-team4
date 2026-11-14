"""서버 실행 위치와 관계없이 프로젝트 루트에서 읽는 환경설정."""
import os
from pathlib import Path

from dotenv import load_dotenv
from pydantic import BaseModel, ConfigDict, Field, SecretStr


ENV_FILE = Path(__file__).resolve().parent.parent / ".env"
PROJECT_ROOT = ENV_FILE.parent
DEFAULT_DATABASE_URL = f"sqlite:///{(PROJECT_ROOT / 'data' / 'lunchrun.db').as_posix()}"


class Settings(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    map_api_key: SecretStr
    # 지도 SDK용 공개 키입니다. REST 키와 분리하며, 미설정 시 SDK 로딩을 생략합니다.
    kakao_javascript_key: str = ""
    # Gemini 키가 없어도 지도는 실행되며 실제 AI 호출 시에만 누락 오류를 반환합니다.
    gemini_api_key: SecretStr = Field(default=SecretStr(""), repr=False)
    gemini_model: str = Field(default="gemini-3.5-flash-lite", min_length=1)
    gemini_timeout_seconds: float = Field(default=30, gt=0, le=120, allow_inf_nan=False)
    # 5단계: 설명 생성만 비활성화하거나 짧은 제한시간을 둘 수 있다. 질문 해석은 유지한다.
    gemini_narration_enabled: bool = True
    gemini_narration_timeout_seconds: float = Field(default=8, gt=0, le=30, allow_inf_nan=False)
    # Gemini는 사고(thinking) 토큰도 출력 한도에 포함하므로 넉넉한 기본값을 사용한다.
    gemini_max_completion_tokens: int = Field(default=2048, ge=128, le=8192)
    # 현재는 메모리 세션이며 쿠키 수명과 메모리 만료시간에 같은 값을 사용한다.
    chat_session_ttl_seconds: int = Field(default=86400, ge=60, le=604800)
    # 상세정보는 정상 결과와 실패 결과의 재시도 주기를 분리해 불필요한 브라우저 수집을 줄인다.
    detail_success_ttl_hours: int = Field(default=168, ge=1, le=720)
    detail_failure_retry_minutes: int = Field(default=60, ge=1, le=1440)
    # Redis 도입 전 단일 프로세스에서 세션별 채팅 과다 요청을 제한한다.
    chat_requests_per_minute: int = Field(default=10, ge=1, le=120)
    chat_requests_per_day: int = Field(default=100, ge=1, le=10000)
    max_request_bytes: int = Field(default=65536, ge=1024, le=1048576)
    # 로컬 HTTP는 False, HTTPS 배포 환경은 True로 설정한다.
    cookie_secure: bool = False
    # 3단계에서는 SQLite를 기본값으로 사용하고, 추후 DATABASE_URL만 바꿔 PostgreSQL로 전환한다.
    database_url: str = Field(default=DEFAULT_DATABASE_URL, min_length=1)


def load_settings() -> Settings:
    # 배포 환경변수가 로컬 .env보다 우선한다.
    load_dotenv(dotenv_path=ENV_FILE, override=False)
    map_api_key = os.environ.get("MAP_API_KEY", "").strip()
    if not map_api_key:
        # 설정 오류 메시지에는 실제 인증키 값을 절대 포함하지 않는다.
        raise RuntimeError(
            "MAP_API_KEY가 없거나 비어 있습니다. 프로젝트 루트의 .env "
            "또는 서버 환경변수에 카카오 REST API 키를 설정해 주세요."
        )
    # .env에 선택적으로 추가한 JavaScript 키만 읽습니다. 기존 REST 키는 재사용하지 않습니다.
    return Settings(
        map_api_key=map_api_key,
        kakao_javascript_key=os.environ.get("KAKAO_JAVASCRIPT_KEY", "").strip(),
        # 기존 환경변수가 있으면 .env보다 우선하며 변경 후 서버를 재시작해야 합니다.
        gemini_api_key=os.environ.get("GEMINI_API_KEY", "").strip(),
        gemini_narration_enabled=os.environ.get('GEMINI_NARRATION_ENABLED','true').lower()=='true',
        gemini_narration_timeout_seconds=os.environ.get('GEMINI_NARRATION_TIMEOUT_SECONDS','8'),
        gemini_model=os.environ.get("GEMINI_MODEL", "gemini-3.5-flash-lite").strip(),
        gemini_timeout_seconds=os.environ.get("GEMINI_TIMEOUT_SECONDS", "30"),
        gemini_max_completion_tokens=os.environ.get("GEMINI_MAX_COMPLETION_TOKENS", "2048"),
        chat_session_ttl_seconds=os.environ.get("CHAT_SESSION_TTL_SECONDS", "86400"),
        detail_success_ttl_hours=os.environ.get("DETAIL_SUCCESS_TTL_HOURS", "168"),
        detail_failure_retry_minutes=os.environ.get(
            "DETAIL_FAILURE_RETRY_MINUTES", "60"
        ),
        chat_requests_per_minute=os.environ.get("CHAT_REQUESTS_PER_MINUTE", "10"),
        chat_requests_per_day=os.environ.get("CHAT_REQUESTS_PER_DAY", "100"),
        max_request_bytes=os.environ.get("MAX_REQUEST_BYTES", "65536"),
        cookie_secure=os.environ.get("COOKIE_SECURE", "false").lower() == "true",
        database_url=(os.environ.get("DATABASE_URL") or os.environ.get("SUPABASE_DB_URL") or DEFAULT_DATABASE_URL).strip(),
    )
