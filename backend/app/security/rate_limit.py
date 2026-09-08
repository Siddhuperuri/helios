"""Distributed rate limiting.

The limiter this replaced counted in a Python dictionary. With one process that is
correct. With three behind a load balancer it is not: round-robin routing hands a client
three independent budgets, which is the same as having no limit at all if the client makes
four requests.

    Request #1 → Backend 1     Request #3 → Backend 3
    Request #2 → Backend 2     Request #4 → Backend 1

Counters therefore live in Redis, keyed by client and by a window index derived from the
clock. Every replica computes the same key for the same client at the same moment, so
there is one budget no matter where a request lands.

Behaviour when Redis is unreachable
-----------------------------------
Requests are allowed. That looks like the wrong call for a security control, so it is
worth being explicit: an instance that cannot reach Redis also fails its readiness probe,
and the load balancer stops sending it traffic within a few seconds. Failing closed would
mean a Redis blip returns 429 to every user of a solar calculator; failing open means a
few seconds of unlimited requests to an instance that is already being drained. The
failure is counted as a metric and logged so it cannot pass unnoticed.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass

from app.infra import redis_client

logger = logging.getLogger(__name__)

_degraded_logged = False


@dataclass(frozen=True)
class RateLimitResult:
    allowed: bool
    limit: int
    remaining: int
    retry_after_s: int
    reset_at: int
    # True when the check could not be performed. Callers treat it as allowed, but the
    # middleware records it so a silent loss of limiting is visible in the metrics.
    degraded: bool = False

    def headers(self) -> dict[str, str]:
        """Standard rate-limit headers, so a well-behaved client can pace itself."""
        out = {
            "X-RateLimit-Limit": str(self.limit),
            "X-RateLimit-Remaining": str(max(0, self.remaining)),
            "X-RateLimit-Reset": str(self.reset_at),
        }
        if not self.allowed:
            out["Retry-After"] = str(self.retry_after_s)
        return out


def check(bucket: str, identity: str, *, limit: int, window_s: int) -> RateLimitResult:
    """Count one request against ``identity``'s budget in ``bucket``.

    Buckets are independent namespaces — the general API budget, the login budget, the
    verification-resend budget — so exhausting one does not consume another.
    """
    global _degraded_logged

    now = time.time()
    window_index = int(now // window_s)
    reset_at = int((window_index + 1) * window_s)
    key = redis_client.key("rl", bucket, identity, window_index)

    try:
        client = redis_client.get_client()
        pipeline = client.pipeline(transaction=False)
        pipeline.incr(key)
        # Set unconditionally rather than only on the first hit. The key already carries
        # the window index, so it is meaningless outside that window; refreshing the TTL
        # only means it is reclaimed a second after the last hit instead of a second after
        # the first. Doing it this way removes the race where a process dies between INCR
        # and EXPIRE and leaves a key with no TTL at all.
        pipeline.expire(key, window_s + 1)
        count = int(pipeline.execute()[0])
    except Exception as exc:  # noqa: BLE001 - see the module docstring
        if not _degraded_logged:
            logger.error(
                "Rate limiting is degraded: the shared counter store is unreachable "
                "(%s: %s). Requests are being allowed; this instance should be failing "
                "its readiness probe.",
                type(exc).__name__,
                exc,
            )
            _degraded_logged = True
        return RateLimitResult(
            allowed=True,
            limit=limit,
            remaining=limit,
            retry_after_s=0,
            reset_at=reset_at,
            degraded=True,
        )

    if count > limit:
        return RateLimitResult(
            allowed=False,
            limit=limit,
            remaining=0,
            retry_after_s=max(1, reset_at - int(now)),
            reset_at=reset_at,
        )
    return RateLimitResult(
        allowed=True,
        limit=limit,
        remaining=limit - count,
        retry_after_s=0,
        reset_at=reset_at,
    )


def peek(bucket: str, identity: str, *, window_s: int) -> int:
    """How many requests are already counted in the current window. Does not consume one."""
    window_index = int(time.time() // window_s)
    key = redis_client.key("rl", bucket, identity, window_index)
    try:
        raw = redis_client.get_client().get(key)
        return int(raw) if raw else 0
    except Exception:  # noqa: BLE001
        return 0


def reset(bucket: str, identity: str, *, window_s: int) -> None:
    """Clear one identity's counter. Used after a successful login, and by tests.

    Clearing on success is deliberate: the login limit exists to slow down guessing, and
    somebody who has just proved they know the password is not guessing. Without this, a
    person who mistypes their password nine times and then gets it right is still locked
    out of their next login.
    """
    window_index = int(time.time() // window_s)
    key = redis_client.key("rl", bucket, identity, window_index)
    try:
        redis_client.get_client().delete(key)
    except Exception:  # noqa: BLE001
        pass


def cooldown(bucket: str, identity: str, *, seconds: int) -> int:
    """A one-at-a-time gate. Returns 0 if allowed, else the seconds left to wait.

    Used for resending a verification email, where the limit is not "N per window" but
    "not again for two minutes". Expressed with SET NX so the check and the claim are one
    operation and two simultaneous requests cannot both pass.
    """
    key = redis_client.key("cooldown", bucket, identity)
    try:
        client = redis_client.get_client()
        if client.set(key, "1", nx=True, ex=seconds):
            return 0
        ttl = client.ttl(key)
        return max(1, int(ttl)) if ttl and ttl > 0 else 1
    except Exception:  # noqa: BLE001 - see the module docstring
        return 0
