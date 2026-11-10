"""7단계: Redis 전환 전 사용할 세션별 메모리 채팅 요청 제한."""

from __future__ import annotations

import asyncio
from collections import deque
from collections.abc import Callable
from dataclasses import dataclass
from time import monotonic


@dataclass(frozen=True, slots=True)
class RateLimitResult:
    """요청 허용 여부와 거부 시 다시 시도할 때까지의 초."""

    allowed: bool
    retry_after: int = 0


class InMemoryChatRateLimiter:
    """한 프로세스 안에서 UUID 세션별 분·일 요청 횟수를 제한한다.

    운영 환경에서 여러 서버 인스턴스를 사용하면 같은 인터페이스를 Redis 기반
    구현으로 교체해야 한다. 사용자 질문이나 위치는 저장하지 않는다.
    """

    def __init__(
        self,
        per_minute: int,
        per_day: int,
        *,
        clock: Callable[[], float] = monotonic,
    ) -> None:
        if per_minute < 1 or per_day < 1:
            raise ValueError("요청 제한은 1 이상이어야 합니다.")
        self._per_minute = per_minute
        self._per_day = per_day
        self._clock = clock
        self._events: dict[str, deque[float]] = {}
        self._lock = asyncio.Lock()

    async def check(self, session_id: str) -> RateLimitResult:
        """만료 기록을 제거한 뒤 허용된 요청만 현재 시각으로 기록한다."""

        now = self._clock()
        async with self._lock:
            # 다시 방문하지 않는 세션의 오래된 기록도 남지 않게 전체 키를 정리한다.
            for key, history in list(self._events.items()):
                while history and now - history[0] >= 86_400:
                    history.popleft()
                if not history:
                    del self._events[key]
            events = self._events.setdefault(session_id, deque())

            minute_events = [value for value in events if now - value < 60]
            if len(minute_events) >= self._per_minute:
                retry = max(1, int(60 - (now - minute_events[0])) + 1)
                return RateLimitResult(False, retry)
            if len(events) >= self._per_day:
                retry = max(1, int(86_400 - (now - events[0])) + 1)
                return RateLimitResult(False, retry)

            events.append(now)
            return RateLimitResult(True)

    async def clear(self) -> None:
        """테스트 종료와 서버 종료 시 메모리 참조를 정리한다."""

        async with self._lock:
            self._events.clear()
