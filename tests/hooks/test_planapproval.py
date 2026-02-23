"""Tests for hooks.planapproval — plan approval via PermissionRequest hook."""

from __future__ import annotations

import json
from unittest.mock import MagicMock

from claude_afk.hooks.planapproval import _emit, run

# --- _emit ---


def test_emit_allow(capsys):
    _emit("allow")
    output = json.loads(capsys.readouterr().out.strip())
    assert output["hookSpecificOutput"]["hookEventName"] == "PermissionRequest"
    assert output["hookSpecificOutput"]["decision"]["behavior"] == "allow"
    assert "message" not in output["hookSpecificOutput"]["decision"]


def test_emit_deny_with_message(capsys):
    _emit("deny", "User wants changes")
    output = json.loads(capsys.readouterr().out.strip())
    assert output["hookSpecificOutput"]["decision"]["behavior"] == "deny"
    assert output["hookSpecificOutput"]["decision"]["message"] == "User wants changes"


# --- run() ---


def _mock_config():
    return MagicMock()


def test_run_approve(capsys, monkeypatch):
    bridge = MagicMock()
    bridge.post.return_value = True
    bridge.wait_for_reply.return_value = "yes"

    monkeypatch.setattr(
        "claude_afk.hooks.planapproval.SlackBridge",
        lambda config, sid: MagicMock(
            __enter__=lambda s: bridge, __exit__=lambda *a: None
        ),
    )

    data = {
        "session_id": "sess-plan",
        "tool_input": {"plan": "## My Plan\n1. Step one"},
    }
    run(data, _mock_config())
    output = json.loads(capsys.readouterr().out.strip())
    assert output["hookSpecificOutput"]["decision"]["behavior"] == "allow"
    # Should post confirmation
    assert any("approved" in str(c).lower() for c in bridge.post.call_args_list)


def test_run_deny(capsys, monkeypatch):
    bridge = MagicMock()
    bridge.post.return_value = True
    bridge.wait_for_reply.return_value = "no"

    monkeypatch.setattr(
        "claude_afk.hooks.planapproval.SlackBridge",
        lambda config, sid: MagicMock(
            __enter__=lambda s: bridge, __exit__=lambda *a: None
        ),
    )

    data = {
        "session_id": "sess-plan",
        "tool_input": {"plan": "## Plan\n1. Bad step"},
    }
    run(data, _mock_config())
    output = json.loads(capsys.readouterr().out.strip())
    assert output["hookSpecificOutput"]["decision"]["behavior"] == "deny"
    assert "changes" in output["hookSpecificOutput"]["decision"]["message"].lower()


def test_run_feedback_as_deny(capsys, monkeypatch):
    """Unclear reply (not y/n) is treated as feedback → deny with message."""
    bridge = MagicMock()
    bridge.post.return_value = True
    bridge.wait_for_reply.return_value = "please add error handling to step 3"

    monkeypatch.setattr(
        "claude_afk.hooks.planapproval.SlackBridge",
        lambda config, sid: MagicMock(
            __enter__=lambda s: bridge, __exit__=lambda *a: None
        ),
    )

    data = {
        "session_id": "sess-plan",
        "tool_input": {"plan": "## Plan\n1. Step"},
    }
    run(data, _mock_config())
    output = json.loads(capsys.readouterr().out.strip())
    assert output["hookSpecificOutput"]["decision"]["behavior"] == "deny"
    assert "error handling" in output["hookSpecificOutput"]["decision"]["message"]


def test_run_timeout_auto_approves(capsys, monkeypatch):
    bridge = MagicMock()
    bridge.post.return_value = True
    bridge.wait_for_reply.return_value = None

    monkeypatch.setattr(
        "claude_afk.hooks.planapproval.SlackBridge",
        lambda config, sid: MagicMock(
            __enter__=lambda s: bridge, __exit__=lambda *a: None
        ),
    )

    data = {
        "session_id": "sess-plan",
        "tool_input": {"plan": "## Plan"},
    }
    run(data, _mock_config())
    output = json.loads(capsys.readouterr().out.strip())
    assert output["hookSpecificOutput"]["decision"]["behavior"] == "allow"


def test_run_empty_plan_auto_approves(capsys):
    """No plan content and no prompts → auto-approve without Slack."""
    data = {
        "session_id": "sess-plan",
        "tool_input": {},
    }
    run(data, _mock_config())
    output = json.loads(capsys.readouterr().out.strip())
    assert output["hookSpecificOutput"]["decision"]["behavior"] == "allow"


def test_run_post_failure_auto_approves(capsys, monkeypatch):
    bridge = MagicMock()
    bridge.post.return_value = False

    monkeypatch.setattr(
        "claude_afk.hooks.planapproval.SlackBridge",
        lambda config, sid: MagicMock(
            __enter__=lambda s: bridge, __exit__=lambda *a: None
        ),
    )

    data = {
        "session_id": "sess-plan",
        "tool_input": {"plan": "## Plan"},
    }
    run(data, _mock_config())
    output = json.loads(capsys.readouterr().out.strip())
    assert output["hookSpecificOutput"]["decision"]["behavior"] == "allow"


def test_run_with_allowed_prompts(capsys, monkeypatch):
    bridge = MagicMock()
    bridge.post.return_value = True
    bridge.wait_for_reply.return_value = "approve"

    monkeypatch.setattr(
        "claude_afk.hooks.planapproval.SlackBridge",
        lambda config, sid: MagicMock(
            __enter__=lambda s: bridge, __exit__=lambda *a: None
        ),
    )

    data = {
        "session_id": "sess-plan",
        "tool_input": {
            "allowedPrompts": [
                {"tool": "Bash", "prompt": "run tests"},
            ],
        },
    }
    run(data, _mock_config())
    output = json.loads(capsys.readouterr().out.strip())
    assert output["hookSpecificOutput"]["decision"]["behavior"] == "allow"
    # Should have posted the plan with prompts
    posted_text = bridge.post.call_args_list[0][0][0]
    assert "Bash" in posted_text
