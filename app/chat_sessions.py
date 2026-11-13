"""3단계: 최근 대화와 현재 추천 상태를 보관하는 메모리 세션."""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from datetime import datetime, timezone
from time import monotonic
from typing import Literal
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field

from .schemas import Conditions, SelectedLocation


SESSION_COOKIE_NAME = "lunchrun_session"
MAX_CHAT_TURNS = 10


class ConversationTurn(BaseModel):
    """사용자 질문과 챗봇 답변 한 쌍을 한 턴으로 저장한다."""

    model_config = ConfigDict(extra="forbid")

    user_message: str = Field(min_length=1, max_length=500)
    assistant_message: str = Field(min_length=1, max_length=5000)
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class PendingAction(BaseModel):
    """추가 입력이 필요한 질문의 종류와 안전한 문맥만 보관한다."""

    model_config = ConfigDict(extra="forbid")

    kind: Literal[
        "change_radius",
        "change_budget",
        "select_restaurant",
        "unsupported_input",
    ]
    original_message: str = Field(min_length=1, max_length=500)
    current_value: int | None = None
    restaurant_ids: list[str] = Field(default_factory=list, max_length=15)


class ChatSessionState(BaseModel):
    """최근 10턴과 턴 수명보다 오래 유지할 현재 추천 상태."""

    model_config = ConfigDict(extra="forbid")

    turns: list[ConversationTurn] = Field(default_factory=list)
    conditions: Conditions | None = None
    location: SelectedLocation | None = None
    radius_m: int | None = Field(default=None, ge=50, le=500)
    selected_menu_id: str | None = Field(default=None, max_length=40)
    recent_menu_ids: list[str] = Field(default_factory=list, max_length=10)
    restaurant_ids: list[str] = Field(default_factory=list, max_length=15)
    candidate_restaurant_ids: list[str] = Field(default_factory=list, max_length=15)
    pending_action: PendingAction | None = None
    last_intent: str | None = Field(default=None, max_length=50)
    version: int = Field(default=0, ge=0)

    def record_exchange(
        self,
        *,
        user_message: str,
        assistant_message: str,
        conditions: Conditions,
        location: SelectedLocation,
        radius_m: int,
        requested_menu_id: str | None,
        response: dict,
        pending_action: dict | None = None,
        clear_pending: bool = False,
        last_intent: str | None = None,
    ) -> None:
        """성공한 API 응답과 그 시점의 화면 조건을 하나의 변경으로 기록한다."""

        changed = (self.conditions is not None and
            (self.conditions.budget != conditions.budget or self.conditions.cuisine != conditions.cuisine))
        changed = changed or (self.location is not None and
            (self.location.lat != location.lat or self.location.lng != location.lng))
        changed = changed or (self.radius_m is not None and self.radius_m != radius_m)
        changed = changed or (requested_menu_id is not None and requested_menu_id != self.selected_menu_id)
        if changed:
            self.selected_menu_id = requested_menu_id
            self.restaurant_ids = []
            self.candidate_restaurant_ids = []
            self.pending_action = None
        self.conditions = conditions.model_copy(deep=True)
        self.location = location.model_copy(deep=True)
        self.radius_m = radius_m
        if requested_menu_id:
            self.selected_menu_id = requested_menu_id

        result = response.get("result")
        if isinstance(result, dict):
            menu = result.get("menu")
            if menu is None:
                self.selected_menu_id = None
            if isinstance(menu, dict) and isinstance(menu.get("id"), str):
                self.selected_menu_id = menu["id"]
                # 최근 메뉴는 중복을 제거한 뒤 최신 항목이 마지막에 오도록 보관한다.
                self.recent_menu_ids = [
                    value for value in self.recent_menu_ids if value != menu["id"]
                ]
                self.recent_menu_ids.append(menu["id"])
                self.recent_menu_ids = self.recent_menu_ids[-10:]
            self.restaurant_ids = _result_ids(result.get("restaurants"))
            self.candidate_restaurant_ids = _result_ids(
                result.get("candidate_restaurants")
            )
            self.last_intent = last_intent or "recommend"
        elif response.get("suggested_patch"):
            self.last_intent = last_intent or "change_conditions"
        else:
            self.last_intent = last_intent or "chat"

        if clear_pending:
            self.pending_action = None
        if pending_action is not None:
            # Groq 원문이 아니라 서버가 만든 제한된 pending 구조만 저장한다.
            self.pending_action = PendingAction.model_validate(pending_action)

        self.turns.append(
            ConversationTurn(
                user_message=user_message,
                assistant_message=assistant_message,
            )
        )
        # 질문과 답변 한 쌍을 한 턴으로 보고 최신 10턴만 Groq 문맥 후보로 남긴다.
        self.turns = self.turns[-MAX_CHAT_TURNS:]
        self.version += 1


def _result_ids(value) -> list[str]:
    """외부 응답 객체에서 유효한 식당 ID만 순서를 보존해 추출한다."""

    if not isinstance(value, list):
        return []
    result: list[str] = []
    for item in value:
        if isinstance(item, dict) and isinstance(item.get("id"), str):
            if item["id"] not in result:
                result.append(item["id"])
    return result[:15]


def valid_session_id(value: str | None) -> str | None:
    """서버가 발급한 형식과 같은 UUID4 쿠키만 세션 키로 사용한다."""

    if not value:
        return None
    try:
        parsed = UUID(value)
    except (ValueError, AttributeError):
        return None
    return str(parsed) if parsed.version == 4 else None


def new_session_id() -> str:
    """로그인 전 브라우저를 구분할 예측하기 어려운 세션 ID를 만든다."""

    return str(uuid4())


class InMemoryChatSessionStore:
    """현재 프로세스 안에서만 유지되는 개발용 세션 저장소.

    서버 재시작과 ``uvicorn --reload`` 시 데이터가 사라진다. 공개 메서드는 깊은
    복사본을 사용해 요청 코드가 잠금 밖에서 저장 상태를 직접 바꾸지 못하게 한다.
    """

    def __init__(
        self,
        ttl_seconds: int = 86_400,
        *,
        clock: Callable[[], float] = monotonic,
    ):
        if ttl_seconds < 60:
            raise ValueError("세션 만료시간은 60초 이상이어야 합니다.")
        self._ttl_seconds = ttl_seconds
        self._clock = clock
        self._sessions: dict[str, tuple[ChatSessionState, float]] = {}
        self._lock = asyncio.Lock()

    async def get(self, session_id: str) -> ChatSessionState | None:
        """유효한 상태의 깊은 복사본을 반환하고 만료 세션은 즉시 제거한다."""

        async with self._lock:
            stored = self._sessions.get(session_id)
            if stored is None:
                return None
            state, expires_at = stored
            if expires_at <= self._clock():
                del self._sessions[session_id]
                return None
            return state.model_copy(deep=True)

    async def record_exchange(
        self,
        session_id: str,
        *,
        user_message: str,
        assistant_message: str,
        conditions: Conditions,
        location: SelectedLocation,
        radius_m: int,
        requested_menu_id: str | None,
        response: dict,
        pending_action: dict | None = None,
        clear_pending: bool = False,
        last_intent: str | None = None,
    ) -> ChatSessionState:
        """같은 세션의 동시 변경을 잠금 안에서 한 번에 적용한다."""

        async with self._lock:
            stored = self._sessions.get(session_id)
            if stored is None or stored[1] <= self._clock():
                state = ChatSessionState()
            else:
                state = stored[0].model_copy(deep=True)
            state.record_exchange(
                user_message=user_message,
                assistant_message=assistant_message,
                conditions=conditions,
                location=location,
                radius_m=radius_m,
                requested_menu_id=requested_menu_id,
                response=response,
                pending_action=pending_action,
                clear_pending=clear_pending,
                last_intent=last_intent,
            )
            self._sessions[session_id] = (
                state,
                self._clock() + self._ttl_seconds,
            )
            return state.model_copy(deep=True)

    async def put(self, session_id: str, state: ChatSessionState) -> None:
        """테스트와 이후 가드레일 단계가 준비한 상태를 검증 후 저장한다."""

        checked = ChatSessionState.model_validate(state.model_dump())
        async with self._lock:
            self._sessions[session_id] = (
                checked.model_copy(deep=True),
                self._clock() + self._ttl_seconds,
            )

    async def clear(self) -> None:
        """테스트 종료나 서버 수명 종료 시 메모리 참조를 정리한다."""

        async with self._lock:
            self._sessions.clear()
