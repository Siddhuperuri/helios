"""CSRF protection for the cookie-authenticated endpoints.

Only two endpoints authenticate with a cookie — ``/api/auth/refresh`` and
``/api/auth/logout`` — because only those two need to work when the access token in
memory has expired or is gone. Everything else carries a bearer token in a header, which a
cross-site request cannot set, so it is not forgeable in the first place.

Those two, though, are exactly the shape CSRF exploits: the browser attaches the refresh
cookie automatically, so a form on another site could silently mint a session or destroy
one. ``SameSite=Lax`` blocks most of that and is set, but it is a defence with known gaps —
it does not separate sibling subdomains, and browsers differ on what counts as a top-level
navigation — so it is not the only thing standing here.

The mechanism is a signed double-submit token. A random value is signed with the
application's secret and placed in a cookie the frontend *can* read; the frontend echoes it
in a request header. An attacker on another origin can cause the cookie to be sent but
cannot read it and cannot set the header, so the two cannot be made to match. Signing the
value additionally means a token planted by something with cookie-write access to a sibling
subdomain is rejected, which plain double-submit would accept.
"""

from __future__ import annotations

import hashlib
import hmac
import logging
import secrets

from fastapi import Request

from app.config import get_settings

logger = logging.getLogger(__name__)

SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS", "TRACE"})


class CSRFError(Exception):
    """The CSRF check failed. Rendered as 403 with an actionable message."""

    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


def _sign(value: str) -> str:
    secret = get_settings().auth.jwt_secret.encode("utf-8")
    return hmac.new(secret, value.encode("utf-8"), hashlib.sha256).hexdigest()[:32]


def issue_token() -> str:
    """A fresh CSRF token, in ``<random>.<signature>`` form."""
    value = secrets.token_urlsafe(24)
    return f"{value}.{_sign(value)}"


def is_valid(token: str | None) -> bool:
    """Whether a token was minted by this application and has not been altered."""
    if not token or "." not in token or len(token) > 256:
        return False
    value, _, signature = token.rpartition(".")
    if not value or not signature:
        return False
    return hmac.compare_digest(signature, _sign(value))


def validate(request: Request) -> None:
    """Enforce the double-submit rule on an unsafe, cookie-authenticated request.

    Raises :class:`CSRFError` on failure. Safe methods are exempt, and so is a request
    that authenticates with a bearer token instead of the cookie: there is nothing to
    forge when the credential has to be attached by script that the attacker's origin
    cannot run.
    """
    if request.method.upper() in SAFE_METHODS:
        return

    auth = get_settings().auth
    cookie_token = request.cookies.get(auth.csrf_cookie_name)
    header_token = request.headers.get(auth.csrf_header_name)

    if not cookie_token or not header_token:
        raise CSRFError(
            "This request is missing its CSRF token. Reload the page and try again."
        )
    if not hmac.compare_digest(cookie_token, header_token):
        raise CSRFError(
            "The CSRF token did not match. Reload the page and try again."
        )
    if not is_valid(cookie_token):
        # A matching pair that we did not sign: something wrote both, which is the
        # subdomain-injection case plain double-submit misses.
        logger.warning("Rejected a CSRF token pair that this application did not sign")
        raise CSRFError(
            "The CSRF token was not issued by this application. Sign in again."
        )


def requires_csrf(request: Request) -> bool:
    """Whether this request relies on cookie authentication and must therefore be checked."""
    if request.method.upper() in SAFE_METHODS:
        return False
    if request.headers.get("Authorization", "").lower().startswith("bearer "):
        return False
    return get_settings().auth.refresh_cookie_name in request.cookies
