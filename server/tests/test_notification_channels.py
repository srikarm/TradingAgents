"""Wave 5.4 (F5) — channel adapter seam + SendGridAdapter wire format.

The live send is operator-gated (SENDGRID_API_KEY + authenticated sender
domain), so the real HTTP call can't be exercised here. These tests pin the
adapter's *behavior* with httpx mocked: correct endpoint/headers/payload,
empty-recipient guard, 202-is-success, and that a provider error surfaces a
debuggable message (which the deliver path records on the FAILED row).
"""
import types

import httpx
import pytest

from app.services.notification_channels import (
    SendGridAdapter,
    StubAdapter,
    get_adapter,
    SENDGRID_ENDPOINT,
)


def _settings(*, key, frm="signals@axiara.ai"):
    return types.SimpleNamespace(sendgrid_api_key=key, notify_from_email=frm)


# ---- get_adapter routing ----

def test_get_adapter_email_with_key_is_sendgrid():
    a = get_adapter("email", _settings(key="SG.live_123"))
    assert isinstance(a, SendGridAdapter)
    assert a.name == "email"


def test_get_adapter_email_without_key_falls_back_to_stub():
    a = get_adapter("email", _settings(key=None))
    assert isinstance(a, StubAdapter)


def test_get_adapter_webpush_and_none_are_unsupported():
    assert get_adapter("webpush", _settings(key="x")) is None
    assert get_adapter("none", _settings(key="x")) is None


# ---- StubAdapter ----

@pytest.mark.asyncio
async def test_stub_send_does_not_raise():
    await StubAdapter().send(to="a@example.com", subject="s", text="t")


# ---- SendGridAdapter wire format (httpx mocked) ----

class _FakeResp:
    def __init__(self, status_code=202, text=""):
        self.status_code = status_code
        self.text = text


class _FakeClient:
    calls: list = []
    next_resp = _FakeResp(202)

    def __init__(self, *a, **k):
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, *e):
        return False

    async def post(self, url, headers=None, json=None):
        _FakeClient.calls.append({"url": url, "headers": headers, "json": json})
        return _FakeClient.next_resp


@pytest.mark.asyncio
async def test_sendgrid_send_posts_expected_payload(monkeypatch):
    _FakeClient.calls = []
    _FakeClient.next_resp = _FakeResp(202)
    monkeypatch.setattr(httpx, "AsyncClient", _FakeClient)

    await SendGridAdapter("SG.key_abc", "signals@axiara.ai").send(
        to="trader@example.com", subject="3 new signals", text="BUY NVDA\nView: ...",
    )

    assert len(_FakeClient.calls) == 1
    call = _FakeClient.calls[0]
    assert call["url"] == SENDGRID_ENDPOINT
    assert call["headers"]["Authorization"] == "Bearer SG.key_abc"
    assert call["json"]["from"] == {"email": "signals@axiara.ai"}
    assert call["json"]["personalizations"] == [{"to": [{"email": "trader@example.com"}]}]
    assert call["json"]["subject"] == "3 new signals"
    assert call["json"]["content"][0]["value"].startswith("BUY NVDA")


@pytest.mark.asyncio
async def test_sendgrid_send_empty_recipient_raises():
    with pytest.raises(ValueError):
        await SendGridAdapter("SG.key", "from@x.com").send(to="", subject="s", text="t")


@pytest.mark.asyncio
async def test_sendgrid_send_surfaces_provider_error(monkeypatch):
    _FakeClient.calls = []
    _FakeClient.next_resp = _FakeResp(403, '{"errors":[{"message":"sender identity not verified"}]}')
    monkeypatch.setattr(httpx, "AsyncClient", _FakeClient)

    with pytest.raises(RuntimeError) as exc:
        await SendGridAdapter("SG.key", "from@x.com").send(
            to="a@example.com", subject="s", text="t",
        )
    assert "403" in str(exc.value)
    assert "sender identity not verified" in str(exc.value)
