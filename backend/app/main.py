"""FastAPI application entry point.

Cross-cutting concerns live here: logging, CORS, rate limiting, observability, graceful
shutdown, and — most importantly — error translation. Every failure that reaches a client
is converted into a structured payload that names what went wrong and what to change.
Internal exception text is logged but never returned, both because it is useless to a user
and because stack traces leak implementation detail.

What changed when this became a multi-instance application
----------------------------------------------------------
The rate limiter used to count in a dictionary in this file. It now counts in Redis, so a
client has one budget across every replica rather than one per replica. The request
middleware now stamps a request id into a context variable that every log line picks up,
because a merged log stream from three instances is unreadable without one. CORS now allows
credentials, so it can no longer be lax about origins. And shutdown is now a sequence
rather than an exit: readiness flips to failing first, so the load balancer drains this
instance before the process stops answering.
"""

from __future__ import annotations

import logging
import time
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, Response
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.api.routes import analysis, estimate, experiments, health, meta
from app.api.routes import live_forecast as live_forecast_routes
from app.api.routes import point_forecast as point_forecast_routes
from app.auth import routes as auth_routes
from app.auth.deps import rate_limit_identity
from app.auth.service import AuthError
from app.config import get_settings
from app.data.sources import DataSourceError
from app.observability import errors as error_tracking
from app.observability import logging as obs_logging
from app.observability import metrics, tracing
from app.security import csrf
from app.security import rate_limit as limiter

settings = get_settings()

obs_logging.configure()
logger = logging.getLogger("helios")


# --------------------------------------------------------------------------------------
# Lifecycle
# --------------------------------------------------------------------------------------

def _startup_checks() -> None:
    """Refuse to start a production process that is still holding development defaults.

    Fail-closed on purpose. Every item on that list is a way the deployment would either
    lose shared state or leak a credential, and all of them are silent at runtime — a
    backend running with the in-process Redis stand-in looks perfectly healthy right up
    until the second replica appears.
    """
    problems = settings.production_problems()
    if not problems:
        return
    if settings.is_production:
        for problem in problems:
            logger.critical("Configuration: %s", problem)
        raise RuntimeError(
            f"Refusing to start in production with {len(problems)} unsafe configuration "
            f"value(s). See the critical log lines above."
        )
    for problem in problems:
        logger.debug("Development configuration note: %s", problem)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup and shutdown."""
    settings.ensure_directories()
    _startup_checks()

    metrics.configure()
    error_tracking.configure()
    tracing.configure(app)

    logger.info(
        "%s v%s ready on instance %s (%s)",
        settings.app_name,
        settings.version,
        settings.observability.instance_id,
        settings.environment,
    )
    logger.info("Database: %s", settings.database.safe_url)
    logger.info("Shared store: %s", redis_summary())

    _retention_sweep()

    yield

    # ---- shutdown ---------------------------------------------------------------------
    # Readiness fails first. The load balancer notices within a health-check interval and
    # stops sending new requests here; only then does the server stop accepting. Reversing
    # these two is what makes a rolling deployment drop requests.
    health.set_accepting_traffic(False)
    logger.info("Draining: readiness now reports not-ready; finishing in-flight requests")

    from app.db.base import dispose_engine
    from app.infra import redis_client

    dispose_engine()
    redis_client.reset_client()
    logger.info("Shutdown complete on instance %s", settings.observability.instance_id)


def redis_summary() -> str:
    from app.infra import redis_client

    info = redis_client.info()
    return f"{info['backend']} ({info['url']})"


def _retention_sweep() -> None:
    """Delete anonymous estimates past the retention window.

    Held behind a short-lived Redis lock so that three replicas starting together sweep
    once between them rather than three times. The sweep is idempotent, so the lock is an
    efficiency measure and not a correctness one — which is why failing to take it is not
    an error.
    """
    from app.estimate import store as estimate_store
    from app.infra import redis_client

    try:
        lock_key = redis_client.key("lock", "retention-sweep")
        if not redis_client.get_client().set(lock_key, "1", nx=True, ex=3600):
            logger.debug("Another instance holds the retention-sweep lock; skipping")
            return
    except Exception:  # noqa: BLE001 - a missing lock is not a reason to skip the sweep
        logger.debug("Could not take the retention-sweep lock; sweeping anyway")

    try:
        removed = estimate_store.prune(settings.store.estimate_retention_days)
        if removed:
            logger.info("Pruned %d anonymous estimate(s) past the retention window", removed)
    except Exception:  # never let housekeeping stop the server from starting
        logger.exception("Estimate retention sweep failed; continuing without it")


app = FastAPI(
    lifespan=lifespan,
    title=settings.app_name,
    version=settings.version,
    description=(
        "Solar irradiance forecasting and photovoltaic yield analysis with time-aware "
        "validation, calibrated prediction intervals, and full result traceability. "
        "Accounts are optional: the calculator works without one."
    ),
    docs_url="/api/docs",
    openapi_url="/api/openapi.json",
)


# --------------------------------------------------------------------------------------
# CORS
# --------------------------------------------------------------------------------------
#
# Credentials are now allowed, because the refresh token travels in a cookie. That makes
# the origin list load-bearing rather than advisory: with credentials, a wildcard origin is
# both forbidden by the specification and a way to hand any site a session. The list is an
# exact allowlist from SOLAR_CORS_ORIGINS, and `production_problems()` rejects '*' in it.
#
# In the shipped topology this hardly matters, because Nginx serves the frontend and the
# API from one origin and the requests are not cross-origin at all. It matters for the
# development setup and for anyone splitting the two across hosts.

app.add_middleware(
    CORSMiddleware,
    allow_origins=list(settings.server.cors_origins),
    allow_credentials=True,
    allow_methods=["GET", "POST", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["Content-Type", "Authorization", settings.auth.csrf_header_name],
    expose_headers=["X-Request-ID", "X-Response-Time-ms", "Retry-After"],
    max_age=600,
)


# --------------------------------------------------------------------------------------
# Request middleware
# --------------------------------------------------------------------------------------

def _route_template(request: Request) -> str:
    """The matched route pattern, for metric labels.

    ``/api/estimate/{estimate_id}``, never ``/api/estimate/V6-uHkNu4Ts``. One time series
    per estimate id would be a cardinality explosion that takes down the metrics backend
    long before it tells anyone anything.
    """
    route = request.scope.get("route")
    return getattr(route, "path", None) or "unmatched"


@app.middleware("http")
async def request_middleware(request: Request, call_next):
    request_id = obs_logging.new_request_id()
    obs_logging.bind_request(request_id)
    started = time.perf_counter()
    metrics.request_started()

    path = request.url.path
    is_probe = path.startswith("/api/health") or path == settings.observability.metrics_path

    try:
        if path.startswith("/api") and not is_probe:
            identity = rate_limit_identity(request)
            obs_logging.bind_request(
                request_id, identity[5:] if identity.startswith("user:") else ""
            )
            result = limiter.check(
                "api",
                identity,
                limit=settings.server.rate_limit_requests,
                window_s=settings.server.rate_limit_window_s,
            )
            if result.degraded:
                metrics.count_limiter_degraded()
            if not result.allowed:
                metrics.count_rate_limited("api")
                logger.warning("Rate limit exceeded", extra={"route": path})
                return JSONResponse(
                    status_code=429,
                    headers={**result.headers(), "X-Request-ID": request_id},
                    content={
                        "error": "rate_limited",
                        "message": (
                            f"Too many requests. This server allows "
                            f"{settings.server.rate_limit_requests} requests per "
                            f"{settings.server.rate_limit_window_s} seconds."
                        ),
                        "remedy": f"Retry in {result.retry_after_s} seconds.",
                    },
                )

        error_tracking.bind_request_context(request_id, obs_logging.user_id_var.get() or None)

        try:
            response = await call_next(request)
        except Exception as exc:
            logger.exception(
                "Unhandled error", extra={"route": path, "method": request.method}
            )
            error_tracking.capture(exc)
            elapsed = (time.perf_counter() - started) * 1000.0
            metrics.observe_request(request.method, _route_template(request), 500, elapsed / 1000)
            return JSONResponse(
                status_code=500,
                headers={"X-Request-ID": request_id},
                content={
                    "error": "internal_error",
                    "message": (
                        "The server encountered an unexpected error while handling this "
                        "request. The failure has been logged."
                    ),
                    "detail": f"Request ID {request_id}",
                    "remedy": (
                        "Retry the request. If it persists, quote this request ID to "
                        "support."
                    ),
                },
            )

        elapsed = (time.perf_counter() - started) * 1000.0
        response.headers["X-Request-ID"] = request_id
        response.headers["X-Response-Time-ms"] = f"{elapsed:.1f}"
        response.headers["X-Instance"] = settings.observability.instance_id
        # Conservative security headers. This API serves JSON, and the browser should not
        # be guessing anything about it.
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["X-Frame-Options"] = "DENY"
        if settings.auth.cookie_secure:
            response.headers["Strict-Transport-Security"] = (
                "max-age=31536000; includeSubDomains"
            )

        if not is_probe:
            metrics.observe_request(
                request.method, _route_template(request), response.status_code, elapsed / 1000
            )
            logger.info(
                "request",
                extra={
                    "route": _route_template(request),
                    "path": path,
                    "method": request.method,
                    "status": response.status_code,
                    "latency_ms": round(elapsed, 1),
                },
            )
        if elapsed > 5000:
            logger.info(
                "Slow request took %.0f ms",
                elapsed,
                extra={"route": _route_template(request), "latency_ms": round(elapsed, 1)},
            )
        return response
    finally:
        metrics.request_finished()


# --------------------------------------------------------------------------------------
# Error handlers
# --------------------------------------------------------------------------------------

@app.exception_handler(RequestValidationError)
async def validation_handler(request: Request, exc: RequestValidationError) -> JSONResponse:
    """Turn pydantic validation output into something a user can act on."""
    # "Field required" is what pydantic says and it is useless to a person filling in a
    # form. These name the thing that is missing in the words the interface used to ask
    # for it. Anything not listed falls back to a generic but still readable sentence.
    missing_field_messages = {
        "location": (
            "Tell us where the system will be — search for a place, use your current "
            "location, or pick a point on the map."
        ),
        "base": "The comparison needs a starting set of details to vary.",
        "scenarios": "Add at least two options to compare.",
        "label": "A name is needed.",
        "q": "Enter something to search for.",
        "email": "Enter your email address.",
        "password": "Enter a password.",
        "token": "That link is incomplete. Use the full link from the email.",
    }

    field_errors: list[dict[str, Any]] = []
    for err in exc.errors():
        location = " → ".join(str(p) for p in err.get("loc", []) if p != "body")
        message = err.get("msg", "Invalid value.")

        if err.get("type") == "missing":
            leaf = str((err.get("loc") or ["this"])[-1])
            message = missing_field_messages.get(
                leaf, f"'{leaf}' is needed before we can continue."
            )
        # pydantic prefixes custom validator messages with "Value error, "; that is an
        # implementation detail, not something a user should read.
        for prefix in ("Value error, ", "Assertion failed, "):
            if message.startswith(prefix):
                message = message[len(prefix):]
        field_errors.append(
            {
                "field": location or "request",
                "message": message,
                "type": err.get("type"),
            }
        )

    summary = field_errors[0]["message"] if field_errors else "The request was not valid."
    field_name = field_errors[0]["field"] if field_errors else "request"

    return JSONResponse(
        status_code=422,
        content={
            "error": "validation_error",
            "message": f"{field_name}: {summary}",
            "remedy": "Correct the highlighted fields and resubmit.",
            "field_errors": field_errors,
        },
    )


@app.exception_handler(DataSourceError)
async def data_source_handler(request: Request, exc: DataSourceError) -> JSONResponse:
    logger.warning("Data source error: %s (%s)", exc.message, exc.detail)
    return JSONResponse(
        status_code=exc.status,
        content={
            "error": "data_source_error",
            "message": exc.message,
            "detail": exc.detail,
            "remedy": (
                "Check the location and date range, then retry. If the upstream service is "
                "unavailable, cached results for previously requested periods still work."
            ),
        },
    )


@app.exception_handler(AuthError)
async def auth_error_handler(request: Request, exc: AuthError) -> JSONResponse:
    """Account operations refused by the service layer.

    Deliberately handled here rather than caught in every route: the rule is that
    ``AuthError`` already carries a message written for a person and a stable code, so
    there is nothing for a handler to add.
    """
    if exc.code in {"invalid_credentials", "account_disabled"}:
        metrics.count_auth_event("login_failure")
    logger.info("Auth refused: %s", exc.code)
    return JSONResponse(
        status_code=exc.status,
        content={"error": exc.code, "message": exc.message},
    )


@app.exception_handler(csrf.CSRFError)
async def csrf_handler(request: Request, exc: csrf.CSRFError) -> JSONResponse:
    logger.warning("CSRF check failed", extra={"route": request.url.path})
    return JSONResponse(
        status_code=403,
        content={
            "error": "csrf_failed",
            "message": exc.message,
            "remedy": "Reload the page and try again.",
        },
    )


@app.exception_handler(StarletteHTTPException)
async def http_handler(request: Request, exc: StarletteHTTPException) -> JSONResponse:
    """Render an HTTPException in the API's envelope.

    Routes raise ``HTTPException(detail=...)`` with either a string or an already-shaped
    dict. Both are supported: a dict is passed through so that auth routes can attach a
    machine-readable ``error`` code, and a string keeps the shape every existing route
    already produces.
    """
    if isinstance(exc.detail, dict):
        content = {"error": "http_error", **exc.detail}
    else:
        content = {
            "error": "http_error",
            "message": exc.detail if isinstance(exc.detail, str) else "Request failed.",
        }
    return JSONResponse(status_code=exc.status_code, content=content, headers=exc.headers)


# --------------------------------------------------------------------------------------
# Routers
# --------------------------------------------------------------------------------------

app.include_router(health.router)
app.include_router(health.legacy_router)
app.include_router(auth_routes.router)
app.include_router(meta.router)
# The consumer surface is registered before the research analysis routes so that
# /api/estimate/compare is matched by its literal path rather than being swallowed by
# /api/estimate/{estimate_id}.
app.include_router(estimate.router)
app.include_router(analysis.router)
app.include_router(experiments.router)
app.include_router(live_forecast_routes.router)
app.include_router(point_forecast_routes.router)


@app.get(settings.observability.metrics_path, include_in_schema=False)
def prometheus_metrics() -> Response:
    """Prometheus exposition.

    Not exposed publicly: the shipped Nginx configuration only answers this on the
    internal listener. It is not a secret, but it is a detailed map of the deployment and
    there is no reason to publish it.
    """
    if not settings.observability.metrics_enabled:
        return Response(status_code=404)

    from app.db.base import pool_stats

    try:
        metrics.observe_pool(pool_stats())
    except Exception:  # noqa: BLE001 - never fail a scrape over introspection
        pass

    body, content_type = metrics.render()
    return Response(content=body, media_type=content_type)


@app.get("/", include_in_schema=False)
def root() -> dict[str, Any]:
    return {
        "name": settings.app_name,
        "version": settings.version,
        "docs": "/api/docs",
        "health": "/api/health",
        "liveness": "/api/health/live",
        "readiness": "/api/health/ready",
        "attribution": settings.data.attribution,
    }
