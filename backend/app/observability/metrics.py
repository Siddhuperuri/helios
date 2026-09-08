"""Prometheus metrics.

What is measured is chosen from what an on-call engineer is actually asked at 3am: is it
slow, is it erroring, and which dependency is the reason. So: request rate, error rate and
latency quantiles by route; database pool saturation; Redis and database probe latency; and
counters for the two silent failure modes that would otherwise be invisible — rate limiting
degrading to allow-everything, and the shared cache falling back to local disk.

Routes are recorded by their *template* (``/api/estimate/{estimate_id}``), never by the
concrete path. Recording the concrete path would create one time series per estimate id,
which is the classic way to take down a Prometheus server with your own instrumentation.

The whole module is optional. If ``prometheus_client`` is not installed, every function
here becomes a no-op and the application runs unchanged.
"""

from __future__ import annotations

import logging
from typing import Any

from app.config import get_settings

logger = logging.getLogger(__name__)

try:
    from prometheus_client import (
        CONTENT_TYPE_LATEST,
        CollectorRegistry,
        Counter,
        Gauge,
        Histogram,
        generate_latest,
    )

    AVAILABLE = True
except ImportError:  # pragma: no cover - depends on the install
    AVAILABLE = False
    CONTENT_TYPE_LATEST = "text/plain"

_registry: Any = None
_metrics: dict[str, Any] = {}


def configure() -> None:
    """Create the collectors. Safe to call more than once."""
    global _registry
    if not AVAILABLE or _registry is not None:
        return

    settings = get_settings()
    _registry = CollectorRegistry()
    instance = settings.observability.instance_id

    _metrics["requests"] = Counter(
        "helios_http_requests_total",
        "HTTP requests handled.",
        ["method", "route", "status"],
        registry=_registry,
    )
    _metrics["latency"] = Histogram(
        "helios_http_request_duration_seconds",
        "Request latency.",
        ["method", "route"],
        # Buckets span four orders of magnitude on purpose. A cached estimate returns in
        # milliseconds and a console model comparison takes forty seconds; a default bucket
        # set would put both in +Inf and make the p99 meaningless.
        buckets=(0.01, 0.05, 0.1, 0.25, 0.5, 1, 2.5, 5, 10, 20, 40, 60, 120, 300),
        registry=_registry,
    )
    _metrics["in_flight"] = Gauge(
        "helios_http_requests_in_flight",
        "Requests currently being handled.",
        registry=_registry,
    )
    _metrics["dependency_latency"] = Histogram(
        "helios_dependency_latency_seconds",
        "Latency of a dependency probe.",
        ["dependency"],
        buckets=(0.001, 0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1, 2.5, 5),
        registry=_registry,
    )
    _metrics["dependency_up"] = Gauge(
        "helios_dependency_up",
        "1 when a dependency answered its last probe, 0 otherwise.",
        ["dependency"],
        registry=_registry,
    )
    _metrics["db_pool"] = Gauge(
        "helios_db_pool_connections",
        "Database connection pool occupancy.",
        ["state"],
        registry=_registry,
    )
    _metrics["rate_limited"] = Counter(
        "helios_rate_limited_total",
        "Requests rejected by a rate limit.",
        ["bucket"],
        registry=_registry,
    )
    _metrics["limiter_degraded"] = Counter(
        "helios_rate_limiter_degraded_total",
        "Rate-limit checks that could not be performed because the shared store was "
        "unreachable, and were therefore allowed.",
        registry=_registry,
    )
    _metrics["auth_events"] = Counter(
        "helios_auth_events_total",
        "Authentication outcomes, for spotting credential-stuffing runs.",
        ["event"],
        registry=_registry,
    )
    _metrics["estimates"] = Counter(
        "helios_estimates_total",
        "Estimates produced, split by whether they were saved to an account.",
        ["ownership"],
        registry=_registry,
    )
    _metrics["analysis_jobs"] = Gauge(
        "helios_analysis_jobs",
        "Analysis jobs by state. Reported now so the dashboards do not have to change "
        "when this work moves to a queue.",
        ["state"],
        registry=_registry,
    )
    _metrics["build"] = Gauge(
        "helios_build_info",
        "Always 1; the labels carry the version and instance.",
        ["version", "instance", "environment"],
        registry=_registry,
    )
    _metrics["build"].labels(
        version=settings.version, instance=instance, environment=settings.environment
    ).set(1)
    logger.info("Prometheus metrics registered")


def _metric(name: str) -> Any:
    return _metrics.get(name) if AVAILABLE else None


def observe_request(method: str, route: str, status: int, duration_s: float) -> None:
    counter = _metric("requests")
    if counter is not None:
        counter.labels(method=method, route=route, status=str(status)).inc()
    histogram = _metric("latency")
    if histogram is not None:
        histogram.labels(method=method, route=route).observe(duration_s)


def request_started() -> None:
    gauge = _metric("in_flight")
    if gauge is not None:
        gauge.inc()


def request_finished() -> None:
    gauge = _metric("in_flight")
    if gauge is not None:
        gauge.dec()


def observe_dependency(name: str, ok: bool, duration_s: float) -> None:
    histogram = _metric("dependency_latency")
    if histogram is not None:
        histogram.labels(dependency=name).observe(duration_s)
    gauge = _metric("dependency_up")
    if gauge is not None:
        gauge.labels(dependency=name).set(1 if ok else 0)


def observe_pool(stats: dict[str, Any]) -> None:
    gauge = _metric("db_pool")
    if gauge is None:
        return
    for state in ("size", "checkedin", "checkedout", "overflow"):
        if isinstance(stats.get(state), (int, float)):
            gauge.labels(state=state).set(float(stats[state]))


def count_rate_limited(bucket: str) -> None:
    counter = _metric("rate_limited")
    if counter is not None:
        counter.labels(bucket=bucket).inc()


def count_limiter_degraded() -> None:
    counter = _metric("limiter_degraded")
    if counter is not None:
        counter.inc()


def count_auth_event(event: str) -> None:
    """Record an authentication outcome.

    ``login_success``, ``login_failure``, ``register``, ``refresh``, ``refresh_reuse``,
    ``password_reset``. A rising ``login_failure`` rate with a flat ``login_success`` rate
    is what credential stuffing looks like from the outside, and that alert is the reason
    this counter exists.
    """
    counter = _metric("auth_events")
    if counter is not None:
        counter.labels(event=event).inc()


def count_estimate(owned: bool) -> None:
    counter = _metric("estimates")
    if counter is not None:
        counter.labels(ownership="owned" if owned else "anonymous").inc()


def set_analysis_jobs(state: str, value: int) -> None:
    gauge = _metric("analysis_jobs")
    if gauge is not None:
        gauge.labels(state=state).set(value)


def render() -> tuple[bytes, str]:
    """The exposition payload for ``/api/metrics``."""
    if not AVAILABLE or _registry is None:
        return b"# metrics unavailable: prometheus_client is not installed\n", "text/plain"
    return generate_latest(_registry), CONTENT_TYPE_LATEST


def reset() -> None:
    """Drop the registry. Tests only."""
    global _registry
    _registry = None
    _metrics.clear()
