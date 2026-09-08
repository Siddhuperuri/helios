"""Provider-agnostic transactional email.

The rule this module exists to enforce: no call site names a vendor. A route asks for
"send this person their verification link" and a provider selected by ``EMAIL_PROVIDER``
carries it. Swapping SES for Postmark is a configuration change and a deployment, not a
code change.

Providers
---------
``ses`` / ``sendgrid`` / ``postmark`` / ``resend``
    Real delivery over each vendor's HTTPS API. All four are a single POST with a JSON or
    form body, which is why none of them needs a vendor SDK — an SDK per provider would be
    four dependencies and four release cadences to carry for one HTTP request each.

``console``
    Prints the message. The development default, so a developer can complete a signup
    without configuring anything.

``memory``
    Captures messages in a list for tests to assert against.

No local mail server, ever. Running one inside the backend container would make the
backend stateful (a spool directory), unreliable (nobody accepts mail from an unknown
container's IP), and a deliverability problem nobody wants to own.

Failure policy
--------------
:func:`send` raises on failure and the caller decides. Registration, for instance, does not
fail because the mail did not go out: the account exists and the person can ask for another
link. Silently swallowing the failure would be worse — it would mean nobody ever finds out
the mail provider's key expired.
"""

from __future__ import annotations

import json
import logging
import sys
import types
import urllib.error
import urllib.request
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any

from app.config import EmailSettings, get_settings

logger = logging.getLogger(__name__)


class EmailSendError(RuntimeError):
    """Delivery failed. Carries a message safe to log, never the credential."""


@dataclass
class EmailMessage:
    to: str
    subject: str
    text: str
    html: str | None = None
    headers: dict[str, str] = field(default_factory=dict)

    def redacted(self) -> dict[str, Any]:
        """A form of this message that is safe to log: recipient and subject only."""
        return {"to": self.to, "subject": self.subject, "chars": len(self.text)}


class EmailSender(ABC):
    name = "abstract"

    def __init__(self, settings: EmailSettings) -> None:
        self.settings = settings

    @abstractmethod
    def send(self, message: EmailMessage) -> None: ...

    def health(self) -> tuple[bool, str | None]:
        """Whether this provider looks usable.

        Deliberately a configuration check rather than a live send. A readiness probe that
        delivered a message every few seconds would be both expensive and a fine way to
        get an account suspended.
        """
        return True, None

    @property
    def from_header(self) -> str:
        name = self.settings.from_name
        address = self.settings.from_address
        return f"{name} <{address}>" if name else address


# --------------------------------------------------------------------------------------
# Development and test providers
# --------------------------------------------------------------------------------------

class ConsoleSender(EmailSender):
    """Prints the message. Delivers nothing."""

    name = "console"

    def send(self, message: EmailMessage) -> None:
        logger.info(
            "\n"
            "──────────── email (not delivered: EMAIL_PROVIDER=console) ────────────\n"
            "To:      %s\n"
            "From:    %s\n"
            "Subject: %s\n"
            "\n%s\n"
            "───────────────────────────────────────────────────────────────────────",
            message.to,
            self.from_header,
            message.subject,
            message.text,
        )

    def health(self) -> tuple[bool, str | None]:
        return True, "console provider does not deliver mail"


# The captured outbox is anchored outside this package, for the same reason the Redis
# stand-in is: a test that builds a second application instance drops every ``app.*``
# module and re-imports, which would give that instance a second, separate outbox. A test
# asserting on mail sent by "the other replica" would then always see zero messages —
# failing for a reason that has nothing to do with the behaviour under test.
_OUTBOX_MODULE = "_helios_shared_outbox"


def outbox() -> list[EmailMessage]:
    """Messages the ``memory`` provider captured. Shared across instances in one process."""
    module = sys.modules.get(_OUTBOX_MODULE)
    if module is None:
        module = types.ModuleType(_OUTBOX_MODULE)
        module.messages = []  # type: ignore[attr-defined]
        sys.modules[_OUTBOX_MODULE] = module
    return module.messages  # type: ignore[attr-defined,no-any-return]


class MemorySender(EmailSender):
    """Captures messages so a test can assert on the link it would have sent."""

    name = "memory"

    def send(self, message: EmailMessage) -> None:
        outbox().append(message)

    @classmethod
    def clear(cls) -> None:
        outbox().clear()

    def health(self) -> tuple[bool, str | None]:
        return True, "memory provider does not deliver mail"


# --------------------------------------------------------------------------------------
# Real providers
# --------------------------------------------------------------------------------------

class _HttpSender(EmailSender):
    """Shared plumbing for the vendors, all of which are one authenticated POST."""

    endpoint = ""

    def _post(
        self,
        url: str,
        body: bytes,
        headers: dict[str, str],
        *,
        expected: tuple[int, ...] = (200, 201, 202),
    ) -> None:
        request = urllib.request.Request(url, data=body, headers=headers, method="POST")
        try:
            with urllib.request.urlopen(request, timeout=self.settings.timeout_s) as response:
                if response.status not in expected:
                    raise EmailSendError(
                        f"{self.name} returned HTTP {response.status}"
                    )
        except urllib.error.HTTPError as exc:
            detail = ""
            try:
                # Vendor error bodies name the problem (bad key, unverified sender). They
                # do not contain the key itself, so this is safe to surface in a log.
                detail = exc.read().decode("utf-8", errors="replace")[:300]
            except Exception:  # noqa: BLE001
                pass
            raise EmailSendError(f"{self.name} rejected the message: {exc.code} {detail}") from exc
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            raise EmailSendError(f"{self.name} was unreachable: {exc}") from exc

    def health(self) -> tuple[bool, str | None]:
        if not self.settings.api_key:
            return False, f"{self.name} is selected but EMAIL_PROVIDER_API_KEY is unset"
        if not self.settings.from_address:
            return False, f"{self.name} is selected but EMAIL_FROM_ADDRESS is unset"
        return True, None


class SendGridSender(_HttpSender):
    name = "sendgrid"

    def send(self, message: EmailMessage) -> None:
        payload: dict[str, Any] = {
            "personalizations": [{"to": [{"email": message.to}]}],
            "from": {"email": self.settings.from_address, "name": self.settings.from_name},
            "subject": message.subject,
            "content": [{"type": "text/plain", "value": message.text}],
        }
        if message.html:
            payload["content"].append({"type": "text/html", "value": message.html})
        self._post(
            "https://api.sendgrid.com/v3/mail/send",
            json.dumps(payload).encode("utf-8"),
            {
                "Authorization": f"Bearer {self.settings.api_key}",
                "Content-Type": "application/json",
            },
        )


class PostmarkSender(_HttpSender):
    name = "postmark"

    def send(self, message: EmailMessage) -> None:
        payload = {
            "From": self.from_header,
            "To": message.to,
            "Subject": message.subject,
            "TextBody": message.text,
            "MessageStream": "outbound",
        }
        if message.html:
            payload["HtmlBody"] = message.html
        self._post(
            "https://api.postmarkapp.com/email",
            json.dumps(payload).encode("utf-8"),
            {
                "X-Postmark-Server-Token": self.settings.api_key,
                "Content-Type": "application/json",
                "Accept": "application/json",
            },
        )


class ResendSender(_HttpSender):
    name = "resend"

    def send(self, message: EmailMessage) -> None:
        payload: dict[str, Any] = {
            "from": self.from_header,
            "to": [message.to],
            "subject": message.subject,
            "text": message.text,
        }
        if message.html:
            payload["html"] = message.html
        self._post(
            "https://api.resend.com/emails",
            json.dumps(payload).encode("utf-8"),
            {
                "Authorization": f"Bearer {self.settings.api_key}",
                "Content-Type": "application/json",
            },
        )


class SESSender(_HttpSender):
    """Amazon SES.

    SES v2 is reached through the SDK in most deployments because its request signing is
    SigV4 and reimplementing that here would be exactly the kind of hand-rolled
    cryptography this project avoids. So this provider requires ``boto3``, which is an
    optional dependency installed only where SES is actually used.
    """

    name = "ses"

    def send(self, message: EmailMessage) -> None:
        try:
            import boto3  # type: ignore[import-untyped]
        except ImportError as exc:  # pragma: no cover - optional dependency
            raise EmailSendError(
                "EMAIL_PROVIDER=ses requires boto3. Install it "
                "(`pip install boto3`) or choose another provider."
            ) from exc

        body: dict[str, Any] = {"Text": {"Data": message.text, "Charset": "UTF-8"}}
        if message.html:
            body["Html"] = {"Data": message.html, "Charset": "UTF-8"}

        try:
            client = boto3.client("sesv2", region_name=self.settings.region)
            client.send_email(
                FromEmailAddress=self.from_header,
                Destination={"ToAddresses": [message.to]},
                Content={
                    "Simple": {
                        "Subject": {"Data": message.subject, "Charset": "UTF-8"},
                        "Body": body,
                    }
                },
            )
        except Exception as exc:  # noqa: BLE001 - botocore raises a wide family
            raise EmailSendError(f"SES rejected the message: {exc}") from exc

    def health(self) -> tuple[bool, str | None]:
        # SES authenticates with the ambient AWS credential chain — an instance role, most
        # often — so an unset EMAIL_PROVIDER_API_KEY is normal and not a problem.
        if not self.settings.from_address:
            return False, "ses is selected but EMAIL_FROM_ADDRESS is unset"
        return True, None


_PROVIDERS: dict[str, type[EmailSender]] = {
    "console": ConsoleSender,
    "memory": MemorySender,
    "sendgrid": SendGridSender,
    "postmark": PostmarkSender,
    "resend": ResendSender,
    "ses": SESSender,
}

_sender: EmailSender | None = None


def get_sender() -> EmailSender:
    global _sender
    if _sender is None:
        settings = get_settings().email
        provider = _PROVIDERS.get(settings.provider)
        if provider is None:
            raise EmailSendError(
                f"Unknown EMAIL_PROVIDER '{settings.provider}'. Choose one of: "
                f"{', '.join(sorted(_PROVIDERS))}."
            )
        _sender = provider(settings)
        logger.info("Email provider: %s", _sender.name)
    return _sender


def reset_sender() -> None:
    """Drop the cached sender after a configuration change. Tests and scripts only."""
    global _sender
    _sender = None
    MemorySender.clear()


def send(message: EmailMessage) -> None:
    """Deliver a message, or raise :class:`EmailSendError`."""
    sender = get_sender()
    sender.send(message)
    logger.info("Sent %s email via %s", message.subject, sender.name)


def health() -> tuple[bool, str | None]:
    """Whether the configured provider is usable, for the readiness probe."""
    try:
        return get_sender().health()
    except EmailSendError as exc:
        return False, str(exc)
