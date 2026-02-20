"""Tests for transcript — JSONL transcript parsing."""

from __future__ import annotations

import json

from claude_afk.transcript import get_last_assistant_message, get_session_name


# --- get_session_name ---


def test_get_session_name_user_message(tmp_path):
    f = tmp_path / "transcript.jsonl"
    entry = {"type": "user", "message": {"content": "Hello Claude, help me"}}
    f.write_text(json.dumps(entry) + "\n")
    assert get_session_name(str(f)) == "Hello Claude, help me"


def test_get_session_name_content_list(tmp_path):
    f = tmp_path / "transcript.jsonl"
    entry = {
        "type": "user",
        "message": {"content": [{"type": "text", "text": "Fix the bug"}]},
    }
    f.write_text(json.dumps(entry) + "\n")
    assert get_session_name(str(f)) == "Fix the bug"


def test_get_session_name_missing_file():
    assert get_session_name("/nonexistent/path.jsonl") == ""


def test_get_session_name_truncation(tmp_path):
    f = tmp_path / "transcript.jsonl"
    long_text = "x" * 200
    entry = {"type": "user", "message": {"content": long_text}}
    f.write_text(json.dumps(entry) + "\n")
    result = get_session_name(str(f))
    assert len(result) == 80


# --- get_last_assistant_message ---


def test_get_last_assistant_message(tmp_path):
    f = tmp_path / "transcript.jsonl"
    lines = [
        json.dumps({"type": "user", "message": {"content": "hi"}}),
        json.dumps(
            {
                "type": "assistant",
                "message": {"content": [{"type": "text", "text": "Hello!"}]},
            }
        ),
    ]
    f.write_text("\n".join(lines) + "\n")
    assert get_last_assistant_message(str(f)) == "Hello!"


def test_get_last_assistant_message_empty(tmp_path):
    f = tmp_path / "transcript.jsonl"
    entry = {"type": "user", "message": {"content": "hi"}}
    f.write_text(json.dumps(entry) + "\n")
    assert get_last_assistant_message(str(f)) == ""


def test_get_last_assistant_message_multiple(tmp_path):
    f = tmp_path / "transcript.jsonl"
    lines = [
        json.dumps(
            {
                "type": "assistant",
                "message": {"content": [{"type": "text", "text": "First"}]},
            }
        ),
        json.dumps(
            {
                "type": "assistant",
                "message": {"content": [{"type": "text", "text": "Second"}]},
            }
        ),
    ]
    f.write_text("\n".join(lines) + "\n")
    assert get_last_assistant_message(str(f)) == "Second"
