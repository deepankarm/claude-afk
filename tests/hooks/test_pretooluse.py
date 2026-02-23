"""Tests for hooks.pretooluse — permission parsing, question resolution, emit, handlers."""

from __future__ import annotations

import json
from unittest.mock import MagicMock

from claude_afk.hooks.pretooluse import (
    _emit,
    _handle_ask_user_question,
    _handle_permission,
    parse_permission_reply,
    resolve_question_answer,
    run,
)
from claude_afk.permissions import Decision

# --- parse_permission_reply ---


def test_parse_permission_reply_allow():
    for word in ("allow", "yes", "y", "approve", "ok", "lgtm", "go", "proceed", "sure", "yep"):
        assert parse_permission_reply(word) == Decision.ALLOW, f"Expected ALLOW for {word!r}"


def test_parse_permission_reply_deny():
    for word in ("deny", "no", "n", "reject", "block", "stop", "nope", "cancel"):
        assert parse_permission_reply(word) == Decision.DENY, f"Expected DENY for {word!r}"


def test_parse_permission_reply_unclear():
    assert parse_permission_reply("maybe later") == Decision.UNCLEAR
    assert parse_permission_reply("hmm") == Decision.UNCLEAR


def test_parse_permission_reply_case_insensitive():
    assert parse_permission_reply("YES") == Decision.ALLOW
    assert parse_permission_reply("Allow") == Decision.ALLOW
    assert parse_permission_reply("DENY") == Decision.DENY
    assert parse_permission_reply("No") == Decision.DENY


def test_parse_permission_reply_with_punctuation():
    assert parse_permission_reply("yes!") == Decision.ALLOW
    assert parse_permission_reply("ok.") == Decision.ALLOW
    assert parse_permission_reply("no!") == Decision.DENY


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
    _handle_permission(bridge, "Bash", {"command": "ls"}, "sess-test")
    output = json.loads(capsys.readouterr().out.strip())
    assert output["hookSpecificOutput"]["permissionDecision"] == "allow"


def test_handle_permission_deny(capsys):
    bridge = MagicMock()
    bridge.post.return_value = True
    bridge.wait_for_reply.return_value = "deny"
    _handle_permission(bridge, "Bash", {"command": "rm -rf /"}, "sess-test")
    output = json.loads(capsys.readouterr().out.strip())
    assert output["hookSpecificOutput"]["permissionDecision"] == "deny"


def test_handle_permission_caches_read_allow(capsys, tmp_path, monkeypatch):
    import claude_afk.permissions as perms

    monkeypatch.setattr(perms, "AFK_HOME", tmp_path)

    bridge = MagicMock()
    bridge.post.return_value = True
    bridge.wait_for_reply.return_value = "y"
    _handle_permission(bridge, "Read", {"file_path": "/tmp/.env"}, "sess-cache")
    capsys.readouterr()

    # Verify cache was written per-file (only sensitive files reach _handle_permission)
    result = perms.check_session_permission("sess-cache", "Read", {"file_path": "/tmp/.env"})
    assert result == "allow"


def test_handle_permission_caches_read_deny(capsys, tmp_path, monkeypatch):
    import claude_afk.permissions as perms

    monkeypatch.setattr(perms, "AFK_HOME", tmp_path)

    bridge = MagicMock()
    bridge.post.return_value = True
    bridge.wait_for_reply.return_value = "n"
    _handle_permission(bridge, "Read", {"file_path": "/tmp/.env"}, "sess-cache")
    capsys.readouterr()

    result = perms.check_session_permission("sess-cache", "Read", {"file_path": "/tmp/.env"})
    assert result == "deny"


def test_handle_permission_caches_edit_allow(capsys, tmp_path, monkeypatch):
    import claude_afk.permissions as perms

    monkeypatch.setattr(perms, "AFK_HOME", tmp_path)

    bridge = MagicMock()
    bridge.post.return_value = True
    bridge.wait_for_reply.return_value = "y"
    _handle_permission(bridge, "Edit", {"file_path": "/tmp/main.py"}, "sess-cache")
    capsys.readouterr()

    result = perms.check_session_permission("sess-cache", "Edit", {"file_path": "/tmp/main.py"})
    assert result == "allow"
    # Different file is not cached
    other = perms.check_session_permission("sess-cache", "Edit", {"file_path": "/tmp/other.py"})
    assert other is None


def test_handle_permission_no_cache_for_bash(capsys, tmp_path, monkeypatch):
    import claude_afk.permissions as perms

    monkeypatch.setattr(perms, "AFK_HOME", tmp_path)

    bridge = MagicMock()
    bridge.post.return_value = True
    bridge.wait_for_reply.return_value = "y"
    _handle_permission(bridge, "Bash", {"command": "ls"}, "sess-cache")
    capsys.readouterr()

    # Session dir should not even exist for Bash
    path = tmp_path / "sessions" / "sess-cache" / "permissions.json"
    assert not path.exists()


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


# --- run() auto-allow policies ---


def _make_data(tool_name, tool_input, session_id="sess-auto"):
    return {
        "tool_name": tool_name,
        "tool_input": tool_input,
        "session_id": session_id,
        "cwd": "/tmp/fake",
    }


def _mock_config():
    return MagicMock()


def test_run_auto_allows_read_normal_file(capsys, monkeypatch):
    monkeypatch.setattr("claude_afk.hooks.pretooluse.load_cc_permission_rules", lambda cwd: [])
    data = _make_data("Read", {"file_path": "/path/to/main.py"})
    run(data, _mock_config())
    output = json.loads(capsys.readouterr().out.strip())
    assert output["hookSpecificOutput"]["permissionDecision"] == "allow"
    assert "Auto-allowed" in output["hookSpecificOutput"]["permissionDecisionReason"]


def test_run_auto_allows_grep(capsys, monkeypatch):
    monkeypatch.setattr("claude_afk.hooks.pretooluse.load_cc_permission_rules", lambda cwd: [])
    data = _make_data("Grep", {"pattern": "foo", "path": "/tmp"})
    run(data, _mock_config())
    output = json.loads(capsys.readouterr().out.strip())
    assert output["hookSpecificOutput"]["permissionDecision"] == "allow"


def test_run_auto_allows_glob(capsys, monkeypatch):
    monkeypatch.setattr("claude_afk.hooks.pretooluse.load_cc_permission_rules", lambda cwd: [])
    data = _make_data("Glob", {"pattern": "**/*.py"})
    run(data, _mock_config())
    output = json.loads(capsys.readouterr().out.strip())
    assert output["hookSpecificOutput"]["permissionDecision"] == "allow"


def test_run_prompts_for_sensitive_read(capsys, monkeypatch, tmp_path):
    import claude_afk.permissions as perms

    monkeypatch.setattr(perms, "AFK_HOME", tmp_path)
    monkeypatch.setattr("claude_afk.hooks.pretooluse.load_cc_permission_rules", lambda cwd: [])

    bridge = MagicMock()
    bridge.post.return_value = True
    bridge.wait_for_reply.return_value = "y"

    monkeypatch.setattr(
        "claude_afk.hooks.pretooluse.SlackBridge",
        lambda config, sid: MagicMock(__enter__=lambda s: bridge, __exit__=lambda *a: None),
    )

    data = _make_data("Read", {"file_path": "/path/to/.env"})
    run(data, _mock_config())
    output = json.loads(capsys.readouterr().out.strip())
    assert output["hookSpecificOutput"]["permissionDecision"] == "allow"
    # Should have posted to Slack (not auto-allowed)
    bridge.post.assert_called_once()
