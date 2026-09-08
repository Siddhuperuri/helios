"""Error tracking, via Sentry.

An unhandled exception in production is currently a line in a log stream that somebody has
to be looking at. Sentry turns it into a grouped, deduplicated report with a stack trace, a
release, and the request that caused it.

The part of this that needs care is what *not* to send. An error report is transmitted to a
third party and stored there, so a naïve integration ships whatever was in the request —
which for ``/api/auth/login`` is somebody's password. The scrubber below runs before every
event leaves the process and removes credentials from headers, cookies, query strings and
bodies. ``send_default_pii`` is off for the same reason.

Entirely optional: with no ``SENTRY_DSN`` the module does nothing.
"""

from __future__ import annotations

import logging
from typing import Any

from app.config import get_settings

logger = logging.getLogger(__name__)

_configured = False

# Names that must never leave the process, whatever container they arrive in.
_SENSITIVE_KEYS = frozenset(
    {
        "password",
        "current_password",
        "new_password",
        "token",
        "access_token",
        "refresh_token",
        "csrf_token",
        "code",
        "client_secret",
        "api_key",
        "authorization",
        "cookie",
        "set-cookie",
        "x-csrf-token",
        "jwt_secret",
        "hashed_password",
        "secret",
    }
)

_REDACTED = "[redacted]"


def _scrub(value: Any, depth: int = 0) -> Any:
    """Recursively replace anything sensitive.

    Depth-limited because a Sentry event can carry deeply nested frame locals and an
    unbounded walk over one is a way to spend real time in an exception handler.
    """
    if depth > 8:
        return value
    if isinstance(value, dict):
        return {
            key: (
                _REDACTED
                if str(key).lower() in _SENSITIVE_KEYS
                else _scrub(item, depth + 1)
            )
            for key, item in value.items()
        }
    if isinstance(value, (list, tuple)):
        return [_scrub(item, depth + 1) for item in value]
    return value


def _before_send(event: dict[str, Any], _hint: dict[str, Any]) -> dict[str, Any] | None:
    """Last gate before an event is transmitted."""
    from app.observability.logging import redact

    try:
        request = event.get("request")
        if isinstance(request, dict):
            for field in ("headers", "cookies", "data", "env"):
                if field in request:
                    request[field] = _scrub(request[field])
            # A token in a query string would survive header scrubbing.
            if isinstance(request.get("query_string"), str):
                request["query_string"] = redact(request["query_string"])
            if isinstance(request.get("url"), str):
                request["url"] = redact(request["url"])

        for container in ("extra", "contexts", "tags"):
            if container in event:
                event[container] = _scrub(event[container])

        for exception in (event.get("exception", {}) or {}).get("values", []) or []:
            if isinstance(exception.get("value"), str):
                exception["value"] = redact(exception["value"])
            for frame in (exception.get("stacktrace", {}) or {}).get("frames", []) or []:
                if isinstance(frame.get("vars"), dict):
                    frame["vars"] = _scrub(frame["vars"])
    except Exception:  # noqa: BLE001
        # If scrubbing itself fails, drop the event. Sending an unscrubbed report is worse
        # than losing one.
        logger.exception("Sentry scrubbing failed; dropping the event")
        return None
    return event


def configure() -> bool:
    """Initialise Sentry if a DSN is configured. Returns whether it was."""
    global _configured
    settings = get_settings()
    dsn = settings.observability.sentry_dsn

    if not dsn or _configured:
        return _configured

    try:
        import sentry_sdk
        from sentry_sdk.integrations.logging import LoggingIntegration
    except ImportError:
        logger.warning(
            "SENTRY_DSN is set but sentry-sdk is not installed. Continuing without error "
            "tracking."
        )
        return False

    sentry_sdk.init(
        dsn=dsn,
        environment=settings.environment,
        release=settings.observability.release,
        traces_sample_rate=settings.observability.sentry_traces_sample_rate,
        # Off deliberately: this would attach request bodies, headers and user addresses.
        # The scrubber below is the second line of defence, not the first.
        send_default_pii=False,
        max_request_body_size="never",
        before_send=_before_send,
        integrations=[
            LoggingIntegration(level=logging.INFO, event_level=logging.ERROR)
        ],
    )
    _configured = True
    logger.info("Error tracking enabled (release %s)", settings.observability.release)
    return True


def bind_request_context(request_id: str, user_id: str | None) -> None:
    """Attach the request id and a user reference to whatever is reported next.

    Only the account's opaque id — never their email address. A report should be enough to
    find the user in the database, not enough to identify them from the report alone.
    """
    if not _configured:
        return
    try:
        import sentry_sdk

        scope = sentry_sdk.get_current_scope()
        scope.set_tag("request_id", request_id)
        scope.set_user({"id": user_id} if user_id else None)
    except Exception:  # noqa: BLE001
        pass


def capture(exc: BaseException) -> None:
    if not _configured:
        return
    try:
        import sentry_sdk

        sentry_sdk.capture_exception(exc)
    except Exception:  # noqa: BLE001
        pass
