"""Health probes, configuration safety, and the middleware's security behaviour.

The health tests are mostly about one distinction: liveness must *not* depend on
PostgreSQL or Redis, and readiness must. Getting that backwards is how a database blip
becomes a restart of every container at once, and it is the kind of mistake that only
shows up during the incident it makes worse.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient


def _break_database(monkeypatch) -> None:
    from app.db import base

    monkeypatch.setattr(base, "ping", lambda: (False, "OperationalError: connection refused"))


def _break_redis(monkeypatch) -> None:
    from app.infra import redis_client

    monkeypatch.setattr(
        redis_client, "ping", lambda: (False, "ConnectionError: connection refused")
    )


# --------------------------------------------------------------------------------------
# Liveness
# --------------------------------------------------------------------------------------

class TestLiveness:
    def test_liveness_is_200_when_the_process_is_running(self, client: TestClient) -> None:
        response = client.get("/api/health/live")
        assert response.status_code == 200
        assert response.json()["status"] == "alive"
        assert "instance" in response.json()

    def test_liveness_survives_the_database_being_down(
        self, client: TestClient, monkeypatch
    ) -> None:
        """The whole reason liveness and readiness are two endpoints.

        A failed liveness probe gets the container killed. If it depended on PostgreSQL, a
        database outage would restart the entire fleet — turning a recoverable dependency
        failure into a cold start on top of it.
        """
        _break_database(monkeypatch)
        _break_redis(monkeypatch)

        assert client.get("/api/health/live").status_code == 200

    def test_liveness_is_not_rate_limited(self, client: TestClient) -> None:
        """A probe that can be throttled is a probe that reports a false outage under load."""
        for _ in range(80):
            assert client.get("/api/health/live").status_code == 200


# --------------------------------------------------------------------------------------
# Readiness
# --------------------------------------------------------------------------------------

class TestReadiness:
    def test_readiness_is_200_when_dependencies_answer(self, client: TestClient) -> None:
        response = client.get("/api/health/ready")
        assert response.status_code == 200
        body = response.json()
        assert body["status"] == "ready"
        assert body["checks"]["database"]["ok"] is True
        assert body["checks"]["redis"]["ok"] is True

    def test_readiness_is_503_when_the_database_is_unreachable(
        self, client: TestClient, monkeypatch
    ) -> None:
        _break_database(monkeypatch)

        response = client.get("/api/health/ready")
        assert response.status_code == 503
        assert response.json()["status"] == "not_ready"
        assert response.json()["checks"]["database"]["ok"] is False
        assert "error" in response.json()["checks"]["database"]

    def test_readiness_is_503_when_redis_is_unreachable(
        self, client: TestClient, monkeypatch
    ) -> None:
        _break_redis(monkeypatch)

        response = client.get("/api/health/ready")
        assert response.status_code == 503
        assert response.json()["checks"]["redis"]["ok"] is False

    def test_readiness_reports_every_failure_not_just_the_first(
        self, client: TestClient, monkeypatch
    ) -> None:
        """An operator looking at a 503 wants the whole picture, not the first problem."""
        _break_database(monkeypatch)
        _break_redis(monkeypatch)

        checks = client.get("/api/health/ready").json()["checks"]
        assert checks["database"]["ok"] is False
        assert checks["redis"]["ok"] is False

    def test_a_dead_mail_provider_does_not_take_the_instance_out_of_rotation(
        self, client: TestClient, monkeypatch
    ) -> None:
        """Email is checked and reported, but not gating.

        Nobody could verify an address, which is bad. Every instance refusing traffic and
        the calculator going down entirely is worse, and it is a self-inflicted outage.
        """
        from app.email import sender

        monkeypatch.setattr(sender, "health", lambda: (False, "provider key rejected"))

        response = client.get("/api/health/ready")
        assert response.status_code == 200
        assert response.json()["checks"]["email"]["ok"] is False
        assert response.json()["checks"]["email"]["gating"] is False

    def test_draining_makes_the_instance_report_not_ready(self, client: TestClient) -> None:
        """Shutdown flips this before the server stops accepting, so the load balancer
        drains the instance rather than discovering it is gone by getting an error."""
        from app.api.routes import health

        health.set_accepting_traffic(False)
        try:
            response = client.get("/api/health/ready")
            assert response.status_code == 503
            assert response.json()["checks"]["draining"]["ok"] is False
            # Still alive, though — it is finishing in-flight work.
            assert client.get("/api/health/live").status_code == 200
        finally:
            health.set_accepting_traffic(True)

    def test_startup_probe_reports_dependency_state(self, client: TestClient) -> None:
        response = client.get("/api/health/startup")
        assert response.status_code == 200
        assert response.json()["database"] is True


class TestLegacyHealth:
    def test_the_original_endpoint_keeps_its_shape(self, client: TestClient) -> None:
        """The frontend renders the archive date and the cache stats from this."""
        response = client.get("/api/health")
        assert response.status_code == 200
        body = response.json()
        assert body["status"] == "ok"
        assert body["archive_latest_date"]
        assert "cache" in body
        # New fields alongside, not instead of.
        assert body["dependencies"]["database"] is True
        assert body["auth"]["access_ttl_minutes"] > 0


# --------------------------------------------------------------------------------------
# Configuration safety
# --------------------------------------------------------------------------------------

class TestProductionConfiguration:
    def test_development_defaults_are_reported_as_unsafe_for_production(
        self, monkeypatch
    ) -> None:
        for key in ("DATABASE_URL", "REDIS_URL", "JWT_SECRET", "EMAIL_PROVIDER"):
            monkeypatch.delenv(key, raising=False)
        from app.config import Settings

        problems = Settings().production_problems()
        joined = " ".join(problems)

        assert any("SQLite" in p for p in problems)
        assert any("in-process stand-in" in p for p in problems)
        assert any("JWT_SECRET" in p for p in problems)
        assert "EMAIL_PROVIDER" in joined

    def test_a_fully_configured_deployment_reports_no_problems(self, monkeypatch) -> None:
        monkeypatch.setenv("DATABASE_URL", "postgresql+psycopg://helios:pw@pgbouncer:6432/helios")
        monkeypatch.setenv("REDIS_URL", "redis://redis:6379/0")
        monkeypatch.setenv("JWT_SECRET", "x" * 48)
        monkeypatch.setenv("EMAIL_PROVIDER", "postmark")
        monkeypatch.setenv("SOLAR_COOKIE_SECURE", "true")
        monkeypatch.setenv("SOLAR_CORS_ORIGINS", "https://helios.example.com")
        from app.config import Settings

        assert Settings().production_problems() == []

    def test_a_wildcard_cors_origin_is_rejected(self, monkeypatch) -> None:
        """With credentials enabled, a wildcard origin is both forbidden by the
        specification and a way to hand any site a session."""
        monkeypatch.setenv("DATABASE_URL", "postgresql+psycopg://helios:pw@db:5432/helios")
        monkeypatch.setenv("REDIS_URL", "redis://redis:6379/0")
        monkeypatch.setenv("JWT_SECRET", "x" * 48)
        monkeypatch.setenv("EMAIL_PROVIDER", "ses")
        monkeypatch.setenv("SOLAR_COOKIE_SECURE", "true")
        monkeypatch.setenv("SOLAR_CORS_ORIGINS", "https://helios.example.com,*")
        from app.config import Settings

        assert any("'*'" in p for p in Settings().production_problems())

    def test_production_startup_refuses_unsafe_configuration(self, monkeypatch) -> None:
        """Fail-closed. Every item on that list is silent at runtime — a backend running
        with the in-process Redis stand-in looks perfectly healthy until the second
        replica appears."""
        monkeypatch.setenv("SOLAR_ENV", "production")
        from app.config import reset_settings

        reset_settings()
        import app.main as main

        reset_settings()
        with pytest.raises(RuntimeError, match="Refusing to start in production"):
            main._startup_checks()


# --------------------------------------------------------------------------------------
# Middleware
# --------------------------------------------------------------------------------------

class TestRequestMiddleware:
    def test_every_response_carries_a_request_id(self, client: TestClient) -> None:
        response = client.get("/api/meta/limits")
        assert response.headers["X-Request-ID"]
        assert response.headers["X-Instance"]
        assert float(response.headers["X-Response-Time-ms"]) >= 0

    def test_request_ids_are_unique(self, client: TestClient) -> None:
        ids = {client.get("/api/meta/limits").headers["X-Request-ID"] for _ in range(10)}
        assert len(ids) == 10

    def test_security_headers_are_set(self, client: TestClient) -> None:
        response = client.get("/api/meta/limits")
        assert response.headers["X-Content-Type-Options"] == "nosniff"
        assert response.headers["Referrer-Policy"] == "no-referrer"
        assert response.headers["X-Frame-Options"] == "DENY"

    def test_hsts_is_only_sent_when_cookies_are_secure(self, client: TestClient) -> None:
        """Sending HSTS from a plaintext dev server would pin developers' browsers to
        HTTPS for a host that does not serve it."""
        response = client.get("/api/meta/limits")
        assert "Strict-Transport-Security" not in response.headers

    def test_the_general_api_limit_applies(self, client: TestClient) -> None:
        from app.config import get_settings

        limit = get_settings().server.rate_limit_requests
        statuses = [
            client.get("/api/meta/limits").status_code for _ in range(limit + 5)
        ]
        assert 429 in statuses
        assert statuses.count(200) == limit

    def test_metrics_are_not_counted_against_the_limit(self, client: TestClient) -> None:
        for _ in range(80):
            client.get("/api/health/ready")
        assert client.get("/api/meta/limits").status_code == 200
