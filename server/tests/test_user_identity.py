# server/tests/test_user_identity.py
import uuid
import pytest

from app.models.user import User, find_or_create_by_identity


@pytest.mark.asyncio
async def test_finds_user_by_email_and_backfills_google_sub(db_session):
    """Existing user with only github_id; signing in via Google with the
    same email should return that user and populate google_sub."""
    existing = User(
        id=uuid.uuid4(),
        github_id="111",
        email="alice@example.com",
        google_sub=None,
    )
    db_session.add(existing)
    await db_session.flush()

    found = await find_or_create_by_identity(
        db_session,
        email="alice@example.com",
        github_id=None,
        google_sub="google-sub-aaa",
    )

    assert found.id == existing.id, "should return the existing user, not create a new one"
    assert found.google_sub == "google-sub-aaa", "should backfill google_sub"
    assert found.github_id == "111", "should not clobber existing github_id"


@pytest.mark.asyncio
async def test_legacy_user_without_email_found_by_github_id(db_session):
    """Pre-migration user with email=NULL, only github_id set. Signing in
    again with GitHub provides the email — find by github_id and backfill
    email."""
    legacy = User(
        id=uuid.uuid4(),
        github_id="222",
        email=None,
        google_sub=None,
    )
    db_session.add(legacy)
    await db_session.flush()

    found = await find_or_create_by_identity(
        db_session,
        email="bob@example.com",
        github_id="222",
        google_sub=None,
    )

    assert found.id == legacy.id, "should return the legacy user"
    assert found.email == "bob@example.com", "should backfill email"
    assert found.github_id == "222"


@pytest.mark.asyncio
async def test_creates_new_user_when_no_match(db_session):
    """First-ever sign-in for an unknown identity creates a new user
    with the supplied fields."""
    found = await find_or_create_by_identity(
        db_session,
        email="charlie@example.com",
        github_id=None,
        google_sub="google-sub-ccc",
    )
    await db_session.flush()

    assert found.email == "charlie@example.com"
    assert found.google_sub == "google-sub-ccc"
    assert found.github_id is None


@pytest.mark.asyncio
async def test_finds_by_google_sub_when_email_unknown(db_session):
    """If the existing user has google_sub set and email=NULL (unlikely
    edge case but possible after partial backfill), find by google_sub."""
    legacy = User(
        id=uuid.uuid4(),
        github_id=None,
        google_sub="google-sub-ddd",
        email=None,
    )
    db_session.add(legacy)
    await db_session.flush()

    found = await find_or_create_by_identity(
        db_session,
        email="dan@example.com",
        github_id=None,
        google_sub="google-sub-ddd",
    )

    assert found.id == legacy.id, "should match by google_sub"
    assert found.email == "dan@example.com", "should backfill email"
