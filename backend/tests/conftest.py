"""Shared test fixtures.

Two things are arranged here, and both exist to make the cross-instance tests mean
something rather than to make the suite convenient.

**Every test gets its own database and its own shared store.** The database is a SQLite
file in a temporary directory and the Redis stand-in is a named ``memory://`` server. Both
are addressed by a URL, which is the point: two application instances built with the same
URL genuinely share state, and two built with different URLs genuinely do not. A fixture
that patched a module global instead would prove nothing about whether the code still has
local state in it.

**Instances are built, not imported.** The ``client`` and ``second_instance`` fixtures
each construct a fresh FastAPI application the same way a container would, by dropping
every ``app.*`` module and re-importing. The cross-instance tests use both to stand in for
two replicas: whatever passes between them passed through PostgreSQL or Redis, because
there is no other channel.

CI runs the same suite against real PostgreSQL and real Redis by setting ``DATABASE_URL``
and ``REDIS_URL``; the fixtures below defer to those when they are present.
"""

from __future__ import annotations

import importlib
import os
import sys
import uuid
from collections.abc import Iterator
from typing import Any

import pytest
from fastapi.testclient import TestClient


def _fresh_app() -> Any:
    """Import a brand-new application object against the current environment.

    Modules are dropped from ``sys.modules`` first so that module-level singletons — the
    settings, the engine, the Redis client — are rebuilt rather than inherited. This is
    what makes a second instance a second instance.
    """
    for name in list(sys.modules):
        if name == "app" or name.startswith("app."):
            del sys.modules[name]
    return importlib.import_module("app.main").app


@pytest.fixture(autouse=True)
def isolated_environment(tmp_path, monkeypatch) -> Iterator[dict[str, str]]:
    """Point this test at its own database, shared store and directories."""
    token = uuid.uuid4().hex[:12]

    env = {
        "SOLAR_ENV": "test",
        "DATABASE_URL": os.environ.get(
            "HELIOS_TEST_DATABASE_URL", f"sqlite:///{tmp_path / 'helios-test.db'}"
        ),
        "REDIS_URL": os.environ.get("HELIOS_TEST_REDIS_URL", f"memory://{token}"),
        "SOLAR_CACHE_DIR": str(tmp_path / "cache"),
        "SOLAR_STORE_DIR": str(tmp_path / "store"),
        "EMAIL_PROVIDER": "memory",
        "SOLAR_FRONTEND_BASE": "http://localhost:3000",
        "OAUTH_REDIRECT_BASE": "http://127.0.0.1:8000",
        # Provider credentials are configured so the flow can be exercised. Nothing here
        # reaches a provider: the token exchange and profile fetch are stubbed at the
        # module boundary, and what the OAuth tests actually check is the state handling
        # and the account-linking rules around them.
        "GOOGLE_OAUTH_CLIENT_ID": "test-google-client-id",
        "GOOGLE_OAUTH_CLIENT_SECRET": "test-google-client-secret",
        "GITHUB_OAUTH_CLIENT_ID": "test-github-client-id",
        "GITHUB_OAUTH_CLIENT_SECRET": "test-github-client-secret",
        "JWT_SECRET": "test-secret-not-used-anywhere-else-0123456789",
        # Argon2 at production work factors would add tens of milliseconds to every test
        # that touches a password, which across the auth suite is minutes. The parameters
        # are exercised by their own test; everything else only needs the algorithm.
        "SOLAR_ARGON2_TIME_COST": "1",
        "SOLAR_ARGON2_MEMORY_KIB": "8192",
        "SOLAR_METRICS_ENABLED": "0",
        "SOLAR_LOG_LEVEL": "WARNING",
        # Long rate-limit windows, purely to make the limiter tests deterministic.
        #
        # The limiter is a fixed window: the counter key contains `int(now // window)`, so
        # it resets the instant a window boundary passes. A test that makes fourteen login
        # attempts expecting a 429 fails if a boundary happens to fall between the first
        # and the last — about a 1-in-900 chance per run at the production window of 900s,
        # which is exactly the kind of rare flake that teaches people to re-run CI instead
        # of reading it.
        #
        # Stretching the window to a day makes a mid-test boundary effectively impossible
        # without changing what is being tested: the assertions are all about the counter
        # accumulating past its limit, never about when it resets.
        "SOLAR_RATE_WINDOW": "86400",
        "SOLAR_LOGIN_RATE_WINDOW": "86400",
        "SOLAR_REGISTER_RATE_WINDOW": "86400",
    }
    for key, value in env.items():
        monkeypatch.setenv(key, value)

    # Anything left over from a previous test in this process.
    for name in list(sys.modules):
        if name == "app" or name.startswith("app."):
            del sys.modules[name]

    from app.db.base import create_all

    create_all()

    yield env

    from app.db.base import dispose_engine
    from app.infra import redis_client

    dispose_engine()
    redis_client.reset_client()


@pytest.fixture()
def app(isolated_environment) -> Any:
    return _fresh_app()


@pytest.fixture()
def client(app) -> Iterator[TestClient]:
    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture()
def second_instance(isolated_environment) -> Iterator[TestClient]:
    """A second backend replica, sharing this test's database and Redis.

    Everything module-level is rebuilt, so the only thing the two instances have in common
    is the infrastructure they both point at. If a request that starts on one can be
    completed by the other, it is because the state went through PostgreSQL or Redis.
    """
    with TestClient(_fresh_app()) as test_client:
        yield test_client


@pytest.fixture()
def outbox() -> Iterator[list]:
    """Messages the application tried to send, so a test can follow the link in one."""
    from app.email.sender import MemorySender, reset_sender
    from app.email.sender import outbox as shared_outbox

    reset_sender()
    MemorySender.clear()
    yield shared_outbox()
    MemorySender.clear()


# --------------------------------------------------------------------------------------
# Helpers
# --------------------------------------------------------------------------------------

def register(client: TestClient, email: str, password: str = "a-long-enough-password") -> dict:
    """Register an account and sign in, returning the session payload.

    Two calls, because registration deliberately returns no session — see
    ``app.auth.routes.register`` for why. This mirrors exactly what the frontend does.
    """
    created = client.post("/api/auth/register", json={"email": email, "password": password})
    assert created.status_code == 200, created.text
    return login(client, email, password)


def login(client: TestClient, email: str, password: str = "a-long-enough-password") -> dict:
    response = client.post("/api/auth/login", json={"email": email, "password": password})
    assert response.status_code == 200, response.text
    return response.json()


def auth_headers(session: dict) -> dict[str, str]:
    return {"Authorization": f"Bearer {session['access_token']}"}


def csrf_headers(client: TestClient) -> dict[str, str]:
    """Headers for a cookie-authenticated call.

    Read from the cookie jar rather than from a saved login response, because the CSRF
    token is reissued alongside every refresh-token rotation. A test that keeps sending the
    token it got at login starts failing after its first refresh — which is the client
    behaving correctly, not a bug.
    """
    token = client.cookies.get("helios_csrf")
    assert token, "no CSRF cookie is set; the client is not signed in"
    return {"X-CSRF-Token": token}


def link_token(outbox_messages: list, index: int = -1) -> str:
    """Pull the token out of the most recent email."""
    text = outbox_messages[index].text
    marker = "token="
    start = text.index(marker) + len(marker)
    end = len(text)
    for terminator in ("\n", "&", " "):
        found = text.find(terminator, start)
        if found != -1:
            end = min(end, found)
    from urllib.parse import unquote

    return unquote(text[start:end].strip())
