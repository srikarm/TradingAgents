import uuid

import jwt
import pytest
from fastapi import HTTPException

from app.auth import get_current_user
from app.config import get_settings
from app.models.user import User


def _make_token(*, sub: str, email: str | None = None, provider: str = "github") -> str:
    settings = get_settings()
    payload: dict = {"sub": sub}
    if email:
        payload["email"] = email
    if provider:
        payload["provider"] = provider
    return jwt.encode(payload, settings.nextauth_secret, algorithm=settings.jwt_algorithm)


@pytest.mark.asyncio
async def test_google_jwt_creates_user_with_google_sub(db_session):
    """A first-time Google sign-in (JWT carries provider=google) should
    create a user with google_sub set and email populated, github_id NULL."""
    token = _make_token(sub="google-sub-zzz", email="zara@example.com", provider="google")

    user = await get_current_user(authorization=f"Bearer {token}", db=db_session)

    assert user.google_sub == "google-sub-zzz"
    assert user.github_id is None
    assert user.email == "zara@example.com"


@pytest.mark.asyncio
async def test_legacy_jwt_without_provider_treated_as_github(db_session):
    """JWTs issued before this PR don't carry a `provider` claim. They
    should be treated as GitHub for backward compatibility."""
    token = _make_token(sub="333", email="legacy@example.com", provider="")

    user = await get_current_user(authorization=f"Bearer {token}", db=db_session)

    assert user.github_id == "333"
    assert user.google_sub is None
    assert user.email == "legacy@example.com"


@pytest.mark.asyncio
async def test_signing_in_via_google_links_existing_github_user(db_session):
    """Two-step flow: existing user signed up with GitHub (email
    alice@example.com), then signs in via Google with the same email.
    The Google sign-in should resolve to the SAME user row with both
    provider IDs populated."""
    # Step 1: GitHub user pre-exists
    existing = User(
        id=uuid.uuid4(),
        github_id="444",
        email="alice@example.com",
        google_sub=None,
    )
    db_session.add(existing)
    await db_session.flush()

    # Step 2: Google sign-in arrives
    token = _make_token(sub="google-sub-aaa", email="alice@example.com", provider="google")
    user = await get_current_user(authorization=f"Bearer {token}", db=db_session)

    assert user.id == existing.id, "should resolve to the existing user, not create a new one"
    assert user.github_id == "444", "github_id should remain populated"
    assert user.google_sub == "google-sub-aaa", "google_sub should now be populated"
    assert user.email == "alice@example.com"
