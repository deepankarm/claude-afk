"""Tests for slack.thread — thread state persistence."""

from __future__ import annotations

from claude_afk.slack import thread


def test_load_missing(afk_home):
    assert thread.load("nonexistent-session") == {}


def test_save_then_load(afk_home):
    thread.save("sess-123", "1234567890.123456")
    state = thread.load("sess-123")
    assert state["thread_ts"] == "1234567890.123456"


def test_get_state_path(afk_home):
    path = thread.get_state_path("my-session")
    assert path.endswith("my-session.json")
    assert "threads" in path
