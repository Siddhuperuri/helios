"""Engine, session factory and the two ways to get a session.

Sessions come from one of two places and never from anywhere else:

``get_session``
    A FastAPI dependency. One session per request, committed if the handler returns and
    rolled back if it raises, closed either way.

``session_scope``
    A context manager for code that is not in a request — startup tasks, the seeding
    script, background work. Same transaction discipline.

The pool is small on purpose. In the deployed topology PgBouncer sits in front of
PostgreSQL in transaction-pooling mode and multiplexes; a large per-process pool would
put the connection count back where PgBouncer was introduced to stop it going.
"""

from __future__ import annotations

import logging
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

from sqlalchemy import create_engine, event, text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker
from sqlalchemy.pool import NullPool, QueuePool

from app.config import get_settings

logger = logging.getLogger(__name__)


class Base(DeclarativeBase):
    """Declarative base for every table in the application."""


_engine: Engine | None = None
_session_factory: sessionmaker[Session] | None = None


def _engine_kwargs() -> dict[str, Any]:
    settings = get_settings()
    db = settings.database

    if db.is_sqlite:
        # SQLite is a development and test backend. `check_same_thread=False` is required
        # because FastAPI runs sync handlers in a threadpool; NullPool keeps a file-backed
        # database from holding connections open across those threads.
        return {
            "echo": db.echo,
            "future": True,
            "poolclass": NullPool,
            "connect_args": {"check_same_thread": False},
        }

    connect_args: dict[str, Any] = {"application_name": "helios-backend"}
    return {
        "echo": db.echo,
        "future": True,
        "poolclass": QueuePool,
        "pool_size": db.pool_size,
        "max_overflow": db.max_overflow,
        "pool_timeout": db.pool_timeout_s,
        "pool_recycle": db.pool_recycle_s,
        # Verify a connection before handing it out. PgBouncer and rolling restarts both
        # close connections underneath us; without this the first query after one of those
        # fails rather than transparently reconnecting.
        "pool_pre_ping": True,
        "connect_args": connect_args,
    }


def get_engine() -> Engine:
    global _engine
    if _engine is None:
        settings = get_settings()
        db = settings.database
        if db.is_sqlite:
            # The file has to exist somewhere writable before the first connection.
            settings.ensure_directories()
        _engine = create_engine(db.url, **_engine_kwargs())

        if db.is_sqlite:

            @event.listens_for(_engine, "connect")
            def _sqlite_pragmas(dbapi_connection: Any, _record: Any) -> None:
                cursor = dbapi_connection.cursor()
                # Foreign keys are off by default in SQLite, which would silently skip
                # the ON DELETE behaviour the schema depends on — the whole point of
                # SET NULL on estimates is that deleting an account must not delete a
                # shared estimate, and a test that does not enforce it proves nothing.
                cursor.execute("PRAGMA foreign_keys=ON")
                cursor.execute("PRAGMA journal_mode=WAL")
                cursor.close()

        logger.info("Database engine created for %s", db.safe_url)
    return _engine


def get_session_factory() -> sessionmaker[Session]:
    global _session_factory
    if _session_factory is None:
        _session_factory = sessionmaker(
            bind=get_engine(),
            autoflush=False,
            expire_on_commit=False,
            future=True,
        )
    return _session_factory


def get_session() -> Iterator[Session]:
    """FastAPI dependency yielding one session per request."""
    session = get_session_factory()()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


@contextmanager
def session_scope() -> Iterator[Session]:
    """A transactional session for code outside a request."""
    session = get_session_factory()()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def dispose_engine() -> None:
    """Close every pooled connection.

    Called on shutdown so a terminating replica returns its connections rather than
    leaving PgBouncer holding them until they time out. Also used by tests to reconfigure.
    """
    global _engine, _session_factory
    engine, _engine = _engine, None
    _session_factory = None
    if engine is not None:
        engine.dispose()


def ping() -> tuple[bool, str | None]:
    """Database reachability, as ``(reachable, error)``. Never raises."""
    try:
        with get_engine().connect() as connection:
            connection.execute(text("SELECT 1"))
        return True, None
    except Exception as exc:  # noqa: BLE001 - any failure means "not ready"
        return False, f"{type(exc).__name__}: {exc}"


def pool_stats() -> dict[str, Any]:
    """Pool saturation, for the metrics endpoint and for capacity work."""
    engine = get_engine()
    pool = engine.pool
    stats: dict[str, Any] = {"dialect": engine.dialect.name, "class": type(pool).__name__}
    for attribute in ("size", "checkedin", "checkedout", "overflow"):
        getter = getattr(pool, attribute, None)
        if callable(getter):
            try:
                stats[attribute] = getter()
            except Exception:  # noqa: BLE001 - introspection must not fail a health check
                pass
    return stats


def create_all() -> None:
    """Create every table directly from the models.

    Alembic owns the schema in every real deployment. This exists for the test suite and
    for a first local run, where spending a migration round-trip on a throwaway SQLite
    file buys nothing. It is never called at application startup.
    """
    from app.db import models  # noqa: F401 - registers the mappers

    Base.metadata.create_all(bind=get_engine())
