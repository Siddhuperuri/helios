"""Distributed tracing, via OpenTelemetry.

The question a trace answers here is specific: a console analysis takes thirty seconds —
how much of that was the upstream weather fetch, how much was feature building, how much
was fitting the model, and how much was the database? Latency percentiles say *that* it is
slow; only a trace says *where*.

    Browser → Nginx → FastAPI → PostgreSQL
                             → Redis
                             → Open-Meteo

Instrumentation is entirely optional and entirely automatic when enabled: FastAPI,
SQLAlchemy, Redis and urllib each have an official instrumentor, so the spans above appear
without a single manual span in the application code. If the packages are not installed,
this module logs once and does nothing — the application must not fail to start because a
collector is missing.
"""

from __future__ import annotations

import importlib
import logging
from typing import Any

from app.config import get_settings

logger = logging.getLogger(__name__)

_configured = False


def configure(app: Any = None) -> bool:
    """Set up tracing if it is enabled and available. Returns whether it was."""
    global _configured
    settings = get_settings().observability

    if not settings.tracing_enabled or _configured:
        return _configured

    try:
        from opentelemetry import trace
        from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
        from opentelemetry.sdk.resources import Resource
        from opentelemetry.sdk.trace import TracerProvider
        from opentelemetry.sdk.trace.export import BatchSpanProcessor
    except ImportError:
        logger.warning(
            "SOLAR_TRACING_ENABLED is set but the OpenTelemetry SDK is not installed. "
            "Install the optional tracing extras (see requirements.txt) or turn tracing "
            "off. Continuing without tracing."
        )
        return False

    resource = Resource.create(
        {
            "service.name": settings.service_name,
            "service.version": get_settings().version,
            "service.instance.id": settings.instance_id,
            "deployment.environment": get_settings().environment,
        }
    )
    provider = TracerProvider(resource=resource)
    provider.add_span_processor(
        BatchSpanProcessor(OTLPSpanExporter(endpoint=settings.otlp_endpoint))
    )
    trace.set_tracer_provider(provider)

    _instrument(app)
    _configured = True
    logger.info("Tracing enabled, exporting to %s", settings.otlp_endpoint)
    return True


def _instrument(app: Any) -> None:
    """Attach the automatic instrumentors, each independently optional.

    Imported by name at call time rather than at module scope, because each package is
    installed separately (requirements-tracing.txt) and a deployment may reasonably have
    some and not others. A missing one is a debug line, never a startup failure.
    """
    if app is not None:
        _try(
            "FastAPI",
            "opentelemetry.instrumentation.fastapi",
            "FastAPIInstrumentor",
            lambda cls: cls.instrument_app(
                app,
                # The probes run every couple of seconds per instance and would otherwise
                # be the overwhelming majority of spans, at zero diagnostic value.
                excluded_urls="/api/health/live,/api/health/ready,/api/metrics",
            ),
        )

    from app.db.base import get_engine

    _try(
        "SQLAlchemy",
        "opentelemetry.instrumentation.sqlalchemy",
        "SQLAlchemyInstrumentor",
        lambda cls: cls().instrument(engine=get_engine()),
    )
    _try(
        "Redis",
        "opentelemetry.instrumentation.redis",
        "RedisInstrumentor",
        lambda cls: cls().instrument(),
    )
    _try(
        "urllib",
        "opentelemetry.instrumentation.urllib",
        "URLLibInstrumentor",
        lambda cls: cls().instrument(),
    )


def _try(name: str, module_path: str, attribute: str, apply: Any) -> None:
    try:
        module = importlib.import_module(module_path)
        apply(getattr(module, attribute))
        logger.debug("Instrumented %s", name)
    except ImportError:
        logger.debug("%s instrumentation not installed; skipping", name)
    except Exception as exc:  # noqa: BLE001 - instrumentation must never break startup
        logger.warning("Could not instrument %s: %s", name, exc)


def current_trace_id() -> str | None:
    """The active trace id, for putting in a log line or an error report.

    This is what turns "the user says it was slow at 14:03" into a specific trace: the
    request id in the response header and the trace id in the log are the same request.
    """
    try:
        from opentelemetry import trace

        span = trace.get_current_span()
        context = span.get_span_context()
        if context and context.is_valid:
            return format(context.trace_id, "032x")
    except Exception:  # noqa: BLE001
        pass
    return None
