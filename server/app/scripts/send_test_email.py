"""Send a one-off test signal-alert email to verify SendGrid provisioning (ISC-33).

Usage:
    uv run python -m app.scripts.send_test_email you@example.com

Uses the configured channel adapter: SendGridAdapter when SENDGRID_API_KEY is
set (a real send — the live-delivery probe), else the logging StubAdapter
(prints instead of sending). This lets an operator confirm the email path the
moment the key + SendGrid domain authentication are in place, without waiting
for a real monitor batch.

Exit 0 on success, non-zero on failure (e.g. unverified domain surfaces the
provider's error).
"""

from __future__ import annotations

import asyncio
import sys

from app.config import get_settings
from app.services.notification_channels import get_adapter


async def _send(to: str) -> int:
    settings = get_settings()
    adapter = get_adapter("email", settings)
    if adapter is None:
        print("no email adapter available (channel disabled)")
        return 1
    link = f"{settings.public_base_url.rstrip('/')}/signals"
    subject = "TradingAgents — test signal alert"
    text = (
        "This is a test of your TradingAgents signal alerts.\n"
        "If you received this, email delivery is working.\n\n"
        f"View your signals: {link}"
    )
    await adapter.send(to=to, subject=subject, text=text)
    print(f"sent via {adapter.name!r} to {to}")
    return 0


def main() -> int:
    if len(sys.argv) != 2:
        print("usage: python -m app.scripts.send_test_email <email>")
        return 2
    return asyncio.run(_send(sys.argv[1]))


if __name__ == "__main__":
    raise SystemExit(main())
