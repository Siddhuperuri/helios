"""The shared ephemeral store.

Everything that is short-lived but must be seen identically by every backend replica
lives here: the upstream response cache, rate-limit counters, refresh-token revocation,
email verification and password-reset tokens, and OAuth state.

Why this module exists at all
-----------------------------
Before this, the rate limiter counted in a Python dict and the cache wrote to the
container's disk. Both are correct for exactly one process. Put three replicas behind a
load balancer and a client gets three times its rate limit, an OAuth flow that starts on
replica A cannot finish on replica B, and a cache entry paid for by one replica is unknown
to the other two. None of those are bugs in the code that was written; they are the
consequence of a single-process assumption that this module removes.

The ``memory://`` fallback
--------------------------
A laptop with no Redis running still has to be able to run the test suite and the dev
server. ``memory://`` is served by ``fakeredis``, which implements the real command
surface — expiry semantics, set operations and all — rather than a hand-written dict that
would drift from Redis in exactly the places that matter. Servers are held in a
module-level registry keyed by URL, so two application instances constructed inside one
test process share one store and genuinely exercise the cross-instance code paths.

It is a development convenience and it is fail-closed: :meth:`Settings.production_problems`
rejects it, and startup refuses to boot a production process that is still using it.
"""

from __future__ import annotations

import logging
import sys
import threading
import types
from typing import Any

from app.config import get_settings

logger = logging.getLogger(__name__)

# The registry of in-process stand-in servers, keyed by URL so that two instances pointed
# at the same "memory://" share one server and two pointed at different ones do not.
#
# It deliberately does *not* live in this module's globals. The cross-instance tests build
# a second application by dropping every ``app.*`` module from ``sys.modules`` and
# re-importing, which would give the second instance a fresh, empty registry — two
# "replicas" that appear to share a Redis URL while actually holding separate stores. The
# tests would then pass or fail for reasons that have nothing to do with the code.
#
# Anchoring it to a module outside the ``app`` package models the real relationship: Redis
# is external to the process, so its stand-in must be external to the code that reloads.
_REGISTRY_MODULE = "_helios_shared_fakeredis"
_FAKE_LOCK = threading.Lock()


def _fake_servers() -> dict[str, Any]:
    module = sys.modules.get(_REGISTRY_MODULE)
    if module is None:
        module = types.ModuleType(_REGISTRY_MODULE)
        module.servers = {}  # type: ignore[attr-defined]
        sys.modules[_REGISTRY_MODULE] = module
    return module.servers  # type: ignore[attr-defined,no-any-return]

_client: Any | None = None
_client_lock = threading.Lock()


class RedisUnavailableError(RuntimeError):
    """The shared store could not be reached.

    Raised by callers that cannot degrade. Anything that *can* degrade — the response
    cache, for instance — catches the underlying error and carries on without it, because
    a cache miss is slower and a cache outage that takes the whole platform down is worse.
    """


def _build_client(url: str) -> Any:
    settings = get_settings()

    if url.startswith("memory://"):
        try:
            import fakeredis
        except ImportError as exc:  # pragma: no cover - depends on the install
            raise RedisUnavailableError(
                "REDIS_URL is 'memory://' but fakeredis is not installed. Install the "
                "backend requirements, or set REDIS_URL to a real Redis instance."
            ) from exc

        with _FAKE_LOCK:
            servers = _fake_servers()
            server = servers.get(url)
            if server is None:
                server = fakeredis.FakeServer()
                servers[url] = server
        logger.warning(
            "Using the in-process Redis stand-in (%s). Shared state is confined to this "
            "process — acceptable for development and tests, never for production.",
            url,
        )
        return fakeredis.FakeStrictRedis(server=server, decode_responses=True)

    import redis

    logger.info("Connecting to Redis at %s", url.split("@")[-1])
    return redis.Redis.from_url(
        url,
        decode_responses=True,
        socket_timeout=settings.redis.socket_timeout_s,
        socket_connect_timeout=settings.redis.connect_timeout_s,
        max_connections=settings.redis.max_connections,
        health_check_interval=30,
        retry_on_timeout=True,
    )


def get_client() -> Any:
    """The process-wide client. Connections are lazy; this does not perform I/O."""
    global _client
    if _client is None:
        with _client_lock:
            if _client is None:
                _client = _build_client(get_settings().redis.url)
    return _client


def reset_client() -> None:
    """Drop the cached client. For tests and for reconfiguration in a script."""
    global _client
    with _client_lock:
        client = _client
        _client = None
    if client is not None:
        try:
            client.close()
        except Exception:  # noqa: BLE001 - teardown must not raise
            pass


def clear_memory_servers() -> None:
    """Empty every in-process stand-in. Test isolation only; a no-op against real Redis."""
    with _FAKE_LOCK:
        registry = _fake_servers()
        registry.clear()
    reset_client()


def key(*parts: Any) -> str:
    """Namespace a key.

    Every key this application writes is prefixed, so a Redis instance shared with
    something else stays legible and ``FLUSHDB`` is never the only cleanup available.
    """
    prefix = get_settings().redis.key_prefix
    return ":".join([prefix, *(str(p) for p in parts)])


def ping() -> tuple[bool, str | None]:
    """Liveness of the shared store, as ``(reachable, error)``.

    Never raises: the readiness endpoint calls this to decide whether to report 503, and
    a health check that throws is a health check that cannot report.
    """
    try:
        get_client().ping()
        return True, None
    except Exception as exc:  # noqa: BLE001 - any failure means "not ready"
        return False, f"{type(exc).__name__}: {exc}"


def info() -> dict[str, Any]:
    """Describe the configured store, without exposing credentials."""
    settings = get_settings()
    url = settings.redis.url
    return {
        "backend": "memory" if settings.redis.is_memory else "redis",
        "url": url if settings.redis.is_memory else url.split("@")[-1],
        "key_prefix": settings.redis.key_prefix,
        "production_ready": not settings.redis.is_memory,
    }
