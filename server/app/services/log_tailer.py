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


def _partial_utf8_tail_bytes(data: bytes) -> int:
    """Return number of trailing bytes that form an incomplete UTF-8 sequence.

    0 if `data` ends at a character boundary or the trailing bytes contain an
    invalid leading-byte pattern (in which case the caller should fall through
    to lossy decoding rather than trim indefinitely).

    UTF-8 leading-byte shapes (and how many continuation bytes follow):
        0xxxxxxx                                  → 0 (ASCII, complete)
        110xxxxx 10xxxxxx                         → 1
        1110xxxx 10xxxxxx 10xxxxxx                → 2
        11110xxx 10xxxxxx 10xxxxxx 10xxxxxx       → 3
    A continuation byte matches 10xxxxxx, i.e. `(b & 0xC0) == 0x80`.
    """
    # Walk back at most 4 bytes — a valid UTF-8 sequence is never longer than that.
    n = len(data)
    max_back = min(4, n)
    for i in range(1, max_back + 1):
        b = data[n - i]
        if (b & 0xC0) == 0x80:
            # Continuation byte — keep walking backwards.
            continue
        # Found a non-continuation byte. Decide based on its leading-bit pattern
        # whether the sequence starting here is complete given `i - 1` trailing
        # continuation bytes already seen.
        continuations_seen = i - 1
        if (b & 0x80) == 0x00:
            # ASCII leading byte (0xxxxxxx): the sequence ends here, complete.
            # Anything we walked over after it must therefore be stray continuations
            # — treat as malformed and don't trim.
            return 0
        if (b & 0xE0) == 0xC0:
            needed = 1
        elif (b & 0xF0) == 0xE0:
            needed = 2
        elif (b & 0xF8) == 0xF0:
            needed = 3
        else:
            # Invalid UTF-8 leading byte — let lossy decoding handle it.
            return 0
        if continuations_seen < needed:
            # Incomplete trailing sequence: trim from this leading byte onwards.
            return i
        # Sequence is complete (or has more continuations than valid, which the
        # decoder will flag) — nothing to trim.
        return 0
    # Ran the full 4-byte lookback and saw only continuation bytes with no
    # leading byte in sight: malformed, don't trim.
    return 0


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
    # If more file remains beyond `end`, avoid consuming a partial multi-byte
    # UTF-8 sequence at the read boundary — otherwise the trailing bytes would
    # be dropped and the character would be permanently lost on the next poll.
    # At EOF we fall through to `errors="replace"` so genuinely truncated bytes
    # don't trigger infinite trim-back-off.
    if end < size:
        trim = _partial_utf8_tail_bytes(data)
        if trim:
            data = data[:-trim]
            end -= trim
    return TailResult(content=data.decode("utf-8", errors="replace"), next_offset=end)
