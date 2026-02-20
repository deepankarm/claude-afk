"""Tests for hooks.pretooluse — permission parsing, question resolution, emit, handlers."""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

from claude_afk.hooks.pretooluse import (
    _emit,
    _handle_ask_user_question,
    _handle_permission,
    parse_permission_reply,
    resolve_question_answer,
)


# --- parse_permission_reply ---


def test_parse_permission_reply_allow():
    for word in ("allow", "yes", "y", "approve", "ok", "lgtm", "go", "proceed", "sure", "yep"):
        assert parse_permission_reply(word) == "allow", f"Expected allow for {word!r}"


def test_parse_permission_reply_deny():
    for word in ("deny", "no", "n", "reject", "block", "stop", "nope", "cancel"):
        assert parse_permission_reply(word) == "deny", f"Expected deny for {word!r}"


def test_parse_permission_reply_unclear():
    assert parse_permission_reply("maybe later") == "unclear"
    assert parse_permission_reply("hmm") == "unclear"


def test_parse_permission_reply_case_insensitive():
    assert parse_permission_reply("YES") == "allow"
    assert parse_permission_reply("Allow") == "allow"
    assert parse_permission_reply("DENY") == "deny"
    assert parse_permission_reply("No") == "deny"


def test_parse_permission_reply_with_punctuation():
    assert parse_permission_reply("yes!") == "allow"
    assert parse_permission_reply("ok.") == "allow"
    assert parse_permission_reply("no!") == "deny"


# --- resolve_question_answer ---


def test_resolve_question_answer_number():
    q = {"options": [{"label": "Alpha"}, {"label": "Beta"}], "multiSelect": False}
    assert resolve_question_answer("1", q) == "Alpha"
    assert resolve_question_answer("2", q) == "Beta"


def test_resolve_question_answer_out_of_range():
    q = {"options": [{"label": "A"}], "multiSelect": False}
    assert resolve_question_answer("99", q) == "99"


def test_resolve_question_answer_multi():
    q = {"options": [{"label": "A"}, {"label": "B"}, {"label": "C"}], "multiSelect": True}
    assert resolve_question_answer("1,3", q) == "A, C"


def test_resolve_question_answer_text():
    q = {"options": [{"label": "A"}], "multiSelect": False}
    assert resolve_question_answer("custom answer", q) == "custom answer"


# --- _emit ---


def test_emit_allow(capsys):
    _emit("allow", "Approved via Slack")
    output = json.loads(capsys.readouterr().out.strip())
    assert output["hookSpecificOutput"]["permissionDecision"] == "allow"
    assert output["hookSpecificOutput"]["permissionDecisionReason"] == "Approved via Slack"


def test_emit_deny(capsys):
    _emit("deny", "Denied via Slack: no")
    output = json.loads(capsys.readouterr().out.strip())
    assert output["hookSpecificOutput"]["permissionDecision"] == "deny"
    assert "Denied via Slack" in output["hookSpecificOutput"]["permissionDecisionReason"]


# --- _handle_permission ---


def test_handle_permission_allow(capsys):
    bridge = MagicMock()
    bridge.post.return_value = True
    bridge.wait_for_reply.return_value = "yes"
    _handle_permission(bridge, "Bash", {"command": "ls"})
    output = json.loads(capsys.readouterr().out.strip())
    assert output["hookSpecificOutput"]["permissionDecision"] == "allow"


def test_handle_permission_deny(capsys):
    bridge = MagicMock()
    bridge.post.return_value = True
    bridge.wait_for_reply.return_value = "deny"
    _handle_permission(bridge, "Bash", {"command": "rm -rf /"})
    output = json.loads(capsys.readouterr().out.strip())
    assert output["hookSpecificOutput"]["permissionDecision"] == "deny"


# --- _handle_ask_user_question ---


def test_handle_ask_user_question(capsys):
    bridge = MagicMock()
    bridge.post.return_value = True
    bridge.wait_for_reply.return_value = "1"

    questions = [
        {
            "question": "Pick one?",
            "header": "Choice",
            "options": [{"label": "Opt A"}, {"label": "Opt B"}],
            "multiSelect": False,
        }
    ]
    _handle_ask_user_question(bridge, questions)
    output = json.loads(capsys.readouterr().out.strip())
    assert output["hookSpecificOutput"]["permissionDecision"] == "deny"
    assert "Opt A" in output["hookSpecificOutput"]["permissionDecisionReason"]
