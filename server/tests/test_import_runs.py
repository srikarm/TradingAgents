import uuid
from pathlib import Path

import pytest
from sqlalchemy import select

from app.models.run import Run
from app.models.user import User
from app.scripts.import_runs import import_legacy_runs


def _seed_legacy(root: Path, ticker: str, date: str) -> None:
    base = root / ticker / date / "reports" / "1_analysts"
    base.mkdir(parents=True)
    (base / "market.md").write_text("legacy market")
    (root / ticker / date / "final_trade_decision.md").write_text("legacy final")


@pytest.mark.asyncio
async def test_import_copies_files_and_creates_run_rows(db_session, tmp_path):
    legacy = tmp_path / "legacy"
    target = tmp_path / "dash"
    _seed_legacy(legacy, "NVDA", "2024-05-10")
    _seed_legacy(legacy, "AAPL", "2024-05-09")

    uid = uuid.uuid4()
    db_session.add(User(id=uid, github_id="gh-import"))
    await db_session.flush()

    n = await import_legacy_runs(
        session=db_session,
        legacy_dir=legacy,
        dashboard_dir=target,
        user_id=uid,
    )
    assert n == 2
    rows = (await db_session.execute(select(Run))).scalars().all()
    assert {r.ticker for r in rows} == {"NVDA", "AAPL"}
    assert (target / "users" / str(uid) / "NVDA" / "2024-05-10" / "reports" /
            "1_analysts" / "market.md").read_text() == "legacy market"


@pytest.mark.asyncio
async def test_import_is_idempotent(db_session, tmp_path):
    legacy = tmp_path / "legacy"
    target = tmp_path / "dash"
    _seed_legacy(legacy, "NVDA", "2024-05-10")
    uid = uuid.uuid4()
    db_session.add(User(id=uid, github_id="gh-id2"))
    await db_session.flush()

    n1 = await import_legacy_runs(session=db_session, legacy_dir=legacy,
                                  dashboard_dir=target, user_id=uid)
    n2 = await import_legacy_runs(session=db_session, legacy_dir=legacy,
                                  dashboard_dir=target, user_id=uid)
    assert n1 == 1 and n2 == 0
    rows = (await db_session.execute(select(Run))).scalars().all()
    assert len(rows) == 1


@pytest.mark.asyncio
async def test_import_rejects_bad_ticker_or_date_segments(db_session, tmp_path):
    legacy = tmp_path / "legacy"
    target = tmp_path / "dash"
    (legacy / ".." / "weird").mkdir(parents=True, exist_ok=True)
    (legacy / "lowercase" / "2024-05-10").mkdir(parents=True)
    uid = uuid.uuid4()
    db_session.add(User(id=uid, github_id="gh-id3"))
    await db_session.flush()
    # Should silently skip non-conforming dirs, not raise.
    n = await import_legacy_runs(session=db_session, legacy_dir=legacy,
                                 dashboard_dir=target, user_id=uid)
    assert n == 0
