"""Safe byte-offset read of a worker's message_tool.log file.

The caller is responsible for ensuring the path is rooted inside the user
namespace (passed through `user_root`). This module does not re-validate
the path — it just performs the read.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class TailResult:
    content: str
    next_offset: int


def tail_log(path: Path, *, since: int, max_bytes: int) -> TailResult:
    """Return bytes from `path` starting at offset `since`, capped at `max_bytes`."""
    if not path.is_file():
        return TailResult(content="", next_offset=0)
    size = path.stat().st_size
    # If the log was truncated and `since` is past the new end, restart at 0.
    if since > size:
        since = 0
    end = min(since + max_bytes, size)
    with path.open("rb") as f:
        f.seek(since)
        data = f.read(end - since)
    return TailResult(content=data.decode("utf-8", errors="replace"), next_offset=end)
