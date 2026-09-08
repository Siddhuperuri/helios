"""Column types that behave the same on PostgreSQL and on SQLite.

PostgreSQL is the deployment target and SQLite is what a laptop and a CI job run without
provisioning anything. Two type decorators keep the model definitions free of that
distinction: a UUID that is native on PostgreSQL and a 36-character string elsewhere, and
a JSON column that is ``JSONB`` on PostgreSQL and plain ``JSON`` elsewhere.

Both are deliberately thin. Anything cleverer would risk the two backends diverging in
behaviour, which is the one thing a compatibility shim must not do.
"""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import CHAR, JSON, TypeDecorator
from sqlalchemy.dialects import postgresql
from sqlalchemy.engine.interfaces import Dialect
from sqlalchemy.types import TypeEngine


class GUID(TypeDecorator):
    """A UUID primary key.

    ``postgresql.UUID`` where it exists; a 36-character lower-case hyphenated string
    elsewhere. Values are always handed back as :class:`uuid.UUID`, so calling code never
    has to know which backend it is on.
    """

    impl = CHAR
    cache_ok = True

    def load_dialect_impl(self, dialect: Dialect) -> TypeEngine[Any]:
        if dialect.name == "postgresql":
            return dialect.type_descriptor(postgresql.UUID(as_uuid=True))
        return dialect.type_descriptor(CHAR(36))

    def process_bind_param(self, value: Any, dialect: Dialect) -> Any:
        if value is None:
            return None
        if not isinstance(value, uuid.UUID):
            value = uuid.UUID(str(value))
        if dialect.name == "postgresql":
            return value
        return str(value)

    def process_result_value(self, value: Any, dialect: Dialect) -> uuid.UUID | None:
        if value is None:
            return None
        if isinstance(value, uuid.UUID):
            return value
        return uuid.UUID(str(value))


class JSONDocument(TypeDecorator):
    """A JSON document column: ``JSONB`` on PostgreSQL, ``JSON`` elsewhere.

    Estimate payloads are large, nested and read whole. They are stored as a document
    rather than shredded into columns because the payload's shape is the engine's business
    and pinning it into a schema would mean a migration every time the engine gained a
    field. Nothing queries inside it; ownership and the summary columns are what queries
    use.
    """

    impl = JSON
    cache_ok = True

    def load_dialect_impl(self, dialect: Dialect) -> TypeEngine[Any]:
        if dialect.name == "postgresql":
            return dialect.type_descriptor(postgresql.JSONB())
        return dialect.type_descriptor(JSON())
