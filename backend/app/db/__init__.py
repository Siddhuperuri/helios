"""Durable application state.

Four tables and no more: users, the OAuth accounts linked to them, estimates and
experiments. The solar engine itself is untouched by any of this — it takes an input
dataclass and returns a payload, and whether that payload is then written to a row is not
its concern.
"""

from app.db.base import Base, get_session, session_scope  # noqa: F401
