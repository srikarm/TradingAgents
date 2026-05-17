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
