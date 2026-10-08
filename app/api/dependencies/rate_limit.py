import asyncio
import time
from collections import (
    defaultdict,
    deque,
)

from fastapi import Request

from app.core.config import settings
from app.core.exceptions import RateLimitError


class InMemoryRateLimiter:
    """
    Lightweight process-local rate limiter.

    Suitable for the current ReefCare MVP deployment.

    If ReefCare later runs across multiple application
    instances, the backing store should move to a shared
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
        ] = defaultdict(
            deque
        )

        self._lock = (
            asyncio.Lock()
        )

    async def check(
        self,
        key: str,
    ) -> None:
        now = (
            time.monotonic()
        )

        window_start = (
            now
            - self.window_seconds
        )

        async with self._lock:
            timestamps = (
                self._requests[
                    key
                ]
            )

            while (
                timestamps
                and timestamps[0]
                <= window_start
            ):
                timestamps.popleft()

            if (
                len(timestamps)
                >= self.max_requests
            ):
                oldest = (
                    timestamps[0]
                )

                retry_after = max(
                    1,
                    int(
                        self.window_seconds
                        - (
                            now
                            - oldest
                        )
                    )
                    + 1,
                )

                raise RateLimitError(
                    retry_after=(
                        retry_after
                    ),
                )

            timestamps.append(
                now
            )


login_limiter = (
    InMemoryRateLimiter(
        max_requests=(
            settings
            .login_rate_limit_requests
        ),

        window_seconds=(
            settings
            .login_rate_limit_window_seconds
        ),
    )
)


smart_report_limiter = (
    InMemoryRateLimiter(
        max_requests=(
            settings
            .smart_report_rate_limit_requests
        ),

        window_seconds=(
            settings
            .smart_report_rate_limit_window_seconds
        ),
    )
)


# US9.4 has its own public limiter.
#
# It must not share a bucket with Smart Report or Visual
# Recognition because those features are authenticated and
# keyed by Observer id, whereas Planning Brief is public
# and therefore uses the requesting client identifier.
planning_brief_limiter = (
    InMemoryRateLimiter(
        max_requests=(
            settings
            .planning_brief_rate_limit_requests
        ),

        window_seconds=(
            settings
            .planning_brief_rate_limit_window_seconds
        ),
    )
)


def get_client_identifier(
    request: Request,
) -> str:
    """
    Return the minimal client identifier used by public
    and authentication rate limits.

    Credentials, JWT values and request bodies are never
    used as rate-limit keys.
    """

    if request.client is None:
        return "unknown"

    return request.client.host


async def apply_login_rate_limit(
    request: Request,
) -> None:
    client_id = (
        get_client_identifier(
            request
        )
    )

    await login_limiter.check(
        key=(
            f"login:{client_id}"
        ),
    )


async def apply_planning_brief_rate_limit(
    request: Request,
) -> None:
    """
    Protect the public Gemini-backed Planning Brief
    endpoint from unbounded repeated requests.

    Rate-limit failure is handled through the existing
    RateLimitError contract:

        HTTP 429
        Retry-After
    """

    client_id = (
        get_client_identifier(
            request
        )
    )

    await (
        planning_brief_limiter
        .check(
            key=(
                "planning-brief:"
                + client_id
            ),
        )
    )