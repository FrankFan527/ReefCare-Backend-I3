import asyncio
import time
from collections import defaultdict, deque

from fastapi import Request

from app.core.config import settings
from app.core.exceptions import RateLimitError


class InMemoryRateLimiter:
    """
    Lightweight Iteration 1 rate limiter.

    This limiter is process-local and is suitable for the
    current MVP/single-instance deployment.

    If ReefCare later runs across multiple application
    instances, replace the backing store with a shared
    system such as Redis.
    """

    def __init__(
        self,
        max_requests: int,
        window_seconds: int,
    ):
        self.max_requests = max_requests
        self.window_seconds = window_seconds

        self._requests: dict[
            str,
            deque[float],
        ] = defaultdict(deque)

        self._lock = asyncio.Lock()

    async def check(
        self,
        key: str,
    ) -> None:
        now = time.monotonic()
        window_start = (
            now - self.window_seconds
        )

        async with self._lock:
            timestamps = self._requests[key]

            while (
                timestamps
                and timestamps[0] <= window_start
            ):
                timestamps.popleft()

            if (
                len(timestamps)
                >= self.max_requests
            ):
                oldest = timestamps[0]

                retry_after = max(
                    1,
                    int(
                        self.window_seconds
                        - (now - oldest)
                    )
                    + 1,
                )

                raise RateLimitError(
                    retry_after=retry_after,
                )

            timestamps.append(now)

            if not timestamps:
                self._requests.pop(
                    key,
                    None,
                )


login_limiter = InMemoryRateLimiter(
    max_requests=(
        settings.login_rate_limit_requests
    ),
    window_seconds=(
        settings.login_rate_limit_window_seconds
    ),
)


def get_client_identifier(
    request: Request,
) -> str:
    """
    Return a minimal client identifier for the MVP limiter.

    Do not use or log credentials, JWT values or request
    bodies as rate-limit identifiers.
    """

    if request.client is None:
        return "unknown"

    return request.client.host


async def apply_login_rate_limit(
    request: Request,
) -> None:
    client_id = get_client_identifier(
        request
    )

    await login_limiter.check(
        key=f"login:{client_id}",
    )