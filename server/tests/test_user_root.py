import uuid
from pathlib import Path

import pytest

from app.services.user_root import (
    InvalidUserIdError,
    PathEscapeError,
    user_report_file,
    user_results_dir,
    user_run_dir,
)

GOOD = str(uuid.uuid4())
BAD_IDS = [
    "../etc",
    "..",
    "",
    "/abs/path",
    "f0" * 17 + "g0",  # right length, invalid hex
    "not-a-uuid",
    "f0f0f0f0-f0f0-f0f0-f0f0-f0f0f0f0f0f0\0",  # nul byte
    " " + str(uuid.uuid4()),
]


@pytest.fixture
def root(tmp_path: Path) -> Path:
    return tmp_path / "dash"


def test_user_results_dir_creates_under_user_namespace(root: Path):
    p = user_results_dir(root, GOOD)
    assert p == root / "users" / GOOD
    assert root in p.parents


def test_user_run_dir_joins_ticker_and_date(root: Path):
    p = user_run_dir(root, GOOD, "NVDA", "2024-05-10")
    assert p == root / "users" / GOOD / "NVDA" / "2024-05-10"


@pytest.mark.parametrize("bad", BAD_IDS)
def test_invalid_user_id_rejected(root: Path, bad: str):
    with pytest.raises(InvalidUserIdError):
        user_results_dir(root, bad)


@pytest.mark.parametrize(
    "ticker",
    ["..", "../etc", "/abs", "NVDA/../AAPL", "NV\0DA", "", " NVDA"],
)
def test_path_escape_in_ticker_rejected(root: Path, ticker: str):
    with pytest.raises(PathEscapeError):
        user_run_dir(root, GOOD, ticker, "2024-05-10")


@pytest.mark.parametrize(
    "date",
    ["..", "2024/05/10", "2024-05-10/../..", "2024-05-10\0", "", "2024-05-1"],
)
def test_path_escape_in_date_rejected(root: Path, date: str):
    with pytest.raises(PathEscapeError):
        user_run_dir(root, GOOD, "NVDA", date)


def test_resolved_path_must_be_inside_root(root: Path):
    # Even if all components individually look safe, the resolved path must
    # remain inside root. Symlink-escape style attacks would surface here.
    root.mkdir(parents=True)
    (root / "users").mkdir()
    (root / "users" / GOOD).mkdir()
    p = user_run_dir(root, GOOD, "NVDA", "2024-05-10")
    p.mkdir(parents=True)
    assert root.resolve() in p.resolve().parents


def test_user_report_file_happy_path(root: Path):
    p = user_report_file(root, GOOD, "NVDA", "2024-05-10", "market.md")
    assert p == root / "users" / GOOD / "NVDA" / "2024-05-10" / "reports" / "market.md"


@pytest.mark.parametrize(
    "filename",
    [
        "../escape.md",         # slash
        "sub/dir.md",            # slash
        "win\\path.md",          # backslash
        "with\0nul.md",          # nul byte
        "report.txt",            # wrong extension
        "report",                # no extension
        "",                      # empty
        ".md",                   # only extension
    ],
)
def test_user_report_file_rejects_bad_filename(root: Path, filename: str):
    with pytest.raises(PathEscapeError):
        user_report_file(root, GOOD, "NVDA", "2024-05-10", filename)


def test_user_report_file_inherits_user_id_validation(root: Path):
    with pytest.raises(InvalidUserIdError):
        user_report_file(root, "not-a-uuid", "NVDA", "2024-05-10", "market.md")


def test_user_report_file_inherits_ticker_validation(root: Path):
    with pytest.raises(PathEscapeError):
        user_report_file(root, GOOD, "../bad", "2024-05-10", "market.md")
