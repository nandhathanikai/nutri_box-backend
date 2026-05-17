"""Simple in-memory IP-based rate limiter.

Good enough for single-instance deployments. For horizontal scale, swap the
in-process dict for Redis with TTL keys (e.g. via redis-py INCR + EXPIRE).
"""
from __future__ import annotations
import threading
import time
from collections import defaultdict, deque
from typing import Deque

from fastapi import HTTPException, Request, status

_lock = threading.Lock()
_buckets: dict[str, Deque[float]] = defaultdict(deque)


def _client_ip(request: Request) -> str:
    # Behind a proxy, X-Forwarded-For may carry the real IP. Take the first hop.
    fwd = request.headers.get("x-forwarded-for")
    if fwd:
        return fwd.split(",")[0].strip()
    if request.client and request.client.host:
        return request.client.host
    return "unknown"


def rate_limit(*, max_calls: int, period_seconds: int, scope: str = "default"):
    """Build a FastAPI dependency that allows at most `max_calls` per IP per `period_seconds`.

    Usage:  @router.post("/login", dependencies=[Depends(rate_limit(max_calls=5, period_seconds=60, scope="login"))])
    """
    def _dep(request: Request):
        ip = _client_ip(request)
        key = f"{scope}:{ip}"
        now = time.monotonic()
        cutoff = now - period_seconds

        with _lock:
            bucket = _buckets[key]
            while bucket and bucket[0] < cutoff:
                bucket.popleft()

            if len(bucket) >= max_calls:
                retry_after = int(bucket[0] + period_seconds - now) + 1
                raise HTTPException(
                    status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                    detail=f"Too many requests. Try again in {retry_after}s.",
                    headers={"Retry-After": str(retry_after)},
                )

            bucket.append(now)

    return _dep
