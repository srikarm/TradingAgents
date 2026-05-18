from pathlib import Path

import pytest

from app.services.log_tailer import TailResult, tail_log


def test_tail_returns_empty_when_file_missing(tmp_path: Path):
    result = tail_log(tmp_path / "missing.log", since=0, max_bytes=1024)
    assert result == TailResult(content="", next_offset=0)


def test_tail_returns_full_content_from_offset_zero(tmp_path: Path):
    log = tmp_path / "msg.log"
    log.write_text("line one\nline two\n")
    result = tail_log(log, since=0, max_bytes=1024)
    assert result.content == "line one\nline two\n"
    assert result.next_offset == len(b"line one\nline two\n")


def test_tail_returns_only_appended_bytes(tmp_path: Path):
    log = tmp_path / "msg.log"
    log.write_text("first\n")
    r1 = tail_log(log, since=0, max_bytes=1024)
    log.write_text("first\nsecond\n")
    r2 = tail_log(log, since=r1.next_offset, max_bytes=1024)
    assert r2.content == "second\n"
    assert r2.next_offset == len(b"first\nsecond\n")


def test_tail_caps_at_max_bytes(tmp_path: Path):
    log = tmp_path / "msg.log"
    log.write_bytes(b"x" * 5000)
    result = tail_log(log, since=0, max_bytes=1024)
    assert len(result.content.encode("utf-8")) == 1024
    assert result.next_offset == 1024


def test_tail_resets_when_since_exceeds_size(tmp_path: Path):
    """If the log was rotated/truncated and `since` is past end of file,
    return everything from byte 0 instead of an empty response."""
    log = tmp_path / "msg.log"
    log.write_text("fresh\n")
    result = tail_log(log, since=10_000, max_bytes=1024)
    assert result.content == "fresh\n"
    assert result.next_offset == len(b"fresh\n")


# -- UTF-8 boundary tests -------------------------------------------------------
#
# `tail_log` reads byte-offset slices. If the boundary cuts through a multi-byte
# UTF-8 character we MUST NOT consume the partial leading bytes — otherwise the
# next poll resumes after them and the character is silently lost. The fix: when
# more file remains beyond the read end, detect a partial trailing UTF-8 sequence
# and back `next_offset` up so the partial bytes are re-read on the next call.


def test_tail_preserves_2byte_char_split_across_boundary(tmp_path: Path):
    """`é` is 0xC3 0xA9 — boundary BETWEEN those two bytes must not lose it."""
    log = tmp_path / "msg.log"
    payload = "prefix é suffix".encode("utf-8")  # b"prefix \xc3\xa9 suffix"
    log.write_bytes(payload)

    # max_bytes=8 puts the read boundary right after the leading 0xC3,
    # leaving the trailing 0xA9 unread.
    r1 = tail_log(log, since=0, max_bytes=8)
    assert r1.content == "prefix "
    assert r1.next_offset == 7  # AT 0xC3, not past 0xA9

    # Second call resumes from the leading byte and reassembles the char.
    r2 = tail_log(log, since=r1.next_offset, max_bytes=1024)
    assert r2.content == "é suffix"
    assert "�" not in r2.content
    assert r2.next_offset == len(payload)


def test_tail_preserves_3byte_char_split_across_boundary(tmp_path: Path):
    """`中` is 0xE4 0xB8 0xAD — boundary at either intermediate position
    (after the leading byte, or after one continuation) must not lose it."""
    log = tmp_path / "msg.log"
    payload = "a中b".encode("utf-8")  # b"a\xe4\xb8\xadb"
    log.write_bytes(payload)

    # Boundary right after the leading 0xE4 (needs 2 continuations, has 0).
    r1 = tail_log(log, since=0, max_bytes=2)
    assert r1.content == "a"
    assert r1.next_offset == 1

    r1b = tail_log(log, since=r1.next_offset, max_bytes=1024)
    assert r1b.content == "中b"
    assert "�" not in r1b.content

    # Boundary after the leading byte + 1 continuation (needs 2, has 1).
    r2 = tail_log(log, since=0, max_bytes=3)
    assert r2.content == "a"
    assert r2.next_offset == 1

    r2b = tail_log(log, since=r2.next_offset, max_bytes=1024)
    assert r2b.content == "中b"
    assert "�" not in r2b.content


def test_tail_preserves_4byte_emoji_split_across_boundary(tmp_path: Path):
    """`🎯` is 0xF0 0x9F 0x8E 0xAF — boundary at any of the three intermediate
    positions must not lose it."""
    log = tmp_path / "msg.log"
    payload = "a🎯b".encode("utf-8")  # b"a\xf0\x9f\x8e\xafb"
    log.write_bytes(payload)

    # Three intermediate boundaries: after the leading byte, after 1 cont, after 2 cont.
    for max_bytes in (2, 3, 4):
        r1 = tail_log(log, since=0, max_bytes=max_bytes)
        assert r1.content == "a", f"max_bytes={max_bytes}: got {r1.content!r}"
        assert r1.next_offset == 1, f"max_bytes={max_bytes}: got offset {r1.next_offset}"

        r2 = tail_log(log, since=r1.next_offset, max_bytes=1024)
        assert r2.content == "🎯b", f"max_bytes={max_bytes}: got {r2.content!r}"
        assert "�" not in r2.content


def test_tail_does_not_trim_at_eof_with_truly_truncated_bytes(tmp_path: Path):
    """If we're reading TO the end of the file and the file itself is truncated
    mid-sequence, fall through to `errors="replace"` rather than trim — otherwise
    we'd back-off forever waiting for bytes that will never arrive."""
    log = tmp_path / "msg.log"
    log.write_bytes(b"hi\xc3")  # leading byte with no continuation, then EOF

    result = tail_log(log, since=0, max_bytes=1024)
    # Decoded with errors="replace" — the partial 0xC3 becomes U+FFFD.
    assert result.content == "hi�"
    # next_offset reaches end-of-file: no infinite trim-back-off.
    assert result.next_offset == 3
