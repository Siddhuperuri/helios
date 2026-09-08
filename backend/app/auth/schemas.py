"""Request and response bodies for the account endpoints.

``extra="forbid"`` throughout, matching the rest of the API: a field the server does not
recognise is a mistake worth reporting, not something to ignore. It is worth more here
than elsewhere — a typo in a security-relevant field that is silently discarded is how a
protection ends up not applied.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class _Body(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class RegisterRequest(_Body):
    email: str = Field(max_length=320)
    # Not validated for length here. The policy lives in one place — `passwords.password_problem`
    # — so that the message a user sees is the message the policy actually enforces.
    password: str = Field(max_length=512)


class LoginRequest(_Body):
    email: str = Field(max_length=320)
    password: str = Field(max_length=512)


class VerifyEmailRequest(_Body):
    token: str = Field(min_length=8, max_length=512)


class ResendVerificationRequest(_Body):
    email: str = Field(max_length=320)


class ForgotPasswordRequest(_Body):
    email: str = Field(max_length=320)


class ResetPasswordRequest(_Body):
    token: str = Field(min_length=8, max_length=512)
    password: str = Field(max_length=512)


class ChangePasswordRequest(_Body):
    # Optional because an account created through Google has no current password to give.
    # Setting a first password still requires a valid session, which is the proof in that
    # case.
    current_password: str | None = Field(default=None, max_length=512)
    new_password: str = Field(max_length=512)


class UpdateProfileRequest(_Body):
    display_name: str | None = Field(default=None, max_length=120)


class ClaimEstimateRequest(_Body):
    estimate_id: str = Field(min_length=8, max_length=64)


class OAuthExchangeRequest(_Body):
    """The one-time code the OAuth callback hands to the frontend.

    In a body rather than a query string on purpose: query strings end up in browser
    history, in the Referer header of the next request, and in every access log between
    here and the client. A single-use ten-second code is not a catastrophe in any of those
    places, but there is no reason to put it there.
    """

    code: str = Field(min_length=8, max_length=256)
