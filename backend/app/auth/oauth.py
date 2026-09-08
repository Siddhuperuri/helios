"""Google and GitHub sign-in.

The whole reason this module looks the way it does is one sentence: the request that
*starts* an OAuth flow and the request that *finishes* it are two different requests, and
behind a load balancer they land on two different replicas.

    Authorize  →  Backend 1
    Callback   →  Backend 2

Anything the authorize step remembers must therefore be readable by every replica. State,
nonce and PKCE verifier all go into Redis under the state value, with a ten-minute TTL and
single-use consumption. Keeping them in a module global or a server-side session — which is
what most examples do — produces a flow that works perfectly on a laptop and fails roughly
two times in three in production.

What is checked, and why
------------------------
*State* is compared and consumed exactly once. It is what ties the callback to a flow this
application actually started, and it is the CSRF defence for the callback itself.

*PKCE* is used for both providers. It means an intercepted authorization code cannot be
exchanged by anyone who does not hold the verifier, which never leaves Redis.

*The post-login destination* is checked against an allowlist before anyone is sent to it. A
callback that redirects wherever a query parameter says is an open redirect that arrives
carrying a freshly minted session.

The ID token is deliberately not parsed. Both providers' user data is read from their
userinfo endpoint over TLS with the access token, so there is no JWT signature to verify
against a rotating JWKS — one less thing to get wrong for no loss of assurance.
"""

from __future__ import annotations

import base64
import hashlib
import json
import logging
import secrets
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlencode, urlparse

import requests

from app.config import OAuthProviderSettings, get_settings
from app.infra import redis_client

logger = logging.getLogger(__name__)

SUPPORTED_PROVIDERS = ("google", "github")


class OAuthError(Exception):
    def __init__(self, code: str, message: str, *, status: int = 400) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.status = status


@dataclass(frozen=True)
class OAuthProfile:
    """The parts of a provider's answer this application uses."""

    provider: str
    account_id: str
    email: str | None
    email_verified: bool
    display_name: str | None
    username: str | None


@dataclass(frozen=True)
class FlowState:
    provider: str
    code_verifier: str
    nonce: str
    redirect_to: str
    # "login" starts or resumes a session; "link" attaches the identity to the account that
    # began the flow. Carried through the round trip so the callback knows which it is.
    intent: str
    user_id: str | None


def _provider(name: str) -> OAuthProviderSettings:
    settings = get_settings().oauth
    provider = settings.provider(name)
    if provider is None:
        raise OAuthError(
            "unknown_provider",
            f"'{name}' is not a supported sign-in provider.",
            status=404,
        )
    if not provider.configured:
        raise OAuthError(
            "provider_not_configured",
            (
                f"{name.title()} sign-in is not available on this deployment. It needs "
                f"{name.upper()}_OAUTH_CLIENT_ID and {name.upper()}_OAUTH_CLIENT_SECRET."
            ),
            status=503,
        )
    return provider


def available_providers() -> list[str]:
    """Which providers this deployment can actually offer.

    The frontend asks so that it does not render a "Continue with GitHub" button that
    leads to a 503.
    """
    return list(get_settings().oauth.configured_providers)


# --------------------------------------------------------------------------------------
# Redirect allowlisting
# --------------------------------------------------------------------------------------

def resolve_redirect(candidate: str | None) -> str:
    """Turn a requested destination into one we are willing to send a browser to.

    Anything not on the allowlist is replaced with the configured frontend origin rather
    than rejected: a stale bookmark should land the user on the site, not on an error page.
    Comparison is on scheme, host and port — never on a string prefix, which
    ``https://helios.example.com.attacker.test`` would pass.
    """
    settings = get_settings().oauth
    default = settings.frontend_base
    if not candidate:
        return default

    if candidate.startswith("/") and not candidate.startswith("//"):
        # A relative path within the frontend is always fine, and is the common case.
        return f"{default}{candidate}"

    try:
        parsed = urlparse(candidate)
    except ValueError:
        return default
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        return default

    origin = f"{parsed.scheme}://{parsed.netloc}"
    allowed = {a.rstrip("/") for a in settings.allowed_redirects} | {default}
    if origin.rstrip("/") not in allowed:
        logger.warning("Rejected an OAuth redirect to a destination that is not allowlisted")
        return default
    return candidate


# --------------------------------------------------------------------------------------
# Cross-replica flow state
# --------------------------------------------------------------------------------------

def _state_key(state: str) -> str:
    return redis_client.key("oauth-state", state)


def begin(
    provider_name: str,
    *,
    redirect_to: str | None,
    intent: str = "login",
    user_id: str | None = None,
) -> str:
    """Start a flow and return the provider's authorization URL."""
    provider = _provider(provider_name)
    settings = get_settings()

    state = secrets.token_urlsafe(32)
    nonce = secrets.token_urlsafe(16)
    code_verifier = secrets.token_urlsafe(64)
    challenge = (
        base64.urlsafe_b64encode(hashlib.sha256(code_verifier.encode("ascii")).digest())
        .decode("ascii")
        .rstrip("=")
    )

    payload = {
        "provider": provider_name,
        "code_verifier": code_verifier,
        "nonce": nonce,
        "redirect_to": resolve_redirect(redirect_to),
        "intent": intent,
        "user_id": user_id,
    }
    try:
        redis_client.get_client().set(
            _state_key(state),
            json.dumps(payload),
            ex=settings.auth.oauth_state_ttl_seconds,
            nx=True,
        )
    except Exception as exc:  # noqa: BLE001
        # Without shared state the callback cannot be validated on another replica, and
        # validating it on this one only would be a coin flip. Refuse rather than start a
        # flow that will probably fail.
        raise OAuthError(
            "state_unavailable",
            "Sign-in is temporarily unavailable. Try again in a moment.",
            status=503,
        ) from exc

    params = {
        "client_id": provider.client_id,
        "redirect_uri": settings.oauth.callback_url(provider_name),
        "response_type": "code",
        "scope": provider.scope,
        "state": state,
        "code_challenge": challenge,
        "code_challenge_method": "S256",
    }
    if provider_name == "google":
        params["nonce"] = nonce
        # Ask for a fresh consent screen only when we need one; `select_account` lets a
        # person with several Google accounts choose rather than being silently signed in
        # as whichever one the browser remembers.
        params["prompt"] = "select_account"
    return f"{provider.authorize_url}?{urlencode(params)}"


def consume_state(state: str) -> FlowState:
    """Validate and spend a state value."""
    if not state or len(state) > 256:
        raise OAuthError("invalid_state", "That sign-in link is not valid.")

    client = redis_client.get_client()
    key = _state_key(state)
    raw = client.get(key)
    if raw is None:
        raise OAuthError(
            "invalid_state",
            "That sign-in attempt has expired or was already completed. Start again.",
        )
    # Single use: a replayed callback must not work even a millisecond later.
    client.delete(key)

    try:
        payload = json.loads(raw)
        return FlowState(
            provider=payload["provider"],
            code_verifier=payload["code_verifier"],
            nonce=payload.get("nonce", ""),
            redirect_to=payload.get("redirect_to") or get_settings().oauth.frontend_base,
            intent=payload.get("intent", "login"),
            user_id=payload.get("user_id"),
        )
    except (json.JSONDecodeError, KeyError) as exc:
        raise OAuthError("invalid_state", "That sign-in link is not valid.") from exc


# --------------------------------------------------------------------------------------
# Token exchange and profile
# --------------------------------------------------------------------------------------

def exchange_code(provider_name: str, code: str, code_verifier: str) -> str:
    """Trade an authorization code for an access token."""
    provider = _provider(provider_name)
    settings = get_settings()

    data = {
        "grant_type": "authorization_code",
        "code": code,
        "redirect_uri": settings.oauth.callback_url(provider_name),
        "client_id": provider.client_id,
        "client_secret": provider.client_secret,
        "code_verifier": code_verifier,
    }
    try:
        response = requests.post(
            provider.token_url,
            data=data,
            headers={"Accept": "application/json"},
            timeout=15,
        )
    except requests.RequestException as exc:
        raise OAuthError(
            "provider_unreachable",
            f"We could not reach {provider_name.title()}. Try again in a moment.",
            status=502,
        ) from exc

    if response.status_code >= 400:
        # The body can contain the client_secret we just sent in an echoed request, so it
        # is summarised rather than logged or returned.
        logger.warning(
            "%s token exchange failed with HTTP %s", provider_name, response.status_code
        )
        raise OAuthError(
            "token_exchange_failed",
            f"{provider_name.title()} refused the sign-in. Start again.",
            status=502,
        )

    try:
        payload = response.json()
    except ValueError as exc:
        raise OAuthError(
            "token_exchange_failed",
            f"{provider_name.title()} returned an unreadable response.",
            status=502,
        ) from exc

    if payload.get("error"):
        logger.warning("%s token exchange error: %s", provider_name, payload.get("error"))
        raise OAuthError(
            "token_exchange_failed",
            f"{provider_name.title()} refused the sign-in. Start again.",
            status=502,
        )

    access_token = payload.get("access_token")
    if not access_token:
        raise OAuthError(
            "token_exchange_failed",
            f"{provider_name.title()} did not return an access token.",
            status=502,
        )
    return str(access_token)


def _get_json(url: str, access_token: str, provider_name: str) -> Any:
    try:
        response = requests.get(
            url,
            headers={
                "Authorization": f"Bearer {access_token}",
                "Accept": "application/json",
                "User-Agent": "Helios-Solar-Intelligence",
            },
            timeout=15,
        )
    except requests.RequestException as exc:
        raise OAuthError(
            "provider_unreachable",
            f"We could not reach {provider_name.title()}. Try again in a moment.",
            status=502,
        ) from exc
    if response.status_code >= 400:
        raise OAuthError(
            "profile_unavailable",
            f"{provider_name.title()} would not share your profile.",
            status=502,
        )
    try:
        return response.json()
    except ValueError as exc:
        raise OAuthError(
            "profile_unavailable",
            f"{provider_name.title()} returned an unreadable profile.",
            status=502,
        ) from exc


def fetch_profile(provider_name: str, access_token: str) -> OAuthProfile:
    provider = _provider(provider_name)
    payload = _get_json(provider.userinfo_url, access_token, provider_name)

    if provider_name == "google":
        # Google's OIDC userinfo response reports whether it has verified the address.
        # An unverified one is not treated as proof of anything.
        verified = bool(payload.get("email_verified"))
        return OAuthProfile(
            provider="google",
            account_id=str(payload.get("sub") or ""),
            email=(payload.get("email") or None) if verified else None,
            email_verified=verified,
            display_name=payload.get("name"),
            username=payload.get("email"),
        )

    # GitHub's /user omits the address when the person has it hidden, and never says
    # whether it is verified. /user/emails does both, so it is asked separately and only
    # a primary *verified* address is accepted.
    email: str | None = None
    verified = False
    for entry in _get_json("https://api.github.com/user/emails", access_token, "github") or []:
        if isinstance(entry, dict) and entry.get("primary") and entry.get("verified"):
            email = entry.get("email")
            verified = True
            break

    return OAuthProfile(
        provider="github",
        account_id=str(payload.get("id") or ""),
        email=email,
        email_verified=verified,
        display_name=payload.get("name") or payload.get("login"),
        username=payload.get("login"),
    )


def complete(state: str, code: str) -> tuple[FlowState, OAuthProfile]:
    """Validate the callback and return the flow it belongs to with the profile behind it."""
    flow = consume_state(state)
    if not code or len(code) > 2048:
        raise OAuthError("invalid_code", "That sign-in could not be completed. Start again.")
    access_token = exchange_code(flow.provider, code, flow.code_verifier)
    profile = fetch_profile(flow.provider, access_token)
    if not profile.account_id:
        raise OAuthError(
            "profile_unavailable",
            f"{flow.provider.title()} did not identify the account. Start again.",
            status=502,
        )
    return flow, profile
