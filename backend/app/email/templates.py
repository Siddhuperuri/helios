"""The two messages the platform sends.

Written the way the rest of the product is written: plain language, one thing being asked
for, and an honest statement of what happens if the reader ignores it. Somebody who did not
request a password reset should be able to read that email, understand that nothing has
changed, and close it.

Both are sent as text with an HTML alternative. The HTML is deliberately spare — inline
styles, no images, no tracking pixel, no web fonts. A verification email is a link and a
sentence; anything more is a deliverability risk and a privacy cost for no benefit.
"""

from __future__ import annotations

import html
from urllib.parse import quote

from app.config import get_settings
from app.email.sender import EmailMessage


def _link(path: str, token: str) -> str:
    base = get_settings().email.link_base
    return f"{base}{path}?token={quote(token, safe='')}"


def _wrap(heading: str, body_paragraphs: list[str], button_label: str, url: str) -> str:
    paragraphs = "".join(
        f'<p style="margin:0 0 16px;line-height:1.6;color:#4a5058;">{html.escape(p)}</p>'
        for p in body_paragraphs
    )
    safe_url = html.escape(url, quote=True)
    return (
        '<div style="font-family:-apple-system,BlinkMacSystemFont,Segoe UI,Helvetica,'
        'Arial,sans-serif;max-width:520px;margin:0 auto;padding:32px 24px;color:#181a1d;">'
        '<p style="margin:0 0 28px;font-family:ui-monospace,SFMono-Regular,Menlo,monospace;'
        'font-size:13px;letter-spacing:0.08em;color:#a66a0c;">HELIOS</p>'
        f'<h1 style="margin:0 0 20px;font-size:20px;font-weight:500;">{html.escape(heading)}</h1>'
        f"{paragraphs}"
        f'<p style="margin:28px 0;"><a href="{safe_url}" '
        'style="display:inline-block;background:#a66a0c;color:#ffffff;text-decoration:none;'
        f'padding:12px 22px;font-size:14px;">{html.escape(button_label)}</a></p>'
        '<p style="margin:0 0 8px;font-size:13px;line-height:1.6;color:#636a73;">'
        "If the button does not work, copy this address into your browser:</p>"
        f'<p style="margin:0;font-size:12px;word-break:break-all;color:#636a73;">{safe_url}</p>'
        "</div>"
    )


def verification_email(to: str, token: str) -> EmailMessage:
    hours = get_settings().auth.verification_ttl_hours
    url = _link("/verify-email", token)
    body = [
        "Confirm this address and your Helios account is fully set up.",
        (
            f"The link is good for {hours} hours. You can keep using the calculator and "
            "saving estimates in the meantime — confirming just makes sure we can reach "
            "you about them."
        ),
        "If you did not create a Helios account, you can ignore this message.",
    ]
    text = (
        "Confirm your email address\n\n"
        + "\n\n".join(body)
        + f"\n\nConfirm your address:\n{url}\n"
    )
    return EmailMessage(
        to=to,
        subject="Confirm your Helios email address",
        text=text,
        html=_wrap("Confirm your email address", body, "Confirm my address", url),
    )


def password_reset_email(to: str, token: str) -> EmailMessage:
    hours = get_settings().auth.password_reset_ttl_hours
    url = _link("/reset-password", token)
    plural = "hour" if hours == 1 else "hours"
    body = [
        "Use the link below to choose a new password for your Helios account.",
        (
            f"It works once and expires in {hours} {plural}. Setting a new password signs "
            "you out everywhere else, on every device."
        ),
        (
            "If you did not ask for this, nothing has happened and you do not need to do "
            "anything. Your current password still works."
        ),
    ]
    text = (
        "Reset your password\n\n" + "\n\n".join(body) + f"\n\nChoose a new password:\n{url}\n"
    )
    return EmailMessage(
        to=to,
        subject="Reset your Helios password",
        text=text,
        html=_wrap("Reset your password", body, "Choose a new password", url),
    )
