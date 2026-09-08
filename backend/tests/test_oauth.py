"""Google and GitHub sign-in.

The provider is stubbed at the module boundary — ``exchange_code`` and ``fetch_profile``
are replaced — because what is worth testing here is not that Google's token endpoint
works. It is the account model around it, where the security-relevant decisions live:

* what happens when a provider identity is already linked,
* what happens when it is not but the email matches an existing account,
* who is allowed to link and unlink, and
* whether somebody can lock themselves out by disconnecting their only way in.

The redirect allowlist is tested directly, because an open redirect on a callback that
carries a fresh session is one of the more damaging things this module could get wrong.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from tests.conftest import auth_headers, register


def stub_provider(monkeypatch, *, account_id: str, email: str | None, username: str = "someone"):
    """Replace the two functions that talk to the provider."""
    from app.auth import oauth

    monkeypatch.setattr(oauth, "exchange_code", lambda p, c, v: "stub-access-token")
    monkeypatch.setattr(
        oauth,
        "fetch_profile",
        lambda p, t: oauth.OAuthProfile(
            provider=p,
            account_id=account_id,
            email=email,
            email_verified=email is not None,
            display_name=username.title(),
            username=username,
        ),
    )


def complete_flow(
    client: TestClient, provider: str = "github", *, headers: dict | None = None
) -> str:
    """Run authorize → callback and return the callback's Location header."""
    authorize = client.get(
        f"/api/auth/oauth/{provider}/authorize",
        follow_redirects=False,
        headers=headers or {},
    )
    assert authorize.status_code == 307, authorize.text
    state = authorize.headers["location"].split("state=")[1].split("&")[0]

    callback = client.get(
        f"/api/auth/oauth/{provider}/callback?code=stub-code&state={state}",
        follow_redirects=False,
        headers=headers or {},
    )
    return callback.headers.get("location", "")


# --------------------------------------------------------------------------------------
# Provider availability
# --------------------------------------------------------------------------------------

class TestProviderAvailability:
    def test_configured_providers_are_advertised(self, client: TestClient) -> None:
        """The frontend asks so it does not render a button that leads to a 503."""
        response = client.get("/api/auth/providers")
        assert response.status_code == 200
        assert set(response.json()["providers"]) == {"google", "github"}

    def test_an_unconfigured_provider_refuses_clearly(
        self, client: TestClient, monkeypatch
    ) -> None:
        monkeypatch.delenv("GOOGLE_OAUTH_CLIENT_ID", raising=False)
        from app.config import reset_settings

        reset_settings()

        response = client.get("/api/auth/oauth/google/authorize", follow_redirects=False)
        assert response.status_code == 503
        assert "GOOGLE_OAUTH_CLIENT_ID" in response.json()["message"]

    def test_an_unknown_provider_is_a_404(self, client: TestClient) -> None:
        response = client.get("/api/auth/oauth/facebook/authorize", follow_redirects=False)
        assert response.status_code == 404


# --------------------------------------------------------------------------------------
# The authorize step
# --------------------------------------------------------------------------------------

class TestAuthorize:
    def test_the_authorize_url_carries_state_and_pkce(self, client: TestClient) -> None:
        response = client.get("/api/auth/oauth/github/authorize", follow_redirects=False)
        assert response.status_code == 307
        location = response.headers["location"]

        assert location.startswith("https://github.com/login/oauth/authorize?")
        assert "state=" in location
        assert "code_challenge=" in location
        assert "code_challenge_method=S256" in location
        # The secret must never appear in a URL handed to a browser.
        assert "client_secret" not in location

    def test_the_redirect_uri_is_the_registered_callback(self, client: TestClient) -> None:
        response = client.get("/api/auth/oauth/google/authorize", follow_redirects=False)
        location = response.headers["location"]
        assert "redirect_uri=http%3A%2F%2F127.0.0.1%3A8000%2Fapi%2Fauth%2Foauth%2Fgoogle%2Fcallback" in location


# --------------------------------------------------------------------------------------
# Sign-in and sign-up
# --------------------------------------------------------------------------------------

class TestSignIn:
    def test_a_new_provider_identity_creates_a_verified_account(
        self, client: TestClient, monkeypatch
    ) -> None:
        """No verification email: the provider has already established that the person
        controls the address, and asking again would be asking twice."""
        stub_provider(monkeypatch, account_id="111", email="fresh@example.com")

        location = complete_flow(client)
        assert "auth_code=" in location
        assert "created=1" in location

        code = location.split("auth_code=")[1].split("&")[0]
        session = client.post("/api/auth/oauth/exchange", json={"code": code})
        assert session.status_code == 200
        assert session.json()["user"]["email"] == "fresh@example.com"
        assert session.json()["user"]["is_verified"] is True
        assert session.json()["user"]["has_password"] is False
        assert session.json()["user"]["providers"] == ["github"]

    def test_signing_in_again_reuses_the_same_account(
        self, client: TestClient, monkeypatch
    ) -> None:
        stub_provider(monkeypatch, account_id="222", email="returning@example.com")

        first = complete_flow(client)
        second = complete_flow(client)

        assert "created=1" in first
        assert "created=1" not in second

        from app.auth import service
        from app.db.base import session_scope

        with session_scope() as session:
            assert service.count_users(session) == 1

    def test_a_matching_email_does_not_silently_merge_accounts(
        self, client: TestClient, monkeypatch, outbox
    ) -> None:
        """The account-takeover defence.

        Somebody has a password account at this address. A provider now asserts the same
        address. Merging on that basis would mean anyone who can get a provider to assert
        an address inherits the account behind it — so instead the flow refuses and asks
        for an explicit, authenticated link.
        """
        register(client, "existing@example.com")
        stub_provider(monkeypatch, account_id="333", email="existing@example.com")

        location = complete_flow(client)

        assert "auth_error=link_required" in location
        assert "auth_code=" not in location

        from app.db.base import session_scope
        from app.db.models import OAuthAccount

        with session_scope() as session:
            assert session.query(OAuthAccount).count() == 0

    def test_a_provider_that_shares_no_address_is_refused_with_a_reason(
        self, client: TestClient, monkeypatch
    ) -> None:
        """GitHub hides the address unless it is public and verified."""
        stub_provider(monkeypatch, account_id="444", email=None)

        location = complete_flow(client)
        assert "auth_error=email_required" in location

    def test_a_replayed_callback_is_refused(self, client: TestClient, monkeypatch) -> None:
        stub_provider(monkeypatch, account_id="555", email="replay@example.com")

        authorize = client.get("/api/auth/oauth/github/authorize", follow_redirects=False)
        state = authorize.headers["location"].split("state=")[1].split("&")[0]

        first = client.get(
            f"/api/auth/oauth/github/callback?code=stub-code&state={state}",
            follow_redirects=False,
        )
        assert "auth_code=" in first.headers["location"]

        second = client.get(
            f"/api/auth/oauth/github/callback?code=stub-code&state={state}",
            follow_redirects=False,
        )
        assert "auth_error=invalid_state" in second.headers["location"]

    def test_a_callback_with_no_state_is_refused(self, client: TestClient) -> None:
        response = client.get(
            "/api/auth/oauth/github/callback?code=stub-code", follow_redirects=False
        )
        assert "auth_error=oauth_invalid" in response.headers["location"]

    def test_a_declined_consent_screen_is_reported_gently(self, client: TestClient) -> None:
        response = client.get(
            "/api/auth/oauth/github/callback?error=access_denied", follow_redirects=False
        )
        assert "auth_error=oauth_declined" in response.headers["location"]

    def test_the_handoff_code_expires_after_one_use(
        self, client: TestClient, monkeypatch
    ) -> None:
        stub_provider(monkeypatch, account_id="666", email="onceonly@example.com")
        location = complete_flow(client)
        code = location.split("auth_code=")[1].split("&")[0]

        assert client.post("/api/auth/oauth/exchange", json={"code": code}).status_code == 200
        assert client.post("/api/auth/oauth/exchange", json={"code": code}).status_code == 400


# --------------------------------------------------------------------------------------
# Linking
# --------------------------------------------------------------------------------------

class TestLinking:
    def test_a_signed_in_user_can_link_a_provider(
        self, client: TestClient, monkeypatch, outbox
    ) -> None:
        session = register(client, "linker@example.com")
        stub_provider(monkeypatch, account_id="777", email="linker@example.com")

        location = complete_flow(client, "github", headers=auth_headers(session))
        assert "linked=github" in location

        me = client.get("/api/auth/me", headers=auth_headers(session))
        assert me.json()["user"]["providers"] == ["github"]
        assert me.json()["authentication_methods"] == 2

    def test_a_provider_identity_cannot_be_linked_to_two_accounts(
        self, client: TestClient, monkeypatch, outbox
    ) -> None:
        first = register(client, "first@example.com")
        second = register(client, "second@example.com")
        stub_provider(monkeypatch, account_id="888", email="shared@example.com")

        assert "linked=github" in complete_flow(client, "github", headers=auth_headers(first))

        location = complete_flow(client, "github", headers=auth_headers(second))
        assert "auth_error=provider_already_linked" in location

    def test_linking_requires_a_session(self, client: TestClient, monkeypatch) -> None:
        response = client.get("/api/auth/oauth/github/link", follow_redirects=False)
        assert response.status_code == 401


class TestUnlinking:
    def test_a_provider_can_be_disconnected_when_a_password_remains(
        self, client: TestClient, monkeypatch, outbox
    ) -> None:
        session = register(client, "unlinker@example.com")
        stub_provider(monkeypatch, account_id="999", email="unlinker@example.com")
        complete_flow(client, "github", headers=auth_headers(session))

        response = client.delete("/api/auth/oauth/github", headers=auth_headers(session))
        assert response.status_code == 200
        assert response.json()["user"]["providers"] == []

    def test_the_last_authentication_method_cannot_be_removed(
        self, client: TestClient, monkeypatch
    ) -> None:
        """The lock-yourself-out defence.

        An account created through Google has no password. Disconnecting Google would
        leave no way in at all — and no way to recover, because password reset needs a
        password to reset to.
        """
        stub_provider(monkeypatch, account_id="1010", email="oauthonly@example.com")
        location = complete_flow(client)
        code = location.split("auth_code=")[1].split("&")[0]
        session = client.post("/api/auth/oauth/exchange", json={"code": code}).json()

        response = client.delete("/api/auth/oauth/github", headers=auth_headers(session))
        assert response.status_code == 409
        assert response.json()["error"] == "last_auth_method"
        assert "password" in response.json()["message"].lower()

    def test_setting_a_password_then_unlinking_is_allowed(
        self, client: TestClient, monkeypatch
    ) -> None:
        """The escape route the refusal above points at has to actually work."""
        stub_provider(monkeypatch, account_id="1111", email="upgrading@example.com")
        location = complete_flow(client)
        code = location.split("auth_code=")[1].split("&")[0]
        session = client.post("/api/auth/oauth/exchange", json={"code": code}).json()

        # No current password to supply: this is setting a first one, and the valid
        # session is the proof.
        changed = client.post(
            "/api/auth/change-password",
            json={"new_password": "a-first-real-password"},
            headers=auth_headers(session),
        )
        assert changed.status_code == 200

        unlinked = client.delete(
            "/api/auth/oauth/github", headers=auth_headers(changed.json())
        )
        assert unlinked.status_code == 200

    def test_unlinking_a_provider_that_is_not_connected_is_a_404(
        self, client: TestClient, outbox
    ) -> None:
        session = register(client, "nothinglinked@example.com")
        response = client.delete("/api/auth/oauth/google", headers=auth_headers(session))
        assert response.status_code == 404


# --------------------------------------------------------------------------------------
# Redirect safety
# --------------------------------------------------------------------------------------

class TestRedirectAllowlist:
    @pytest.mark.parametrize(
        "candidate",
        [
            "https://evil.example.com/steal",
            "http://localhost:3000.evil.test/",
            "//evil.example.com",
            "javascript:alert(1)",
            "data:text/html,<script>alert(1)</script>",
            "https://localhost:3000@evil.example.com/",
        ],
    )
    def test_a_destination_outside_the_allowlist_is_replaced(
        self, client: TestClient, candidate: str
    ) -> None:
        """An open redirect on this callback would arrive carrying a fresh session."""
        from app.auth import oauth

        resolved = oauth.resolve_redirect(candidate)
        assert resolved == "http://localhost:3000"

    @pytest.mark.parametrize(
        "candidate,expected",
        [
            ("/projects", "http://localhost:3000/projects"),
            ("/result/abc123", "http://localhost:3000/result/abc123"),
            ("http://localhost:3000/account", "http://localhost:3000/account"),
            (None, "http://localhost:3000"),
        ],
    )
    def test_an_allowed_destination_is_kept(
        self, client: TestClient, candidate: str | None, expected: str
    ) -> None:
        from app.auth import oauth

        assert oauth.resolve_redirect(candidate) == expected

    def test_a_prefix_match_is_not_enough(self, client: TestClient) -> None:
        """``https://localhost:3000.evil.test`` starts with the allowed origin as a string
        and is a completely different host. Comparison is on scheme, host and port."""
        from app.auth import oauth

        assert oauth.resolve_redirect("http://localhost:3000.evil.test/x") == (
            "http://localhost:3000"
        )
