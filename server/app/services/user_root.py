"""Per-user path-join security primitive.

Every filesystem access in the dashboard server MUST go through one of the
functions here. This module is the single trust boundary for path
construction. Treat it as security-critical.
"""

from __future__ import annotations

import re
from pathlib import Path

USER_ID_RE = re.compile(r"^[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}$")
TICKER_RE = re.compile(r"^[A-Z][A-Z0-9.\-]{0,11}$")
DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


class InvalidUserIdError(ValueError):
    """Raised when a user_id doesn't match the expected UUID format."""


class PathEscapeError(ValueError):
    """Raised when a path component would escape the user namespace."""


def _check_user_id(user_id: str) -> None:
    if not isinstance(user_id, str) or not USER_ID_RE.fullmatch(user_id):
        raise InvalidUserIdError(f"invalid user_id: {user_id!r}")


def _check_segment(name: str, value: str, pattern: re.Pattern[str]) -> None:
    if not isinstance(value, str) or "\0" in value or not pattern.fullmatch(value):
        raise PathEscapeError(f"invalid {name}: {value!r}")


def user_results_dir(root: Path, user_id: str) -> Path:
    """Return the user's namespace root: <root>/users/<user_id>."""
    _check_user_id(user_id)
    return Path(root) / "users" / user_id


def user_run_dir(root: Path, user_id: str, ticker: str, trade_date: str) -> Path:
    """Return the directory holding a specific run's artifacts."""
    _check_user_id(user_id)
    _check_segment("ticker", ticker, TICKER_RE)
    _check_segment("trade_date", trade_date, DATE_RE)
    return user_results_dir(root, user_id) / ticker / trade_date


def user_report_file(
    root: Path, user_id: str, ticker: str, trade_date: str, filename: str
) -> Path:
    """Return the path to a specific report markdown file under reports/."""
    if not isinstance(filename, str) or "/" in filename or "\\" in filename or "\0" in filename:
        raise PathEscapeError(f"invalid filename: {filename!r}")
    if not filename.endswith(".md"):
        raise PathEscapeError(f"only .md filenames allowed: {filename!r}")
    return user_run_dir(root, user_id, ticker, trade_date) / "reports" / filename
