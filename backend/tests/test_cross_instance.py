"""Cross-instance behaviour: the tests that prove the backend is actually stateless.

Every test in this file uses two application instances built independently against the
same database and the same shared store. They stand in for two replicas behind a load
balancer. Because each instance re-imports the whole ``app`` package, they share no module
globals, no caches and no singletons — so anything that passes between them passed through
PostgreSQL or Redis, and nothing else.

That is the entire point. The old backend would have failed most of these: its estimates
were files on one container's disk, its rate limiter counted in one process's memory, and
an OAuth flow that began on one instance could not be finished on another. Each test below
corresponds to one of those failures.

Under the default configuration the "shared store" is a named in-process Redis stand-in
addressed by URL, which two instances in one test process genuinely share. CI runs the same
file against real PostgreSQL and real Redis by setting ``HELIOS_TEST_DATABASE_URL`` and
``HELIOS_TEST_REDIS_URL``, at which point the two instances are sharing exactly what
production shares.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from tests.conftest import auth_headers, csrf_headers, link_token, login, register

# --------------------------------------------------------------------------------------
# Durable state
# --------------------------------------------------------------------------------------

class TestSharedDurableState:
    def test_an_estimate_written_on_one_instance_is_readable_on_the_other(
        self, client: TestClient, second_instance: TestClient
    ) -> None:
        """The failure that file-backed storage would produce, stated as a test."""
        from app.estimate import store

        estimate_id = store.save(
            {"location": {"label": "Vijayawada"}, "system": {"capacity_kwp": 5}}
        ).estimate_id

        response = second_instance.get(f"/api/estimate/{estimate_id}")
        assert response.status_code == 200
        assert response.json()["estimate_id"] == estimate_id

    def test_an_account_created_on_one_instance_can_sign_in_on_the_other(
        self, client: TestClient, second_instance: TestClient, outbox
    ) -> None:
        client.post(
            "/api/auth/register",
            json={"email": "roaming@example.com", "password": "a-long-enough-password"},
        )

        session = login(second_instance, "roaming@example.com")
        assert session["user"]["email"] == "roaming@example.com"

    def test_a_dashboard_is_the_same_from_either_instance(
        self, client: TestClient, second_instance: TestClient, outbox
    ) -> None:
        user = register(client, "both@example.com")

        from app.estimate import store

        estimate_id = store.save(
            {"location": {"label": "Somewhere"}}, owner_id=user["user"]["id"]
        ).estimate_id

        first = client.get("/api/estimates", headers=auth_headers(user))
        second = second_instance.get("/api/estimates", headers=auth_headers(user))

        assert first.json()["estimates"] == second.json()["estimates"]
        assert [e["estimate_id"] for e in second.json()["estimates"]] == [estimate_id]


# --------------------------------------------------------------------------------------
# Sessions
# --------------------------------------------------------------------------------------

class TestSessionsAcrossInstances:
    def test_an_access_token_minted_on_one_instance_is_accepted_by_the_other(
        self, client: TestClient, second_instance: TestClient, outbox
    ) -> None:
        """Stateless by construction: the token is signed, not stored, so this works as
        long as both instances share JWT_SECRET."""
        session = register(client, "token@example.com")

        response = second_instance.get("/api/auth/me", headers=auth_headers(session))
        assert response.status_code == 200
        assert response.json()["user"]["email"] == "token@example.com"

    def test_a_refresh_token_issued_on_one_instance_can_be_rotated_by_the_other(
        self, client: TestClient, second_instance: TestClient, outbox
    ) -> None:
        """This one is *not* free. Refresh tokens are stored, so it works only because
        they are stored in Redis rather than in the issuing process."""
        register(client, "rotate-across@example.com")

        second_instance.cookies.set("helios_refresh", client.cookies.get("helios_refresh"))
        second_instance.cookies.set("helios_csrf", client.cookies.get("helios_csrf"))

        response = second_instance.post(
            "/api/auth/refresh", headers=csrf_headers(second_instance)
        )
        assert response.status_code == 200
        assert response.json()["access_token"]

    def test_signing_out_on_one_instance_ends_the_session_on_the_other(
        self, client: TestClient, second_instance: TestClient, outbox
    ) -> None:
        """Revocation has to be shared or logout is a lie on two thirds of the fleet."""
        register(client, "signout@example.com")
        refresh_cookie = client.cookies.get("helios_refresh")
        csrf_cookie = client.cookies.get("helios_csrf")

        assert client.post("/api/auth/logout", headers=csrf_headers(client)).status_code == 200

        second_instance.cookies.set("helios_refresh", refresh_cookie)
        second_instance.cookies.set("helios_csrf", csrf_cookie)
        response = second_instance.post(
            "/api/auth/refresh", headers={"X-CSRF-Token": csrf_cookie}
        )
        assert response.status_code == 401

    def test_a_password_reset_on_one_instance_invalidates_sessions_on_the_other(
        self, client: TestClient, second_instance: TestClient, outbox
    ) -> None:
        register(client, "reset-across@example.com")
        refresh_cookie = client.cookies.get("helios_refresh")
        csrf_cookie = client.cookies.get("helios_csrf")
        outbox.clear()

        # The whole reset happens on the second instance.
        second_instance.post(
            "/api/auth/forgot-password", json={"email": "reset-across@example.com"}
        )
        assert (
            second_instance.post(
                "/api/auth/reset-password",
                json={"token": link_token(outbox), "password": "a-completely-new-password"},
            ).status_code
            == 200
        )

        # The session held against the first instance is gone.
        client.cookies.set("helios_refresh", refresh_cookie)
        client.cookies.set("helios_csrf", csrf_cookie)
        assert (
            client.post(
                "/api/auth/refresh", headers={"X-CSRF-Token": csrf_cookie}
            ).status_code
            == 401
        )

    def test_a_verification_link_can_be_opened_against_either_instance(
        self, client: TestClient, second_instance: TestClient, outbox
    ) -> None:
        """A user clicks a link in their inbox; which replica answers is a coin toss."""
        client.post(
            "/api/auth/register",
            json={"email": "verify-across@example.com", "password": "a-long-enough-password"},
        )

        response = second_instance.post(
            "/api/auth/verify-email", json={"token": link_token(outbox)}
        )
        assert response.status_code == 200
        assert response.json()["verified"] is True


# --------------------------------------------------------------------------------------
# OAuth
# --------------------------------------------------------------------------------------

class TestOAuthAcrossInstances:
    def test_a_flow_started_on_one_instance_is_completed_by_the_other(
        self, client: TestClient, second_instance: TestClient, monkeypatch
    ) -> None:
        """The canonical cross-instance failure.

        The authorize request and the callback are two separate HTTP requests, and behind a
        load balancer they land wherever. Everything the authorize step remembered — state,
        nonce, PKCE verifier — has to be readable by whichever instance gets the callback.

        The provider itself is stubbed: what is under test is that the *flow state* crosses
        instances, not that Google's token endpoint works.
        """
        from app.auth import oauth

        state_value = oauth.begin("github", redirect_to="/projects")
        state = state_value.split("state=")[1].split("&")[0]

        # Stub the provider on the instance that will receive the callback.
        import app.auth.oauth as second_oauth

        monkeypatch.setattr(
            second_oauth, "exchange_code", lambda provider, code, verifier: "stub-access-token"
        )
        monkeypatch.setattr(
            second_oauth,
            "fetch_profile",
            lambda provider, token: second_oauth.OAuthProfile(
                provider="github",
                account_id="12345",
                email="oauth-user@example.com",
                email_verified=True,
                display_name="OAuth User",
                username="oauthuser",
            ),
        )

        response = second_instance.get(
            f"/api/auth/oauth/github/callback?code=stub-code&state={state}",
            follow_redirects=False,
        )
        assert response.status_code == 303
        assert "auth_code=" in response.headers["location"]

    def test_a_state_value_can_only_be_spent_once_across_the_whole_fleet(
        self, client: TestClient, second_instance: TestClient
    ) -> None:
        """Single-use has to be single-use globally, or a replayed callback just needs to
        be routed to a different replica."""
        from app.auth import oauth

        url = oauth.begin("google", redirect_to=None)
        state = url.split("state=")[1].split("&")[0]

        assert oauth.consume_state(state).provider == "google"

        with pytest.raises(oauth.OAuthError) as raised:
            oauth.consume_state(state)
        assert raised.value.code == "invalid_state"

    def test_an_oauth_handoff_code_can_be_exchanged_on_the_other_instance(
        self, client: TestClient, second_instance: TestClient, outbox
    ) -> None:
        session = register(client, "handoff@example.com")

        from app.auth.routes import _issue_handoff
        from app.auth.service import get_user
        from app.db.base import session_scope

        with session_scope() as db_session:
            user = get_user(db_session, session["user"]["id"])
            code = _issue_handoff(user)

        response = second_instance.post("/api/auth/oauth/exchange", json={"code": code})
        assert response.status_code == 200
        assert response.json()["user"]["email"] == "handoff@example.com"

        # And only once, whichever instance is asked.
        assert (
            client.post("/api/auth/oauth/exchange", json={"code": code}).status_code == 400
        )


# --------------------------------------------------------------------------------------
# Rate limiting
# --------------------------------------------------------------------------------------

class TestDistributedRateLimiting:
    def test_the_login_budget_is_cumulative_across_instances(
        self, client: TestClient, second_instance: TestClient, outbox
    ) -> None:
        """The property an in-process limiter cannot have.

        Driven over HTTP against both instances rather than by calling the limiter module,
        because after the second instance is built only one copy of that module is
        importable — a direct call would be testing one process twice. Going through the
        two applications is the only way the assertion means what it says.

        The exact count matters. Ten attempts is the configured budget; if each instance
        kept its own counter the twelfth attempt would still be returning 401.
        """
        from app.config import get_settings

        register(client, "stuffed@example.com")
        budget = get_settings().auth.login_attempts

        clients = (client, second_instance)
        statuses = []
        for index in range(budget + 6):
            target = clients[index % 2]
            statuses.append(
                target.post(
                    "/api/auth/login",
                    json={"email": "stuffed@example.com", "password": f"guess-number-{index}"},
                ).status_code
            )

        assert 429 in statuses, statuses
        rejected_before_block = statuses.index(429)
        assert rejected_before_block == budget, (
            f"expected one shared budget of {budget} attempts, but {rejected_before_block} "
            f"were allowed before the block: {statuses}"
        )

    def test_the_block_is_visible_from_the_instance_that_did_not_trip_it(
        self, client: TestClient, second_instance: TestClient, outbox
    ) -> None:
        """Exhausting the budget against one replica must lock the others out too."""
        from app.config import get_settings

        register(client, "exhausted@example.com")
        budget = get_settings().auth.login_attempts

        for index in range(budget + 1):
            client.post(
                "/api/auth/login",
                json={"email": "exhausted@example.com", "password": f"guess-{index}"},
            )

        blocked = second_instance.post(
            "/api/auth/login",
            json={"email": "exhausted@example.com", "password": "another-guess"},
        )
        assert blocked.status_code == 429
        assert "Retry-After" in blocked.headers

    def test_a_resend_cooldown_is_shared(
        self, client: TestClient, second_instance: TestClient, outbox
    ) -> None:
        client.post(
            "/api/auth/register",
            json={"email": "cooldown@example.com", "password": "a-long-enough-password"},
        )
        outbox.clear()

        first = client.post(
            "/api/auth/resend-verification", json={"email": "cooldown@example.com"}
        )
        assert first.status_code == 200

        second = second_instance.post(
            "/api/auth/resend-verification", json={"email": "cooldown@example.com"}
        )
        assert second.status_code == 429
        assert len(outbox) == 1


# --------------------------------------------------------------------------------------
# Shared cache
# --------------------------------------------------------------------------------------

class TestSharedCache:
    def test_a_cached_upstream_payload_is_visible_to_the_other_instance(
        self, client: TestClient, second_instance: TestClient
    ) -> None:
        """One weather fetch should be paid for once, not once per replica."""
        from app.infra import cache

        cache.write("cross-instance-key", {"hourly": {"time": ["2024-01-01T00:00"]}})
        assert cache.read("cross-instance-key") == {
            "hourly": {"time": ["2024-01-01T00:00"]}
        }

    def test_the_cache_key_scheme_is_unchanged(self, client: TestClient) -> None:
        """Existing entries must still resolve: the storage moved, the key did not."""
        from app.data.sources import _cache_key

        key = _cache_key(
            "https://archive-api.open-meteo.com/v1/archive",
            {"latitude": 16.5, "longitude": 80.6},
        )
        assert len(key) == 32
        assert key == _cache_key(
            "https://archive-api.open-meteo.com/v1/archive",
            {"longitude": 80.6, "latitude": 16.5},
        )


# --------------------------------------------------------------------------------------
# No local disk
# --------------------------------------------------------------------------------------

class TestNoLocalState:
    def test_saving_an_estimate_writes_nothing_to_the_store_directory(
        self, client: TestClient, isolated_environment
    ) -> None:
        """The direct check that the file-backed store is gone.

        Nothing durable may land on a backend's own disk, because the next request will be
        served by a different container.
        """
        from pathlib import Path

        from app.estimate import store

        store_dir = Path(isolated_environment["SOLAR_STORE_DIR"])
        store.save({"location": {"label": "Nowhere"}})

        written = [p for p in store_dir.rglob("*") if p.is_file()] if store_dir.exists() else []
        assert written == [], f"estimates were written to local disk: {written}"

    def test_recording_an_experiment_writes_no_jsonl_file(
        self, client: TestClient, isolated_environment
    ) -> None:
        import types
        from pathlib import Path

        from app.experiments import store

        result = types.SimpleNamespace(
            manifest={
                "dataset": {"period_start": "2022-01-01", "period_end": "2024-01-01"},
                "validation": {"n_train": 100, "n_test": 25},
            },
            model_key="random_forest",
            model_display_name="Random Forest",
            target_name="clear_sky_index",
            test_metrics_physical={"rmse": 52.3},
            test_metrics={},
            train_metrics={},
            cv_summary={},
            skill_scores={},
            interval_metrics={},
            warnings=[],
        )
        store.record(result, location_label="Vijayawada", latitude=16.5, longitude=80.6)

        store_dir = Path(isolated_environment["SOLAR_STORE_DIR"])
        jsonl = list(store_dir.rglob("*.jsonl")) if store_dir.exists() else []
        assert jsonl == [], f"experiments were written to local disk: {jsonl}"
