"""Transactional email.

Two messages exist today — verify your address, reset your password — and both are on the
critical path of somebody getting into their account. What carries them is a vendor
decision that should never have to be made inside a route handler, so it is made once, by
name, from configuration.
"""

from app.email.sender import EmailMessage, EmailSendError, get_sender, send  # noqa: F401
