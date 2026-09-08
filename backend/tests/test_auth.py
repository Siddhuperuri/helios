"""Authentication: registration, sessions, verification, reset and password policy.

These tests are written against the HTTP surface rather than the service functions,
because the properties worth protecting are properties of the endpoint. "The password is
hashed" is a unit test; "the response to registering an address that already exists is
byte-for-byte the response to registering a new one" is what actually stops account
enumeration, and it can only be checked from outside.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from tests.conftest import auth_headers, csrf_headers, link_token, login, register

PASSWORD = "a-long-enough-password"


# --------------------------------------------------------------------------------------
# Registration
# --------------------------------------------------------------------------------------

class TestRegistration:
    def test_register_creates_an_account_that_can_then_sign_in(
        self, client: TestClient, outbox
    ) -> None:
        created = client.post(
            "/api/auth/register", json={"email": "new@example.com", "password": PASSWORD}
        )
        assert created.status_code == 200
        # No session here, by design. See app.auth.routes.register.
        assert "access_token" not in created.json()
        assert len(outbox) == 1

        session = login(client, "new@example.com")
        assert session["user"]["email"] == "new@example.com"
        assert session["user"]["is_verified"] is False
        assert session["access_token"]
        assert session["expires_in"] > 0
        # The hash must never travel, under any key.
        assert "hashed_password" not in str(session)

    def test_the_refresh_token_is_httponly_and_the_csrf_token_is_not(
        self, client: TestClient, outbox
    ) -> None:
        client.post(
            "/api/auth/register", json={"email": "cookies@example.com", "password": PASSWORD}
        )
        response = client.post(
            "/api/auth/login", json={"email": "cookies@example.com", "password": PASSWORD}
        )
        header = response.headers.get("set-cookie", "")
        assert "helios_refresh=" in header
        assert "httponly" in header.lower()
        # The CSRF cookie has to be readable by our own page, or double-submit cannot work.
        csrf_part = [p for p in header.split("helios_csrf=") if p]
        assert csrf_part, header

    def test_an_existing_address_gets_byte_identical_treatment(
        self, client: TestClient, outbox
    ) -> None:
        """The account-enumeration property, checked structurally rather than by wording.

        A caller must not be able to tell whether an address is registered — not from the
        status, not from the body, not from whether a token came back. Comparing the whole
        response is the only assertion that keeps holding when somebody edits the copy.
        """
        fresh = client.post(
            "/api/auth/register", json={"email": "brand-new@example.com", "password": PASSWORD}
        )
        register(client, "taken@example.com")
        outbox.clear()

        second = client.post(
            "/api/auth/register",
            json={"email": "taken@example.com", "password": "another-password"},
        )

        assert second.status_code == fresh.status_code == 200
        assert second.json() == fresh.json()
        assert "access_token" not in second.json()

    def test_a_duplicate_registration_does_not_change_the_existing_password(
        self, client: TestClient, outbox
    ) -> None:
        """The other half of the same endpoint's safety.

        Answering uniformly would be worthless if the duplicate branch quietly overwrote
        the account's password with the one the caller supplied.
        """
        register(client, "unchanged@example.com")
        client.post(
            "/api/auth/register",
            json={"email": "unchanged@example.com", "password": "attacker-chosen-password"},
        )

        assert (
            client.post(
                "/api/auth/login",
                json={"email": "unchanged@example.com", "password": "attacker-chosen-password"},
            ).status_code
            == 401
        )
        assert (
            client.post(
                "/api/auth/login",
                json={"email": "unchanged@example.com", "password": PASSWORD},
            ).status_code
            == 200
        )

    def test_the_address_is_normalised(self, client: TestClient, outbox) -> None:
        client.post(
            "/api/auth/register",
            json={"email": "Mixed.Case@Example.COM", "password": PASSWORD},
        )
        # Same person: signing in with the lower-case form must reach the same account.
        session = login(client, "mixed.case@example.com")
        assert session["user"]["email"] == "mixed.case@example.com"

    @pytest.mark.parametrize("password", ["short", "", "         "])
    def test_a_weak_password_is_refused_with_a_reason(
        self, client: TestClient, outbox, password: str
    ) -> None:
        response = client.post(
            "/api/auth/register", json={"email": "weak@example.com", "password": password}
        )
        assert response.status_code == 422
        body = response.json()
        assert body["error"] in {"weak_password", "validation_error"}
        assert body["message"]

    @pytest.mark.parametrize("email", ["not-an-address", "@example.com", "a@", ""])
    def test_a_malformed_address_is_refused(
        self, client: TestClient, outbox, email: str
    ) -> None:
        response = client.post("/api/auth/register", json={"email": email, "password": PASSWORD})
        assert response.status_code == 422

    def test_unknown_fields_are_rejected(self, client: TestClient, outbox) -> None:
        response = client.post(
            "/api/auth/register",
            json={"email": "x@example.com", "password": PASSWORD, "is_admin": True},
        )
        assert response.status_code == 422


# --------------------------------------------------------------------------------------
# Login
# --------------------------------------------------------------------------------------

class TestLogin:
    def test_login_returns_a_session(self, client: TestClient, outbox) -> None:
        register(client, "login@example.com")
        response = client.post(
            "/api/auth/login", json={"email": "login@example.com", "password": PASSWORD}
        )
        assert response.status_code == 200
        assert response.json()["access_token"]

    def test_a_wrong_password_and_an_unknown_account_are_indistinguishable(
        self, client: TestClient, outbox
    ) -> None:
        register(client, "real@example.com")

        wrong = client.post(
            "/api/auth/login", json={"email": "real@example.com", "password": "wrong-password-here"}
        )
        unknown = client.post(
            "/api/auth/login", json={"email": "ghost@example.com", "password": PASSWORD}
        )

        assert wrong.status_code == unknown.status_code == 401
        assert wrong.json()["message"] == unknown.json()["message"]
        assert wrong.json()["error"] == unknown.json()["error"] == "invalid_credentials"

    def test_login_is_rate_limited_per_account(self, client: TestClient, outbox) -> None:
        register(client, "brute@example.com")
        statuses = [
            client.post(
                "/api/auth/login",
                json={"email": "brute@example.com", "password": f"wrong-password-{i}"},
            ).status_code
            for i in range(14)
        ]
        assert 429 in statuses, statuses

    def test_a_successful_login_clears_the_guessing_budget(
        self, client: TestClient, outbox
    ) -> None:
        """Somebody who mistypes their password a few times and then gets it right must
        not be locked out of their *next* login."""
        register(client, "fatfingers@example.com")
        for _ in range(5):
            client.post(
                "/api/auth/login",
                json={"email": "fatfingers@example.com", "password": "not-the-password"},
            )
        good = client.post(
            "/api/auth/login", json={"email": "fatfingers@example.com", "password": PASSWORD}
        )
        assert good.status_code == 200
        again = client.post(
            "/api/auth/login", json={"email": "fatfingers@example.com", "password": PASSWORD}
        )
        assert again.status_code == 200


# --------------------------------------------------------------------------------------
# Protected endpoints and refresh
# --------------------------------------------------------------------------------------

class TestSession:
    def test_me_requires_a_token(self, client: TestClient, outbox) -> None:
        assert client.get("/api/auth/me").status_code == 401

    def test_me_returns_the_account(self, client: TestClient, outbox) -> None:
        session = register(client, "me@example.com")
        response = client.get("/api/auth/me", headers=auth_headers(session))
        assert response.status_code == 200
        assert response.json()["user"]["email"] == "me@example.com"
        assert response.json()["authentication_methods"] == 1

    def test_a_tampered_token_is_refused(self, client: TestClient, outbox) -> None:
        session = register(client, "tamper@example.com")
        broken = session["access_token"][:-4] + "AAAA"
        response = client.get("/api/auth/me", headers={"Authorization": f"Bearer {broken}"})
        assert response.status_code == 401
        assert response.json()["error"] == "token_invalid"

    def test_a_refresh_token_is_not_accepted_as_a_bearer_token(
        self, client: TestClient, outbox
    ) -> None:
        """Typing confusion between the two token kinds is a real class of bug, so the
        access-token decoder checks the ``typ`` claim rather than only the signature."""
        register(client, "typed@example.com")
        refresh_cookie = client.cookies.get("helios_refresh")
        assert refresh_cookie
        response = client.get(
            "/api/auth/me", headers={"Authorization": f"Bearer {refresh_cookie}"}
        )
        assert response.status_code == 401

    def test_refresh_rotates_and_returns_a_new_access_token(
        self, client: TestClient, outbox
    ) -> None:
        register(client, "refresh@example.com")
        first_cookie = client.cookies.get("helios_refresh")

        response = client.post("/api/auth/refresh", headers=csrf_headers(client))
        assert response.status_code == 200
        assert response.json()["access_token"]
        assert client.cookies.get("helios_refresh") != first_cookie

    def test_refresh_without_the_csrf_header_is_refused(
        self, client: TestClient, outbox
    ) -> None:
        register(client, "csrf@example.com")
        response = client.post("/api/auth/refresh")
        assert response.status_code == 403
        assert response.json()["error"] == "csrf_failed"

    def test_a_forged_csrf_pair_is_refused(self, client: TestClient, outbox) -> None:
        """Plain double-submit accepts any matching pair, which something with cookie-write
        access to a sibling subdomain can produce. The token is signed for exactly this."""
        register(client, "forged@example.com")
        client.cookies.set("helios_csrf", "attacker-chosen.value")
        response = client.post(
            "/api/auth/refresh", headers={"X-CSRF-Token": "attacker-chosen.value"}
        )
        assert response.status_code == 403

    def test_a_rotated_refresh_token_cannot_be_reused(
        self, client: TestClient, outbox
    ) -> None:
        """Reuse is treated as theft: every session for the account is revoked."""
        register(client, "reuse@example.com")
        stolen = client.cookies.get("helios_refresh")

        client.post("/api/auth/refresh", headers=csrf_headers(client))

        # The rotation issued a fresh CSRF token too, so take that one and replay only the
        # stale refresh cookie. Otherwise this test would be checking CSRF, not reuse.
        headers = csrf_headers(client)
        client.cookies.set("helios_refresh", stolen)
        replay = client.post("/api/auth/refresh", headers=headers)
        assert replay.status_code == 401
        assert replay.json()["error"] == "token_revoked"

    def test_logout_revokes_the_refresh_token(self, client: TestClient, outbox) -> None:
        register(client, "logout@example.com")
        stale = client.cookies.get("helios_refresh")
        headers = csrf_headers(client)

        assert client.post("/api/auth/logout", headers=headers).status_code == 200

        # Logout clears both cookies; put back exactly what a thief would still hold.
        client.cookies.set("helios_refresh", stale)
        client.cookies.set("helios_csrf", headers["X-CSRF-Token"])
        assert client.post("/api/auth/refresh", headers=headers).status_code == 401


# --------------------------------------------------------------------------------------
# Email verification
# --------------------------------------------------------------------------------------

class TestVerification:
    def test_the_link_in_the_email_verifies_the_account(
        self, client: TestClient, outbox
    ) -> None:
        session = register(client, "verify@example.com")
        assert session["user"]["is_verified"] is False
        assert len(outbox) == 1

        response = client.post(
            "/api/auth/verify-email", json={"token": link_token(outbox)}
        )
        assert response.status_code == 200
        assert response.json()["verified"] is True
        assert response.json()["user"]["is_verified"] is True

    def test_a_verification_token_works_only_once(self, client: TestClient, outbox) -> None:
        register(client, "once@example.com")
        token = link_token(outbox)

        assert client.post("/api/auth/verify-email", json={"token": token}).status_code == 200
        second = client.post("/api/auth/verify-email", json={"token": token})
        assert second.status_code == 400
        assert second.json()["error"] == "token_invalid"

    def test_an_expired_token_says_so_specifically(self, client: TestClient, outbox) -> None:
        """``token_expired``, not a generic 400.

        The interface shows "request a new link" for one and "that link is not valid" for
        the other, and it can only tell them apart if the API does.
        """
        from app.security import tokens

        session = register(client, "expired@example.com")
        # A negative TTL rather than zero: with zero the token expires on the same clock
        # tick it was issued on, and whether the comparison sees it as expired depends on
        # the platform's timer resolution.
        token, _ = tokens.issue_email_token(
            "verify_email", session["user"]["id"], ttl_hours=-1
        )

        response = client.post("/api/auth/verify-email", json={"token": token})
        assert response.status_code == 400
        assert response.json()["error"] == "token_expired"
        assert "expired" in response.json()["message"].lower()

    def test_a_token_that_was_never_issued_is_invalid(
        self, client: TestClient, outbox
    ) -> None:
        response = client.post("/api/auth/verify-email", json={"token": "x" * 43})
        assert response.status_code == 400
        assert response.json()["error"] == "token_invalid"

    def test_resend_is_throttled(self, client: TestClient, outbox) -> None:
        register(client, "resend@example.com")
        outbox.clear()

        first = client.post(
            "/api/auth/resend-verification", json={"email": "resend@example.com"}
        )
        assert first.status_code == 200
        assert len(outbox) == 1

        second = client.post(
            "/api/auth/resend-verification", json={"email": "resend@example.com"}
        )
        assert second.status_code == 429
        assert "Retry-After" in second.headers
        assert len(outbox) == 1

    def test_resend_does_not_reveal_whether_an_account_exists(
        self, client: TestClient, outbox
    ) -> None:
        response = client.post(
            "/api/auth/resend-verification", json={"email": "nobody@example.com"}
        )
        assert response.status_code == 200
        assert len(outbox) == 0


# --------------------------------------------------------------------------------------
# Password reset
# --------------------------------------------------------------------------------------

class TestPasswordReset:
    def test_reset_sets_a_new_password_and_revokes_every_session(
        self, client: TestClient, outbox
    ) -> None:
        """The security-critical property of the whole flow.

        Somebody resets their password because they think an attacker has their session.
        If the attacker's refresh token still works afterwards, the reset achieved nothing.
        """
        register(client, "reset@example.com")
        attacker_token = client.cookies.get("helios_refresh")
        attacker_csrf = csrf_headers(client)
        outbox.clear()

        client.post("/api/auth/forgot-password", json={"email": "reset@example.com"})
        assert len(outbox) == 1

        response = client.post(
            "/api/auth/reset-password",
            json={"token": link_token(outbox), "password": "a-brand-new-password"},
        )
        assert response.status_code == 200

        # The old session is gone.
        client.cookies.set("helios_refresh", attacker_token)
        client.cookies.set("helios_csrf", attacker_csrf["X-CSRF-Token"])
        replay = client.post("/api/auth/refresh", headers=attacker_csrf)
        assert replay.status_code == 401

        # The old password is gone.
        assert (
            client.post(
                "/api/auth/login", json={"email": "reset@example.com", "password": PASSWORD}
            ).status_code
            == 401
        )
        # The new one works.
        assert (
            client.post(
                "/api/auth/login",
                json={"email": "reset@example.com", "password": "a-brand-new-password"},
            ).status_code
            == 200
        )

    def test_a_reset_token_works_only_once(self, client: TestClient, outbox) -> None:
        register(client, "single@example.com")
        outbox.clear()
        client.post("/api/auth/forgot-password", json={"email": "single@example.com"})
        token = link_token(outbox)

        assert (
            client.post(
                "/api/auth/reset-password", json={"token": token, "password": "first-new-password"}
            ).status_code
            == 200
        )
        second = client.post(
            "/api/auth/reset-password", json={"token": token, "password": "second-new-password"}
        )
        assert second.status_code == 400

    def test_an_expired_reset_token_says_so(self, client: TestClient, outbox) -> None:
        from app.security import tokens

        session = register(client, "stale@example.com")
        token, _ = tokens.issue_email_token(
            "password_reset", session["user"]["id"], ttl_hours=-1
        )
        response = client.post(
            "/api/auth/reset-password", json={"token": token, "password": "a-new-password-here"}
        )
        assert response.status_code == 400
        assert response.json()["error"] == "token_expired"

    def test_completing_a_reset_also_confirms_the_address(
        self, client: TestClient, outbox
    ) -> None:
        """Reading the reset email proves control of the mailbox, which is what
        verification asks for. Asking again would be asking twice."""
        register(client, "proof@example.com")
        outbox.clear()
        client.post("/api/auth/forgot-password", json={"email": "proof@example.com"})
        client.post(
            "/api/auth/reset-password",
            json={"token": link_token(outbox), "password": "yet-another-password"},
        )
        login = client.post(
            "/api/auth/login",
            json={"email": "proof@example.com", "password": "yet-another-password"},
        )
        assert login.json()["user"]["is_verified"] is True

    def test_forgot_password_does_not_reveal_whether_an_account_exists(
        self, client: TestClient, outbox
    ) -> None:
        response = client.post(
            "/api/auth/forgot-password", json={"email": "nobody-here@example.com"}
        )
        assert response.status_code == 200
        assert len(outbox) == 0


# --------------------------------------------------------------------------------------
# Changing a password from settings
# --------------------------------------------------------------------------------------

class TestChangePassword:
    def test_the_current_password_is_required(self, client: TestClient, outbox) -> None:
        session = register(client, "change@example.com")
        response = client.post(
            "/api/auth/change-password",
            json={"current_password": "not-it-either", "new_password": "a-fresh-password"},
            headers=auth_headers(session),
        )
        assert response.status_code == 403

    def test_changing_a_password_ends_other_sessions_but_not_this_one(
        self, client: TestClient, outbox
    ) -> None:
        session = register(client, "rotate@example.com")
        old_refresh = client.cookies.get("helios_refresh")
        old_csrf = csrf_headers(client)

        response = client.post(
            "/api/auth/change-password",
            json={"current_password": PASSWORD, "new_password": "the-newest-password"},
            headers=auth_headers(session),
        )
        assert response.status_code == 200
        # The caller is handed a working session rather than being signed out of the
        # device they are standing at.
        assert response.json()["access_token"]

        client.cookies.set("helios_refresh", old_refresh)
        client.cookies.set("helios_csrf", old_csrf["X-CSRF-Token"])
        assert client.post("/api/auth/refresh", headers=old_csrf).status_code == 401


# --------------------------------------------------------------------------------------
# Hashing
# --------------------------------------------------------------------------------------

class TestPasswordStorage:
    def test_the_stored_value_is_an_argon2id_hash(self, client: TestClient, outbox) -> None:
        register(client, "hashed@example.com")

        from app.auth import service
        from app.db.base import session_scope

        with session_scope() as session:
            user = service.get_user_by_email(session, "hashed@example.com")
            assert user is not None
            assert user.hashed_password.startswith("$argon2id$")
            assert PASSWORD not in user.hashed_password

    def test_two_accounts_with_the_same_password_have_different_hashes(
        self, client: TestClient, outbox
    ) -> None:
        register(client, "one@example.com")
        register(client, "two@example.com")

        from app.auth import service
        from app.db.base import session_scope

        with session_scope() as db:
            first = service.get_user_by_email(db, "one@example.com")
            second = service.get_user_by_email(db, "two@example.com")
            assert first.hashed_password != second.hashed_password
