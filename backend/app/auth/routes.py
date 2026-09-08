"""Account endpoints.

Everything under ``/api/auth``. Three conventions hold across all of it.

**Responses do not leak whether an address has an account.** Registration, resend and
forgot-password answer identically whether or not the address is known — same status, same
body, same set of cookies. That costs a little clarity for the honest user, and it is
bought back by saying plainly what will happen: *if there is an account, a message is on
its way*. It is also why registration does not return a session; see :func:`register`.

**Access tokens go in the body, refresh tokens go in a cookie.** The access token is held in
the frontend's memory and attached as a bearer header; it is never written to
``localStorage``, where any script on the page could read it. The refresh token is httpOnly
and therefore unreadable by script at all, which is the point — but it is also sent
automatically, so the endpoints that rely on it carry CSRF protection.

**Nothing here is required to use the calculator.** These routes exist alongside the product;
they are not in front of it.
"""

from __future__ import annotations

import json
import logging
import secrets
from typing import Any, Literal
from urllib.parse import urlencode

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session

from app.auth import oauth as oauth_flow
from app.auth import service
from app.auth.deps import current_user, optional_user, rate_limit_identity
from app.auth.schemas import (
    ChangePasswordRequest,
    ClaimEstimateRequest,
    ForgotPasswordRequest,
    LoginRequest,
    OAuthExchangeRequest,
    RegisterRequest,
    ResendVerificationRequest,
    ResetPasswordRequest,
    UpdateProfileRequest,
    VerifyEmailRequest,
)
from app.config import get_settings
from app.db.base import get_session
from app.db.models import User
from app.email import sender as email_sender
from app.email import templates as email_templates
from app.estimate import store as estimate_store
from app.infra import redis_client
from app.observability import metrics
from app.security import csrf, passwords, rate_limit, tokens

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/auth", tags=["auth"])


# --------------------------------------------------------------------------------------
# Helpers
# --------------------------------------------------------------------------------------

def _fail(code: str, message: str, *, status: int = 400, remedy: str | None = None) -> HTTPException:
    """Build an error in the envelope the rest of the API uses.

    The frontend renders ``message`` verbatim and switches on ``error``, so both matter:
    one is for the person, the other is for the client.
    """
    detail: dict[str, Any] = {"error": code, "message": message}
    if remedy:
        detail["remedy"] = remedy
    return HTTPException(status_code=status, detail=detail)


def _limit(request: Request, bucket: str, *, limit: int, window_s: int, identity: str | None = None) -> None:
    """Apply one of the aggressive auth limits, or raise 429.

    Counted in Redis, so it is one budget for the client across every replica. See
    :mod:`app.security.rate_limit`.
    """
    who = identity or rate_limit_identity(request)
    result = rate_limit.check(bucket, who, limit=limit, window_s=window_s)
    if not result.allowed:
        raise HTTPException(
            status_code=429,
            detail={
                "error": "rate_limited",
                "message": "Too many attempts. Wait a moment before trying again.",
                "remedy": f"Try again in {result.retry_after_s} seconds.",
            },
            headers=result.headers(),
        )


def _samesite(value: str) -> Literal["lax", "strict", "none"]:
    normalised = (value or "").strip().lower()
    if normalised in ("lax", "strict", "none"):
        return normalised  # type: ignore[return-value]
    logger.warning(
        "SOLAR_COOKIE_SAMESITE=%r is not one of lax/strict/none; using 'lax'", value
    )
    return "lax"


def _set_session_cookies(response: Response, refresh_token: str, refresh_ttl: int) -> str:
    """Attach the refresh cookie and a matching CSRF cookie. Returns the CSRF token.

    The refresh cookie is httpOnly so no script can read it. The CSRF cookie deliberately
    is not: the frontend has to read it to echo it back in a header, and that asymmetry —
    readable by our own page, unreadable by another origin — is exactly what makes
    double-submit work.
    """
    auth = get_settings().auth
    csrf_token = csrf.issue_token()
    # SOLAR_COOKIE_SAMESITE is a free-form string in the environment and a closed set here.
    # Anything unrecognised falls back to "lax" rather than being passed through, because
    # a typo silently producing an invalid attribute would drop the cookie entirely.
    samesite = _samesite(auth.cookie_samesite)

    response.set_cookie(
        auth.refresh_cookie_name,
        refresh_token,
        max_age=refresh_ttl,
        httponly=True,
        secure=auth.cookie_secure,
        samesite=samesite,
        domain=auth.cookie_domain,
        # Scoped to the endpoints that use it. The cookie is not attached to estimate or
        # analysis requests at all, which removes it from most of the attack surface.
        path="/api/auth",
    )
    response.set_cookie(
        auth.csrf_cookie_name,
        csrf_token,
        max_age=refresh_ttl,
        httponly=False,
        secure=auth.cookie_secure,
        samesite=samesite,
        domain=auth.cookie_domain,
        path="/",
    )
    return csrf_token


def _clear_session_cookies(response: Response) -> None:
    auth = get_settings().auth
    response.delete_cookie(
        auth.refresh_cookie_name, path="/api/auth", domain=auth.cookie_domain
    )
    response.delete_cookie(auth.csrf_cookie_name, path="/", domain=auth.cookie_domain)


def _session_payload(user: User, response: Response) -> dict[str, Any]:
    """Mint a session and shape the response the frontend expects."""
    access_token, expires_in = tokens.create_access_token(
        user_id=user.id, email=user.email, is_verified=user.is_verified
    )
    refresh_token, refresh_ttl = tokens.issue_refresh_token(user.id)
    csrf_token = _set_session_cookies(response, refresh_token, refresh_ttl)
    return {
        "access_token": access_token,
        "token_type": "bearer",
        "expires_in": expires_in,
        "csrf_token": csrf_token,
        "user": user.to_dict(),
    }


def _send_verification(user: User) -> None:
    """Issue a verification token and send it. Never raises into the request.

    A registration that succeeded is not undone because a mail provider had a bad minute:
    the account exists, and the person can ask for another link. The failure is logged at
    error level so that a broken provider key is visible in the logs rather than only in
    the support queue.
    """
    try:
        token, _ = tokens.issue_email_token("verify_email", user.id)
        email_sender.send(email_templates.verification_email(user.email, token))
    except Exception:  # noqa: BLE001
        logger.exception("Could not send the verification email for account %s", user.id)


# --------------------------------------------------------------------------------------
# Registration and sign-in
# --------------------------------------------------------------------------------------

# Byte-for-byte identical whether or not the address already has an account. Built once,
# at module level, so that no future edit can accidentally make one branch differ from the
# other — the whole property depends on there being exactly one of these.
_REGISTRATION_RESPONSE: dict[str, Any] = {
    "registered": True,
    "message": (
        "Check your email for a confirmation link. If that address already has an "
        "account, sign in instead."
    ),
}


@router.post("/register")
def register(
    request: Request, body: RegisterRequest, session: Session = Depends(get_session)
) -> dict[str, Any]:
    """Create an account and send a confirmation link.

    Returns no session, and that is the interesting decision. Signing the caller in here
    would be better for the person registering and would also make this endpoint an
    account-enumeration oracle: a response carrying an access token means "that address
    was free", and one without means "that address is taken". No amount of careful wording
    hides a structural difference like that.

    So the response is identical in both cases, and the frontend immediately calls
    ``/api/auth/login`` with the same credentials. A genuinely new account signs straight
    in — the user sees no extra step, only one more round trip. An existing account with
    the wrong password gets login's generic refusal, which reveals nothing either. An
    existing account with the *right* password signs in, which is correct: that is the
    account's owner, and they would have got there by signing in anyway.
    """
    auth = get_settings().auth
    _limit(request, "register", limit=auth.register_attempts, window_s=auth.register_window_s)

    outcome = service.register(session, body.email, body.password)

    if outcome.user is not None:
        # Both branches send at most one message, to the address's real owner, subject to
        # the same per-address cooldown. Without the cooldown this endpoint would be a way
        # to send somebody a confirmation email every few seconds.
        needs_confirmation = outcome.created or not outcome.user.is_verified
        if needs_confirmation and not rate_limit.cooldown(
            "verify-send", f"email:{outcome.user.email}", seconds=auth.resend_window_s
        ):
            _send_verification(outcome.user)

    if outcome.created:
        logger.info("Registered account %s", outcome.user.id if outcome.user else "?")
        metrics.count_auth_event("register")
    else:
        logger.info("Register attempt on an address that already has an account")

    return dict(_REGISTRATION_RESPONSE)


@router.post("/login")
def login(
    request: Request,
    body: LoginRequest,
    response: Response,
    session: Session = Depends(get_session),
) -> dict[str, Any]:
    auth = get_settings().auth
    # Limited by client *and* by the address being attempted. The first stops one host
    # working through many accounts; the second stops a botnet working on one account.
    email_identity = f"email:{service.normalise_email(body.email)}"
    _limit(request, "login", limit=auth.login_attempts, window_s=auth.login_window_s)
    _limit(
        request,
        "login-account",
        limit=auth.login_attempts,
        window_s=auth.login_window_s,
        identity=email_identity,
    )

    user = service.authenticate(session, body.email, body.password)

    # Proving the password clears the guessing budget: see rate_limit.reset.
    rate_limit.reset("login", rate_limit_identity(request), window_s=auth.login_window_s)
    rate_limit.reset("login-account", email_identity, window_s=auth.login_window_s)

    metrics.count_auth_event("login_success")
    return _session_payload(user, response)


@router.post("/refresh")
def refresh(
    request: Request, response: Response, session: Session = Depends(get_session)
) -> dict[str, Any]:
    """Exchange the refresh cookie for a new access token, rotating the refresh token.

    Authenticated by cookie, so CSRF-protected. Rotation means a token is good exactly
    once; presenting a rotated-away one is treated as theft and ends every session for the
    account.
    """
    auth = get_settings().auth
    csrf.validate(request)

    token = request.cookies.get(auth.refresh_cookie_name)
    if not token:
        raise _fail(
            "no_session",
            "You are not signed in.",
            status=401,
            remedy="Sign in and try again.",
        )

    try:
        user_id, new_token, ttl = tokens.rotate_refresh_token(token)
    except tokens.TokenError as exc:
        metrics.count_auth_event(
            "refresh_reuse" if exc.code == "token_revoked" else "refresh_failure"
        )
        _clear_session_cookies(response)
        raise _fail(exc.code, exc.message, status=401, remedy="Sign in again.") from exc

    user = service.get_user(session, user_id)
    if user is None or not user.is_active:
        tokens.revoke_refresh_token(new_token)
        _clear_session_cookies(response)
        raise _fail("account_missing", "That account is no longer available.", status=401)

    access_token, expires_in = tokens.create_access_token(
        user_id=user.id, email=user.email, is_verified=user.is_verified
    )
    csrf_token = _set_session_cookies(response, new_token, ttl)
    return {
        "access_token": access_token,
        "token_type": "bearer",
        "expires_in": expires_in,
        "csrf_token": csrf_token,
        "user": user.to_dict(),
    }


@router.post("/logout")
def logout(request: Request, response: Response) -> dict[str, Any]:
    """End this device's session.

    Only this one. Somebody signing out on a library computer should not be signing out
    their phone as well — that is what the password-change path is for.
    """
    csrf.validate(request)
    token = request.cookies.get(get_settings().auth.refresh_cookie_name)
    if token:
        tokens.revoke_refresh_token(token)
    _clear_session_cookies(response)
    return {"signed_out": True}


@router.post("/logout-all")
def logout_everywhere(
    request: Request, response: Response, user: User = Depends(current_user)
) -> dict[str, Any]:
    """End every session for this account, on every device."""
    revoked = tokens.revoke_all_refresh_tokens(user.id)
    _clear_session_cookies(response)
    return {"signed_out": True, "sessions_ended": revoked}


@router.get("/me")
def me(user: User = Depends(current_user)) -> dict[str, Any]:
    return {
        "user": user.to_dict(),
        "oauth_accounts": [account.to_dict() for account in user.oauth_accounts],
        "authentication_methods": service.authentication_method_count(user),
        "estimate_count": estimate_store.count_for_owner(user.id),
    }


@router.patch("/me")
def update_me(
    body: UpdateProfileRequest,
    user: User = Depends(current_user),
    session: Session = Depends(get_session),
) -> dict[str, Any]:
    if body.display_name is not None:
        user.display_name = body.display_name.strip() or None
    session.flush()
    return {"user": user.to_dict()}


# --------------------------------------------------------------------------------------
# Email verification
# --------------------------------------------------------------------------------------

@router.post("/verify-email")
def verify_email(
    body: VerifyEmailRequest, session: Session = Depends(get_session)
) -> dict[str, Any]:
    """Confirm an address.

    An expired link returns ``token_expired`` specifically, not a generic 400. That
    distinction is the difference between the interface offering a "send me a new one"
    button and telling the user something unhelpful about an invalid request.
    """
    try:
        user_id = tokens.consume_email_token("verify_email", body.token)
    except tokens.TokenError as exc:
        raise _fail(
            exc.code,
            exc.message,
            status=400,
            remedy=(
                "Request a new confirmation link — it takes a moment."
                if exc.code == "token_expired"
                else "Sign in and request a new confirmation link."
            ),
        ) from exc

    user = service.get_user(session, user_id)
    if user is None:
        raise _fail("account_missing", "That account no longer exists.", status=404)

    if user.is_verified:
        return {"verified": True, "already_verified": True, "user": user.to_dict()}

    service.mark_verified(session, user)
    logger.info("Verified email for account %s", user.id)
    return {"verified": True, "already_verified": False, "user": user.to_dict()}


@router.post("/resend-verification")
def resend_verification(
    request: Request,
    body: ResendVerificationRequest,
    session: Session = Depends(get_session),
) -> dict[str, Any]:
    """Send another confirmation link.

    Throttled hard, per account and per client. This endpoint causes email to be sent to
    an address chosen by the caller, which makes it a mailbox-flooding tool if it is not.
    """
    auth = get_settings().auth
    normalised = service.normalise_email(body.email)
    _limit(request, "resend-client", limit=6, window_s=auth.resend_window_s * 10)

    generic = {
        "sent": True,
        "message": (
            "If that address has an unconfirmed account, a new link is on its way. "
            "Check your spam folder if it does not arrive."
        ),
    }

    wait = rate_limit.cooldown("resend", f"email:{normalised}", seconds=auth.resend_window_s)
    if wait:
        raise HTTPException(
            status_code=429,
            detail={
                "error": "rate_limited",
                "message": "A confirmation link was sent very recently.",
                "remedy": f"Wait {wait} seconds before asking for another.",
            },
            headers={"Retry-After": str(wait)},
        )

    user = service.get_user_by_email(session, normalised)
    if user is not None and not user.is_verified:
        _send_verification(user)
    return generic


# --------------------------------------------------------------------------------------
# Password reset
# --------------------------------------------------------------------------------------

@router.post("/forgot-password")
def forgot_password(
    request: Request,
    body: ForgotPasswordRequest,
    session: Session = Depends(get_session),
) -> dict[str, Any]:
    normalised = service.normalise_email(body.email)
    _limit(request, "forgot-client", limit=6, window_s=3600)

    generic = {
        "sent": True,
        "message": (
            "If that address has an account, a reset link is on its way. It expires in "
            f"{get_settings().auth.password_reset_ttl_hours} hour(s)."
        ),
    }

    wait = rate_limit.cooldown("forgot", f"email:{normalised}", seconds=120)
    if wait:
        # Still a generic answer: telling the caller they are being throttled for *this
        # address* would confirm the address exists.
        return generic

    user = service.get_user_by_email(session, normalised)
    if user is not None and user.is_active:
        try:
            token, _ = tokens.issue_email_token("password_reset", user.id)
            email_sender.send(email_templates.password_reset_email(user.email, token))
        except Exception:  # noqa: BLE001
            logger.exception("Could not send a password reset email for account %s", user.id)
    return generic


@router.post("/reset-password")
def reset_password(
    body: ResetPasswordRequest,
    response: Response,
    session: Session = Depends(get_session),
) -> dict[str, Any]:
    """Set a new password from a reset link, and end every existing session.

    The revocation is the security-critical half. A reset is what somebody does when they
    believe an attacker has their account; leaving the attacker's thirty-day refresh token
    working would make the whole exercise theatre.
    """
    try:
        user_id = tokens.consume_email_token("password_reset", body.token)
    except tokens.TokenError as exc:
        raise _fail(
            exc.code,
            exc.message,
            status=400,
            remedy=(
                "Request a new reset link."
                if exc.code == "token_expired"
                else "Request a new reset link from the sign-in page."
            ),
        ) from exc

    user = service.get_user(session, user_id)
    if user is None:
        raise _fail("account_missing", "That account no longer exists.", status=404)

    service.set_password(session, user, body.password, revoke_sessions=True)
    metrics.count_auth_event("password_reset")
    # Any other reset link in the same inbox is now dead too.
    tokens.revoke_email_tokens_for_user("password_reset", user.id)

    # Completing a reset proves control of the mailbox, which is what verification asks.
    if not user.is_verified:
        service.mark_verified(session, user)

    _clear_session_cookies(response)
    return {
        "reset": True,
        "message": (
            "Your password has been changed and every device has been signed out. "
            "Sign in with your new password."
        ),
    }


@router.post("/change-password")
def change_password(
    body: ChangePasswordRequest,
    response: Response,
    request: Request,
    user: User = Depends(current_user),
    session: Session = Depends(get_session),
) -> dict[str, Any]:
    """Change a password from account settings, ending other sessions.

    The current password is required when there is one. Somebody who signed up through
    Google is setting a first password rather than changing one, and their valid session
    is the proof in that case.
    """
    if user.has_password:
        if not body.current_password:
            raise _fail(
                "current_password_required",
                "Enter your current password.",
                status=422,
            )
        if not passwords.verify_password(body.current_password, user.hashed_password):
            _limit(request, "change-password", limit=8, window_s=900)
            raise _fail(
                "invalid_credentials", "That is not your current password.", status=403
            )

    service.set_password(session, user, body.new_password, revoke_sessions=True)

    # The person doing this is right here, so re-issue their session rather than making
    # them sign in again on the device they are already using.
    payload = _session_payload(user, response)
    payload["changed"] = True
    payload["message"] = "Password updated. Other devices have been signed out."
    return payload


# --------------------------------------------------------------------------------------
# Estimate claiming
# --------------------------------------------------------------------------------------

@router.post("/claim-estimate")
def claim_estimate(
    body: ClaimEstimateRequest, user: User = Depends(current_user)
) -> dict[str, Any]:
    """Attach an estimate that was produced anonymously to this account.

    The natural path through the product: run an estimate, like it, then sign in. Only
    unowned estimates can be claimed, so holding a link to somebody else's saved estimate
    does not let you take it.
    """
    record = estimate_store.claim(body.estimate_id, user.id)
    if record is None:
        existing = estimate_store.owner_of(body.estimate_id)
        if existing == str(user.id):
            return {"claimed": True, "already_owned": True, "estimate_id": body.estimate_id}
        raise _fail(
            "cannot_claim",
            (
                "That estimate could not be added to your account. It may have been "
                "deleted, or it may already belong to someone else."
            ),
            status=404,
        )
    return {"claimed": True, "already_owned": False, "estimate_id": record.estimate_id}


# --------------------------------------------------------------------------------------
# OAuth
# --------------------------------------------------------------------------------------

@router.get("/providers")
def providers() -> dict[str, Any]:
    """Which sign-in providers this deployment offers.

    Asked by the frontend so it does not render a button that leads to a 503.
    """
    return {"providers": oauth_flow.available_providers()}


def _oauth_failure(flow_redirect: str, code: str, message: str) -> RedirectResponse:
    """Send the browser back to the frontend with the failure attached.

    A callback cannot usefully render JSON: the user is in a browser, mid-navigation, and
    what they need is the sign-in page saying what went wrong.
    """
    separator = "&" if "?" in flow_redirect else "?"
    query = urlencode({"auth_error": code, "auth_message": message})
    return RedirectResponse(f"{flow_redirect}{separator}{query}", status_code=303)


@router.get("/oauth/{provider}/authorize")
def oauth_authorize(
    provider: str,
    request: Request,
    redirect_to: str | None = Query(default=None, max_length=2048),
    user: User | None = Depends(optional_user),
) -> RedirectResponse:
    """Begin a sign-in flow.

    A signed-in caller begins a *link* flow instead, which attaches the provider identity
    to the account they are already using. That is the only way an account gains a second
    provider — there is deliberately no path where matching email addresses cause a merge.
    """
    _limit(request, "oauth-start", limit=20, window_s=300)
    try:
        url = oauth_flow.begin(
            provider,
            redirect_to=redirect_to,
            intent="link" if user else "login",
            user_id=str(user.id) if user else None,
        )
    except oauth_flow.OAuthError as exc:
        raise _fail(exc.code, exc.message, status=exc.status) from exc
    return RedirectResponse(url, status_code=307)


@router.get("/oauth/{provider}/callback")
def oauth_callback(
    provider: str,
    request: Request,
    code: str | None = Query(default=None, max_length=2048),
    state: str | None = Query(default=None, max_length=256),
    error: str | None = Query(default=None, max_length=256),
    session: Session = Depends(get_session),
) -> Response:
    """Finish a sign-in flow.

    This request has almost certainly landed on a different replica than the one that
    started it, which is why every piece of flow state came from Redis rather than from
    this process's memory.
    """
    frontend = get_settings().oauth.frontend_base

    if error:
        # The person pressed "cancel" on the provider's consent screen, most often.
        return _oauth_failure(
            frontend, "oauth_declined", f"{provider.title()} sign-in was not completed."
        )
    if not code or not state:
        return _oauth_failure(
            frontend, "oauth_invalid", "That sign-in link was incomplete. Start again."
        )

    try:
        flow, profile = oauth_flow.complete(state, code)
    except oauth_flow.OAuthError as exc:
        return _oauth_failure(frontend, exc.code, exc.message)

    if flow.provider != provider:
        return _oauth_failure(frontend, "oauth_invalid", "That sign-in link was not valid.")

    destination = flow.redirect_to

    if flow.intent == "link":
        owner = service.get_user(session, flow.user_id or "")
        if owner is None:
            return _oauth_failure(
                destination, "not_authenticated", "Sign in again before connecting an account."
            )
        try:
            service.link_provider(
                session,
                owner,
                provider=provider,
                provider_account_id=profile.account_id,
                email=profile.email,
                username=profile.username,
            )
        except service.AuthError as exc:
            return _oauth_failure(destination, exc.code, exc.message)
        separator = "&" if "?" in destination else "?"
        return RedirectResponse(f"{destination}{separator}linked={provider}", status_code=303)

    try:
        user, created = service.sign_in_with_provider(
            session,
            provider=provider,
            provider_account_id=profile.account_id,
            email=profile.email,
            display_name=profile.display_name,
            username=profile.username,
        )
    except service.AuthError as exc:
        return _oauth_failure(destination, exc.code, exc.message)

    # A redirect cannot carry a body, so the access token is handed over through a
    # one-time code the frontend immediately exchanges. Putting the token itself in the
    # URL would write it into browser history, the Referer header and any proxy log on the
    # way.
    handoff = _issue_handoff(user)
    response = RedirectResponse(
        f"{destination}{'&' if '?' in destination else '?'}auth_code={handoff}"
        f"{'&created=1' if created else ''}",
        status_code=303,
    )
    refresh_token, ttl = tokens.issue_refresh_token(user.id)
    _set_session_cookies(response, refresh_token, ttl)
    return response


def _issue_handoff(user: User) -> str:
    """A single-use code the frontend swaps for an access token.

    Ten seconds, one use, stored in Redis so the exchange can land on any replica.
    """
    code = secrets.token_urlsafe(32)
    redis_client.get_client().set(
        redis_client.key("oauth-handoff", code),
        json.dumps({"user_id": str(user.id)}),
        ex=10,
        nx=True,
    )
    return code


@router.post("/oauth/exchange")
def oauth_exchange(
    request: Request,
    body: OAuthExchangeRequest,
    response: Response,
    session: Session = Depends(get_session),
) -> dict[str, Any]:
    """Swap a one-time handoff code for an access token.

    Completes the OAuth round trip: the callback redirected with a code, the frontend
    posts it here, and gets back the same session payload a password login produces.
    """
    _limit(request, "oauth-exchange", limit=20, window_s=300)

    key = redis_client.key("oauth-handoff", body.code)
    client = redis_client.get_client()
    raw = client.get(key)
    if raw is None:
        raise _fail(
            "invalid_code",
            "That sign-in link has expired. Start again.",
            status=400,
            remedy="Return to the sign-in page and try again.",
        )
    client.delete(key)

    try:
        user_id = json.loads(raw)["user_id"]
    except (json.JSONDecodeError, KeyError) as exc:
        raise _fail("invalid_code", "That sign-in could not be completed.", status=400) from exc

    user = service.get_user(session, user_id)
    if user is None or not user.is_active:
        raise _fail("account_missing", "That account is no longer available.", status=401)

    return _session_payload(user, response)


@router.get("/oauth/{provider}/link")
def oauth_link(
    provider: str,
    request: Request,
    redirect_to: str | None = Query(default=None, max_length=2048),
    user: User = Depends(current_user),
) -> RedirectResponse:
    """Begin a flow that attaches a provider to the account making the request."""
    _limit(request, "oauth-start", limit=20, window_s=300)
    try:
        url = oauth_flow.begin(
            provider, redirect_to=redirect_to, intent="link", user_id=str(user.id)
        )
    except oauth_flow.OAuthError as exc:
        raise _fail(exc.code, exc.message, status=exc.status) from exc
    return RedirectResponse(url, status_code=307)


@router.delete("/oauth/{provider}")
def oauth_unlink(
    provider: str,
    user: User = Depends(current_user),
    session: Session = Depends(get_session),
) -> dict[str, Any]:
    """Disconnect a provider, unless it is the only way into the account."""
    try:
        service.unlink_provider(session, user, provider)
    except service.AuthError as exc:
        raise _fail(
            exc.code,
            exc.message,
            status=exc.status,
            remedy=(
                "Set a password first, then disconnect."
                if exc.code == "last_auth_method"
                else None
            ),
        ) from exc
    return {"unlinked": provider, "user": user.to_dict()}
