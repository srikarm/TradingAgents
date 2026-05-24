"""Wave 5.4 — channel adapter seam.

A notification is delivered through a `ChannelAdapter`. v1 ships an email
adapter (Resend) plus a logging stub. The stub is returned whenever the email
channel is selected but no provider key is configured, so the whole
notification spine runs end-to-end without external provisioning — only the
real send is gated on RESEND_API_KEY + verified-domain DNS.

Adding a future channel (web-push, SMS, Telegram) means adding an adapter +
a branch in `get_adapter`; nothing in the service layer changes.
"""

from __future__ import annotations

import logging
from typing import Protocol

logger = logging.getLogger(__name__)

RESEND_ENDPOINT = "https://api.resend.com/emails"


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


class ResendAdapter:
    """Sends via the Resend transactional-email HTTP API."""

    name = "email"

    def __init__(self, api_key: str, from_email: str) -> None:
        self._api_key = api_key
        self._from = from_email

    async def send(self, *, to: str, subject: str, text: str) -> None:
        import httpx

        if not to:
            # The deliver path passes user.email; a blank address means the
            # account lost its email after enabling. Fail loudly so it lands as
            # a FAILED notification row with a clear reason, not a Resend 422.
            raise ValueError("ResendAdapter: empty recipient address")

        async with httpx.AsyncClient(timeout=10.0) as client:
            res = await client.post(
                RESEND_ENDPOINT,
                headers={"Authorization": f"Bearer {self._api_key}"},
                json={
                    "from": self._from,
                    "to": [to],
                    "subject": subject,
                    "text": text,
                },
            )
            if res.status_code >= 400:
                # Surface the provider's body — raise_for_status alone hides WHY
                # (unverified domain, invalid sender, rate limit). The caller
                # records this string on the failed notification row.
                raise RuntimeError(
                    f"Resend send failed: {res.status_code} {res.text[:300]}"
                )


def get_adapter(channel: str, settings) -> ChannelAdapter | None:
    """Resolve the adapter for a channel, or None if the channel can't deliver.

    email + key  → ResendAdapter (real send)
    email, no key → StubAdapter   (spine works without provisioning)
    webpush/none → None           (no live delivery in v1)
    """
    if channel == "email":
        if settings.resend_api_key:
            return ResendAdapter(settings.resend_api_key, settings.notify_from_email)
        return StubAdapter()
    return None
