"""The shared upstream-response cache.

What is cached and why has not changed: an Open-Meteo payload is keyed by a SHA-256 of
the request URL and parameters, and holding the exact bytes that produced a result is what
lets a recorded experiment be reproduced after the upstream reanalysis has been revised.
The key scheme is unchanged, deliberately — an existing key must still resolve.

What *has* changed is where the bytes go. They used to be one JSON file per key on the
container's disk, which meant three replicas paid for the same fetch three times and each
held a copy the others could not see. They now go to Redis, so the fetch is paid for once.

The disk tier survives as a fallback for the case where Redis is unreachable. That is not
shared state and is not relied upon for correctness: it exists because a weather fetch
costs tens of seconds, and a Redis incident should make the platform slower rather than
turn every request into a fresh upstream download.
"""

from __future__ import annotations

import json
import logging
import time
from pathlib import Path
from typing import Any

from app.config import get_settings
from app.infra import redis_client

logger = logging.getLogger(__name__)

_NAMESPACE = "cache"

# Set once per process, so a Redis outage produces one warning rather than one per request.
_degraded_logged = False


def _redis_key(key: str) -> str:
    return redis_client.key(_NAMESPACE, key)


def _disk_path(key: str) -> Path:
    return get_settings().cache.directory / f"{key}.json"


def _note_degraded(operation: str, exc: Exception) -> None:
    global _degraded_logged
    if not _degraded_logged:
        logger.warning(
            "Shared cache unavailable during %s (%s: %s). Falling back to the local tier; "
            "upstream fetches will not be shared between replicas until Redis returns.",
            operation,
            type(exc).__name__,
            exc,
        )
        _degraded_logged = True


def read(key: str) -> dict[str, Any] | None:
    """Return a cached payload, or ``None`` for a miss, an expiry or an unreadable entry."""
    settings = get_settings()
    if not settings.cache.enabled:
        return None

    shared_available = True
    try:
        raw = redis_client.get_client().get(_redis_key(key))
        if raw is not None:
            return json.loads(raw)
    except json.JSONDecodeError:
        # A corrupt entry is a miss, never an error. Drop it so it is not read again.
        logger.warning("Discarding unreadable shared cache entry %s", key)
        try:
            redis_client.get_client().delete(_redis_key(key))
        except Exception:  # noqa: BLE001 - best effort
            pass
        return None
    except Exception as exc:  # noqa: BLE001 - degrade, never fail the request
        shared_available = False
        _note_degraded("read", exc)

    if not settings.cache.disk_fallback:
        return None

    payload = _read_disk(key)
    if payload is not None and shared_available:
        # A local hit after a shared miss means an entry written by an earlier release, or
        # during an outage. Promote it so the other replicas get it too, and so the local
        # tier drains rather than quietly becoming the real cache again.
        try:
            redis_client.get_client().set(
                _redis_key(key), json.dumps(payload), ex=settings.cache.ttl_seconds
            )
        except Exception:  # noqa: BLE001 - promotion is opportunistic
            pass
    return payload


def write(key: str, payload: dict[str, Any]) -> None:
    """Store a payload under the shared TTL. Failures are logged, never raised."""
    settings = get_settings()
    if not settings.cache.enabled:
        return

    body = json.dumps(payload)
    try:
        redis_client.get_client().set(_redis_key(key), body, ex=settings.cache.ttl_seconds)
        return
    except Exception as exc:  # noqa: BLE001
        _note_degraded("write", exc)

    if settings.cache.disk_fallback:
        _write_disk(key, body)


def delete(key: str) -> None:
    try:
        redis_client.get_client().delete(_redis_key(key))
    except Exception:  # noqa: BLE001
        pass
    path = _disk_path(key)
    if path.exists():
        path.unlink(missing_ok=True)


# --------------------------------------------------------------------------------------
# Local fallback tier
# --------------------------------------------------------------------------------------

def _read_disk(key: str) -> dict[str, Any] | None:
    settings = get_settings()
    path = _disk_path(key)
    if not path.exists():
        return None
    try:
        if time.time() - path.stat().st_mtime > settings.cache.ttl_seconds:
            return None
        with path.open("r", encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, json.JSONDecodeError):
        logger.warning("Discarding unreadable local cache entry %s", key)
        return None


def _write_disk(key: str, body: str) -> None:
    path = _disk_path(key)
    tmp = path.with_suffix(".tmp")
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with tmp.open("w", encoding="utf-8") as fh:
            fh.write(body)
        tmp.replace(path)  # atomic, so a crash cannot leave a half-written entry
    except OSError as exc:
        logger.warning("Could not write local cache entry %s: %s", key, exc)


# --------------------------------------------------------------------------------------
# Introspection
# --------------------------------------------------------------------------------------

def stats() -> dict[str, Any]:
    """Describe the cache for the health endpoint."""
    settings = get_settings()
    out: dict[str, Any] = {
        "enabled": settings.cache.enabled,
        "ttl_seconds": settings.cache.ttl_seconds,
        "shared_backend": redis_client.info()["backend"],
        "local_fallback": settings.cache.disk_fallback,
    }
    try:
        client = redis_client.get_client()
        pattern = redis_client.key(_NAMESPACE, "*")
        # SCAN rather than KEYS: this runs on a live instance and must not block it.
        out["shared_entries"] = sum(1 for _ in client.scan_iter(match=pattern, count=500))
        out["shared_available"] = True
    except Exception as exc:  # noqa: BLE001
        out["shared_available"] = False
        out["shared_error"] = type(exc).__name__
    return out
