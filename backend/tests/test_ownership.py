"""Estimate ownership, and the privacy boundary around it.

The ownership model is additive: it was bolted onto a product where an estimate's opaque
link was the only access control there was, and it had to be added without breaking that.
These tests pin down the resulting rules, which are easy to state and easy to get subtly
wrong:

* An anonymous estimate has no owner and behaves exactly as it always did.
* A signed-in user's estimate gets an owner and appears in their dashboard.
* The opaque link still reads any estimate, owned or not — otherwise every link already
  sent to an installer would break.
* Only the owner can *change* an owned estimate.
* One user's dashboard never contains another user's estimates, by any route.

Estimates are written directly through the store rather than through ``POST /api/estimate``
because that endpoint runs the full solar pipeline, which needs network access to
Open-Meteo. The engine is not what is under test here; the authorization around it is.
"""

from __future__ import annotations

from fastapi.testclient import TestClient

from tests.conftest import auth_headers, register

PAYLOAD = {
    "location": {"label": "Vijayawada, India"},
    "system": {"capacity_kwp": 5.4},
    "generation": {"annual_kwh": 8123.4},
    "economics": {"payback_years": 4.2},
    "uncertainty": {"confidence": "moderate"},
    "user_type": "home",
}


def _save(owner_id: str | None = None, label: str = "Test estimate") -> str:
    from app.estimate import store

    return store.save(dict(PAYLOAD), label=label, owner_id=owner_id).estimate_id


# --------------------------------------------------------------------------------------
# Anonymous estimates
# --------------------------------------------------------------------------------------

class TestAnonymousEstimates:
    def test_an_anonymous_estimate_is_readable_by_its_link(self, client: TestClient) -> None:
        estimate_id = _save()
        response = client.get(f"/api/estimate/{estimate_id}")
        assert response.status_code == 200
        assert response.json()["estimate_id"] == estimate_id
        assert response.json()["owned"] is False
        assert response.json()["editable"] is True

    def test_an_anonymous_estimate_stays_editable_without_an_account(
        self, client: TestClient
    ) -> None:
        """The signed-out result page renames, edits and deletes. None of that may start
        demanding a signup."""
        estimate_id = _save()

        renamed = client.post(
            f"/api/estimate/{estimate_id}/rename", json={"label": "My roof"}
        )
        assert renamed.status_code == 200
        assert renamed.json()["label"] == "My roof"

        assert client.delete(f"/api/estimate/{estimate_id}").status_code == 200

    def test_an_unknown_link_is_a_clean_404(self, client: TestClient) -> None:
        response = client.get("/api/estimate/nosuchestimateidentifier")
        assert response.status_code == 404
        assert "could not find" in response.json()["message"].lower()


# --------------------------------------------------------------------------------------
# Owned estimates
# --------------------------------------------------------------------------------------

class TestOwnedEstimates:
    def test_the_dashboard_lists_only_the_callers_estimates(
        self, client: TestClient, outbox
    ) -> None:
        alice = register(client, "alice@example.com")
        bob = register(client, "bob@example.com")

        alice_estimate = _save(alice["user"]["id"], "Alice's farm")
        bob_estimate = _save(bob["user"]["id"], "Bob's roof")
        _save(None, "Nobody's estimate")

        listing = client.get("/api/estimates", headers=auth_headers(alice))
        assert listing.status_code == 200
        ids = [e["estimate_id"] for e in listing.json()["estimates"]]
        assert ids == [alice_estimate]
        assert bob_estimate not in ids

    def test_the_dashboard_requires_an_account(self, client: TestClient) -> None:
        """There is no anonymous listing any more. There used to be, and it showed every
        estimate on the server to anyone who asked."""
        _save()
        assert client.get("/api/estimates").status_code == 401

    def test_there_is_no_parameter_that_widens_the_listing(
        self, client: TestClient, outbox
    ) -> None:
        alice = register(client, "alice2@example.com")
        bob = register(client, "bob2@example.com")
        _save(bob["user"]["id"], "Bob's private estimate")

        for query in ("?owner_id=" + bob["user"]["id"], "?all=true", "?limit=100"):
            response = client.get(f"/api/estimates{query}", headers=auth_headers(alice))
            # Either the parameter is rejected outright or it is ignored; what must never
            # happen is that it returns somebody else's rows.
            if response.status_code == 200:
                assert response.json()["estimates"] == []

    def test_an_owned_estimate_is_still_readable_by_its_link(
        self, client: TestClient, outbox
    ) -> None:
        """The property that keeps every already-shared link working."""
        owner = register(client, "owner@example.com")
        estimate_id = _save(owner["user"]["id"])

        anonymous = client.get(f"/api/estimate/{estimate_id}")
        assert anonymous.status_code == 200
        assert anonymous.json()["owned"] is True
        assert anonymous.json()["editable"] is False

    def test_a_stranger_holding_the_link_cannot_change_an_owned_estimate(
        self, client: TestClient, outbox
    ) -> None:
        owner = register(client, "owner2@example.com")
        estimate_id = _save(owner["user"]["id"], "Original name")

        assert (
            client.post(
                f"/api/estimate/{estimate_id}/rename", json={"label": "Vandalised"}
            ).status_code
            == 403
        )
        assert client.delete(f"/api/estimate/{estimate_id}").status_code == 403

        # And nothing changed.
        from app.estimate import store

        assert store.get(estimate_id).label == "Original name"

    def test_another_signed_in_user_cannot_change_it_either(
        self, client: TestClient, outbox
    ) -> None:
        owner = register(client, "owner3@example.com")
        intruder = register(client, "intruder@example.com")
        estimate_id = _save(owner["user"]["id"])

        response = client.delete(
            f"/api/estimate/{estimate_id}", headers=auth_headers(intruder)
        )
        assert response.status_code == 403

    def test_the_owner_can_change_it(self, client: TestClient, outbox) -> None:
        owner = register(client, "owner4@example.com")
        estimate_id = _save(owner["user"]["id"])

        renamed = client.post(
            f"/api/estimate/{estimate_id}/rename",
            json={"label": "Renamed by its owner"},
            headers=auth_headers(owner),
        )
        assert renamed.status_code == 200
        assert (
            client.delete(
                f"/api/estimate/{estimate_id}", headers=auth_headers(owner)
            ).status_code
            == 200
        )


# --------------------------------------------------------------------------------------
# Claiming
# --------------------------------------------------------------------------------------

class TestClaiming:
    def test_an_anonymous_estimate_can_be_claimed_after_signing_in(
        self, client: TestClient, outbox
    ) -> None:
        """The natural path: run an estimate, like it, then make an account."""
        estimate_id = _save()
        user = register(client, "claimer@example.com")

        response = client.post(
            "/api/auth/claim-estimate",
            json={"estimate_id": estimate_id},
            headers=auth_headers(user),
        )
        assert response.status_code == 200
        assert response.json()["claimed"] is True

        listing = client.get("/api/estimates", headers=auth_headers(user))
        assert [e["estimate_id"] for e in listing.json()["estimates"]] == [estimate_id]

    def test_an_estimate_that_already_has_an_owner_cannot_be_taken(
        self, client: TestClient, outbox
    ) -> None:
        owner = register(client, "keeps@example.com")
        thief = register(client, "thief@example.com")
        estimate_id = _save(owner["user"]["id"])

        response = client.post(
            "/api/auth/claim-estimate",
            json={"estimate_id": estimate_id},
            headers=auth_headers(thief),
        )
        assert response.status_code == 404

        from app.estimate import store

        assert store.owner_of(estimate_id) == owner["user"]["id"]

    def test_claiming_requires_an_account(self, client: TestClient) -> None:
        estimate_id = _save()
        assert (
            client.post(
                "/api/auth/claim-estimate", json={"estimate_id": estimate_id}
            ).status_code
            == 401
        )


# --------------------------------------------------------------------------------------
# Account deletion
# --------------------------------------------------------------------------------------

class TestAccountDeletion:
    def test_deleting_an_account_orphans_its_estimates_rather_than_destroying_them(
        self, client: TestClient, outbox
    ) -> None:
        """ON DELETE SET NULL, and the reason for it.

        By the time somebody closes their account, an estimate of theirs may already have
        been sent to an installer. Breaking that link is not something the account holder
        asked for, and it is not recoverable.
        """
        user = register(client, "leaving@example.com")
        estimate_id = _save(user["user"]["id"])

        from app.auth import service
        from app.db.base import session_scope
        from app.estimate import store

        with session_scope() as session:
            account = service.get_user_by_email(session, "leaving@example.com")
            session.delete(account)

        record = store.get(estimate_id)
        assert record is not None
        assert record.owner_id is None

        # And the link still works.
        assert client.get(f"/api/estimate/{estimate_id}").status_code == 200

    def test_deleting_an_account_removes_its_oauth_links(
        self, client: TestClient, outbox
    ) -> None:
        """ON DELETE CASCADE, because a credential linkage to a user who no longer exists
        is meaningless — and would block that provider identity from being reused."""
        from app.auth import service
        from app.db.base import session_scope
        from app.db.models import OAuthAccount

        register(client, "linked@example.com")

        with session_scope() as session:
            account = service.get_user_by_email(session, "linked@example.com")
            service.link_provider(
                session,
                account,
                provider="github",
                provider_account_id="99887766",
                email="linked@example.com",
                username="linked",
            )

        with session_scope() as session:
            account = service.get_user_by_email(session, "linked@example.com")
            session.delete(account)

        with session_scope() as session:
            remaining = session.query(OAuthAccount).count()
            assert remaining == 0


# --------------------------------------------------------------------------------------
# Retention
# --------------------------------------------------------------------------------------

class TestRetention:
    def test_the_retention_sweep_spares_owned_estimates(
        self, client: TestClient, outbox
    ) -> None:
        """An anonymous estimate has nobody to tidy up after it. An owned one does, and
        expiring somebody's saved work out from under them is data loss, not housekeeping.
        """
        from datetime import datetime, timedelta, timezone

        from app.db.base import session_scope
        from app.db.models import Estimate
        from app.estimate import store

        user = register(client, "keeper@example.com")
        owned = _save(user["user"]["id"])
        orphan = _save(None)

        long_ago = datetime.now(timezone.utc) - timedelta(days=800)
        with session_scope() as session:
            for estimate_id in (owned, orphan):
                session.get(Estimate, estimate_id).created_at = long_ago

        removed = store.prune(max_age_days=365)

        assert removed == 1
        assert store.get(orphan) is None
        assert store.get(owned) is not None
