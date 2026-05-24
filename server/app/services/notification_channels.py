"""Wave 5.4 — channel adapter seam.

A notification is delivered through a `ChannelAdapter`. v1 ships an email
adapter (SendGrid) plus a logging stub. The stub is returned whenever the email
channel is selected but no provider key is configured, so the whole
notification spine runs end-to-end without external provisioning — only the
real send is gated on SENDGRID_API_KEY + a SendGrid-authenticated sender domain.

Adding a future channel (web-push, SMS, Telegram) means adding an adapter +
a branch in `get_adapter`; nothing in the service layer changes.
"""

from __future__ import annotations

import logging
from typing import Protocol

logger = logging.getLogger(__name__)

SENDGRID_ENDPOINT = "https://api.sendgrid.com/v3/mail/send"


class ChannelAdapter(Protocol):
    name: str

    async def send(self, *, to: str, subject: str, text: str) -> None:
        ...


class StubAdapter:
    """Logs the notification instead of sending it. Used pre-provisioning and
    in tests — exercises the full claim→build→send→record path with no I/O."""

    name = "stub"

    async def send(self, *, to: str, subject: str, text: str) -> None:
        logger.info(
            "notification[stub] would send to=%s subject=%r body=%r",
            to, subject, text,
        )


class SendGridAdapter:
    """Sends via the SendGrid v3 mail-send HTTP API."""

    name = "email"

    def __init__(self, api_key: str, from_email: str) -> None:
        self._api_key = api_key
        self._from = from_email

    async def send(self, *, to: str, subject: str, text: str) -> None:
        import httpx

        if not to:
            # The deliver path passes user.email; a blank address means the
            # account lost its email after enabling. Fail loudly so it lands as
            # a FAILED notification row with a clear reason, not a SendGrid 4xx.
            raise ValueError("SendGridAdapter: empty recipient address")

        async with httpx.AsyncClient(timeout=10.0) as client:
            res = await client.post(
                SENDGRID_ENDPOINT,
                headers={"Authorization": f"Bearer {self._api_key}"},
                json={
                    "personalizations": [{"to": [{"email": to}]}],
                    "from": {"email": self._from},
                    "subject": subject,
                    "content": [{"type": "text/plain", "value": text}],
                },
            )
            # SendGrid returns 202 Accepted on success. Anything else (incl. an
            # unauthenticated sender domain, bad key, rate limit) is a failure —
            # surface the body so the reason lands on the FAILED notification row.
            if res.status_code != 202:
                raise RuntimeError(
                    f"SendGrid send failed: {res.status_code} {res.text[:300]}"
                )


def get_adapter(channel: str, settings) -> ChannelAdapter | None:
    """Resolve the adapter for a channel, or None if the channel can't deliver.

    email + key  → SendGridAdapter (real send)
    email, no key → StubAdapter    (spine works without provisioning)
    webpush/none → None            (no live delivery in v1)
    """
    if channel == "email":
        if settings.sendgrid_api_key:
            return SendGridAdapter(settings.sendgrid_api_key, settings.notify_from_email)
        return StubAdapter()
    return None
