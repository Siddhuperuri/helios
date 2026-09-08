"""Structured logging with request context.

With one process, ``2026-08-22 10:14:02 INFO helios: Saved estimate abc`` is a fine log
line. With three replicas behind a load balancer it is missing the three things you
actually need: which instance wrote it, which request it belongs to, and which user was
making that request. Grepping a merged stream for a user's problem is impossible without
them.

So every record carries ``request_id``, ``user_id`` and ``instance_id``, propagated through
a :class:`contextvars.ContextVar` rather than threaded through every function signature.
Context variables are the right tool here specifically because FastAPI runs sync handlers
in a threadpool: a ``ContextVar`` set in the middleware is visible to the handler that
middleware called, and invisible to every other request running concurrently.

Output is JSON when ``SOLAR_JSON_LOGS`` is on, which is how it runs in a container so that
Loki or ELK can index the fields instead of regexing them back out of a sentence. On a
laptop it stays human-readable, because nobody wants to read JSON while developing.

Redaction is not a formatting nicety. A log line is copied to a central store, kept for
months and read by people who are not the user, so anything that looks like a token,
password or secret is replaced before it is written.
"""

from __future__ import annotations

import json
import logging
import re
import sys
import uuid
from contextvars import ContextVar
from datetime import datetime, timezone
from typing import Any

from app.config import get_settings

request_id_var: ContextVar[str] = ContextVar("request_id", default="")
user_id_var: ContextVar[str] = ContextVar("user_id", default="")

# Anything shaped like a credential, whatever field it arrived in. Deliberately blunt: a
# false positive costs a redacted log line, a false negative costs a leaked token.
_REDACTIONS: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"(?i)\b(bearer)\s+[A-Za-z0-9._\-]{8,}"), r"\1 [redacted]"),
    (
        re.compile(
            r"(?i)\b(password|passwd|secret|token|api[_-]?key|client[_-]?secret|"
            r"authorization|refresh|csrf)\b(\s*[=:]\s*)(\"?)([^\s\"',&]{4,})"
        ),
        r"\1\2\3[redacted]",
    ),
    # A bare JWT anywhere in a message.
    (re.compile(r"\beyJ[A-Za-z0-9_\-]{6,}\.[A-Za-z0-9_\-]{6,}\.[A-Za-z0-9_\-]{6,}"), "[redacted-jwt]"),
)


def redact(text: str) -> str:
    for pattern, replacement in _REDACTIONS:
        text = pattern.sub(replacement, text)
    return text


def new_request_id() -> str:
    return uuid.uuid4().hex[:12]


class ContextFilter(logging.Filter):
    """Attach the ambient request context to every record."""

    def __init__(self, instance_id: str) -> None:
        super().__init__()
        self.instance_id = instance_id

    def filter(self, record: logging.LogRecord) -> bool:
        record.request_id = request_id_var.get() or "-"
        record.user_id = user_id_var.get() or "-"
        record.instance_id = self.instance_id
        return True


class JSONFormatter(logging.Formatter):
    """One JSON object per line, with the context fields promoted to top level."""

    # Everything the stdlib puts on a record. Anything *not* in here was added by a caller
    # via `extra=` and is worth forwarding.
    _STANDARD = frozenset(
        vars(logging.LogRecord("", 0, "", 0, "", None, None)).keys()
    ) | {"message", "asctime", "taskName"}

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            # Built directly rather than through `formatTime`, whose datefmt is strftime
            # and therefore has no way to express milliseconds.
            "timestamp": datetime.fromtimestamp(record.created, tz=timezone.utc)
            .isoformat(timespec="milliseconds")
            .replace("+00:00", "Z"),
            "level": record.levelname,
            "logger": record.name,
            "message": redact(record.getMessage()),
            "request_id": getattr(record, "request_id", "-"),
            "user_id": getattr(record, "user_id", "-"),
            "instance_id": getattr(record, "instance_id", "-"),
        }
        if record.exc_info:
            payload["exception"] = redact(self.formatException(record.exc_info))

        for key, value in record.__dict__.items():
            if key in self._STANDARD or key in payload:
                continue
            try:
                json.dumps(value)
                payload[key] = value
            except (TypeError, ValueError):
                payload[key] = str(value)

        return json.dumps(payload, default=str)


class HumanFormatter(logging.Formatter):
    """The development format: the line it always printed, plus the request id.

    Redaction applies here too. Development logs are pasted into issues and chat far more
    often than production logs are read.
    """

    def format(self, record: logging.LogRecord) -> str:
        request_id = getattr(record, "request_id", "") or ""
        record.context = f"[{request_id}] " if request_id and request_id != "-" else ""
        formatted = super().format(record)
        return redact(formatted)


def configure() -> None:
    """Install the root logging configuration. Idempotent."""
    settings = get_settings()
    level = getattr(logging, settings.server.log_level.upper(), logging.INFO)

    handler = logging.StreamHandler(stream=sys.stdout)
    handler.addFilter(ContextFilter(settings.observability.instance_id))
    if settings.observability.json_logs:
        handler.setFormatter(JSONFormatter())
    else:
        handler.setFormatter(
            HumanFormatter("%(asctime)s %(levelname)-8s %(name)s: %(context)s%(message)s")
        )

    root = logging.getLogger()
    for existing in list(root.handlers):
        root.removeHandler(existing)
    root.addHandler(handler)
    root.setLevel(level)

    # Access logs are emitted by our own middleware with full context. Uvicorn's version
    # would be a second, contextless copy of every line.
    logging.getLogger("uvicorn.access").disabled = True
    logging.getLogger("uvicorn.error").setLevel(level)


def bind_request(request_id: str, user_id: str = "") -> None:
    request_id_var.set(request_id)
    user_id_var.set(user_id)


def bind_user(user_id: str) -> None:
    user_id_var.set(user_id)


def current_request_id() -> str:
    return request_id_var.get() or ""
