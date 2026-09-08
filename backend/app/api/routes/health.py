"""Health endpoints.

Liveness and readiness answer different questions, and conflating them is the single most
common way to build an outage into a deployment.

``/api/health/live``
    *Is this process running?* Nothing else. It touches no dependency, because the
    consequence of a failed liveness probe is that the orchestrator kills the container. A
    liveness check that queries PostgreSQL turns a database blip into every replica being
    restarted at once, which is a database blip plus a cold fleet.

``/api/health/ready``
    *Should this instance be given traffic?* This one does check its dependencies, because
    the consequence of failing is only that the load balancer routes elsewhere — which is
    exactly right for an instance that cannot reach Redis or PostgreSQL.

``/api/health``
    The original endpoint, kept working. It reaches upstream for the archive date, which
    makes it too slow and too dependent on a third party to be a probe — that is why the
    two above exist — but it is what the frontend's status indicator calls and removing it
    would break a working feature for no reason.
"""

from __future__ import annotations

import logging
import time
from typing import Any

from fastapi import APIRouter, Response

from app.config import get_settings
from app.db import base as db
from app.email import sender as email_sender
from app.infra import cache as shared_cache
from app.infra import redis_client
from app.security import tokens

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/health", tags=["health"])

# Set false by the shutdown handler the moment SIGTERM arrives, so that readiness starts
# failing before the process stops accepting connections. That gap is what lets the load
# balancer drain this instance instead of discovering it is gone by getting an error.
_accepting_traffic = True

_started_at = time.time()


def set_accepting_traffic(value: bool) -> None:
    global _accepting_traffic
    _accepting_traffic = value


def is_accepting_traffic() -> bool:
    return _accepting_traffic


@router.get("/live")
def live() -> dict[str, Any]:
    """200 while the process is running. Never touches a dependency."""
    settings = get_settings()
    return {
        "status": "alive",
        "instance": settings.observability.instance_id,
        "version": settings.version,
        "uptime_s": round(time.time() - _started_at, 1),
    }


@router.get("/ready")
def ready(response: Response) -> dict[str, Any]:
    """200 when this instance can serve real traffic, 503 when it cannot.

    Checks are run in full even after the first failure: an operator looking at a 503 wants
    to know everything that is wrong, not the first thing that was wrong.
    """
    settings = get_settings()
    checks: dict[str, Any] = {}
    ready_to_serve = True

    started = time.perf_counter()
    db_ok, db_error = db.ping()
    checks["database"] = {
        "ok": db_ok,
        "latency_ms": round((time.perf_counter() - started) * 1000, 2),
        "backend": "postgresql" if settings.database.is_postgres else "sqlite",
    }
    if not db_ok:
        checks["database"]["error"] = db_error
        ready_to_serve = False

    started = time.perf_counter()
    redis_ok, redis_error = redis_client.ping()
    checks["redis"] = {
        "ok": redis_ok,
        "latency_ms": round((time.perf_counter() - started) * 1000, 2),
        "backend": redis_client.info()["backend"],
    }
    if not redis_ok:
        checks["redis"]["error"] = redis_error
        ready_to_serve = False

    # Email is checked but is not a readiness gate. A dead mail provider means nobody can
    # verify an address; it does not mean this instance cannot compute a solar estimate,
    # and pulling the whole fleet out of rotation over it would be a self-inflicted outage.
    email_ok, email_note = email_sender.health()
    checks["email"] = {"ok": email_ok, "provider": settings.email.provider, "gating": False}
    if email_note:
        checks["email"]["note"] = email_note

    if not _accepting_traffic:
        checks["draining"] = {"ok": False, "note": "shutting down; finishing in-flight work"}
        ready_to_serve = False

    if settings.is_production:
        problems = settings.production_problems()
        if problems:
            checks["configuration"] = {"ok": False, "problems": problems}
            ready_to_serve = False

    response.status_code = 200 if ready_to_serve else 503
    return {
        "status": "ready" if ready_to_serve else "not_ready",
        "instance": settings.observability.instance_id,
        "version": settings.version,
        "environment": settings.environment,
        "checks": checks,
    }


@router.get("/startup")
def startup(response: Response) -> dict[str, Any]:
    """Whether this instance has ever become ready.

    Separate from readiness because orchestrators use a startup probe with a longer
    deadline: a container that takes forty seconds to warm up is starting, not failing, and
    a readiness probe with a forty-second timeout would be useless for detecting a genuinely
    unhealthy instance later.
    """
    db_ok, _ = db.ping()
    redis_ok, _ = redis_client.ping()
    started = db_ok and redis_ok
    response.status_code = 200 if started else 503
    return {"status": "started" if started else "starting", "database": db_ok, "redis": redis_ok}


# --------------------------------------------------------------------------------------
# The original health endpoint
# --------------------------------------------------------------------------------------

legacy_router = APIRouter(prefix="/api", tags=["reference"])


@legacy_router.get("/health")
def health() -> dict[str, Any]:
    """The pre-existing health payload, extended rather than replaced.

    The frontend renders the archive date from this, so the shape it already returned is
    preserved exactly and the new infrastructure fields are added alongside.
    """
    from app.api.service import CACHE
    from app.data.sources import latest_available_archive_date

    settings = get_settings()
    db_ok, _ = db.ping()
    redis_ok, _ = redis_client.ping()

    return {
        "status": "ok",
        "app": settings.app_name,
        "version": settings.version,
        "archive_latest_date": latest_available_archive_date().isoformat(),
        # Unchanged key and shape: the frontend reads this. The shared upstream cache is
        # reported alongside it rather than in place of it.
        "cache": CACHE.stats(),
        "upstream_cache": shared_cache.stats(),
        "instance": settings.observability.instance_id,
        "environment": settings.environment,
        "dependencies": {"database": db_ok, "redis": redis_ok},
        "auth": {
            "enabled": True,
            "providers": list(settings.oauth.configured_providers),
            **tokens.describe(),
        },
    }
