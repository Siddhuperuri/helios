"""Shared infrastructure: the things every backend replica talks to instead of its disk.

Nothing in this package holds application logic. It exists so that the rest of the
codebase can ask for "the shared cache" or "a database session" without knowing whether
it is talking to Redis or to the in-process stand-in, to PostgreSQL or to SQLite.
"""
