"""Tests for cli — enable/disable/status/uninstall via CliRunner."""

from __future__ import annotations

import json
from pathlib import Path

from click.testing import CliRunner

from claude_afk import config
from claude_afk.cli import _install_hooks, _uninstall_hooks, main
from claude_afk.config import SlackConfig, load_state, save_state


# --- enable/disable ---


def test_enable_all(afk_home):
    runner = CliRunner()
    result = runner.invoke(main, ["enable", "all"])
    assert result.exit_code == 0
    state = load_state()
    assert state["enabled"] == "all"


def test_enable_session(afk_home):
    runner = CliRunner()
    result = runner.invoke(main, ["enable", "sess-42"])
    assert result.exit_code == 0
    state = load_state()
    assert "sess-42" in state["enabled"]


def test_disable_all(afk_home):
    save_state({"enabled": "all"})
    runner = CliRunner()
    result = runner.invoke(main, ["disable", "all"])
    assert result.exit_code == 0
    state = load_state()
    assert state["enabled"] == []


def test_disable_session(afk_home):
    save_state({"enabled": ["sess-1", "sess-2"]})
    runner = CliRunner()
    result = runner.invoke(main, ["disable", "sess-1"])
    assert result.exit_code == 0
    state = load_state()
    assert "sess-1" not in state["enabled"]
    assert "sess-2" in state["enabled"]


# --- status ---


def test_status_not_configured(afk_home):
    runner = CliRunner()
    result = runner.invoke(main, ["status"])
    assert result.exit_code == 0
    assert "Not configured" in result.output


def test_status_configured(afk_home):
    cfg = SlackConfig(
        bot_token="xoxb-x",
        socket_mode_token="xapp-x",
        user_id="U123",
        dm_channel_id="D456",
        claude_homes=["/home/user/.claude"],
    )
    cfg.save()
    save_state({"enabled": "all"})

    runner = CliRunner()
    result = runner.invoke(main, ["status"])
    assert result.exit_code == 0
    assert "U123" in result.output
    assert "D456" in result.output
    assert "ALL enabled" in result.output


# --- install/uninstall hooks ---


def test_install_hooks(tmp_path):
    claude_home = str(tmp_path / "claude")
    Path(claude_home).mkdir()
    _install_hooks(claude_home)

    settings_path = Path(claude_home) / "settings.json"
    with open(settings_path) as f:
        settings = json.load(f)

    hooks = settings["hooks"]
    assert "PreToolUse" in hooks
    assert "Stop" in hooks
    assert "Notification" in hooks
    # Verify the command contains claude-afk
    cmds = [
        h["command"]
        for entry in hooks["PreToolUse"]
        for h in entry.get("hooks", [])
    ]
    assert any("claude-afk" in c for c in cmds)


def test_install_hooks_idempotent(tmp_path):
    claude_home = str(tmp_path / "claude")
    Path(claude_home).mkdir()
    _install_hooks(claude_home)
    _install_hooks(claude_home)

    settings_path = Path(claude_home) / "settings.json"
    with open(settings_path) as f:
        settings = json.load(f)

    # Should not have duplicate PreToolUse entries (the source installs 2 matchers)
    pre_tool_use = settings["hooks"]["PreToolUse"]
    afk_entries = [
        e
        for e in pre_tool_use
        if any("claude-afk" in h.get("command", "") for h in e.get("hooks", []))
    ]
    assert len(afk_entries) == 2  # AskUserQuestion matcher + catch-all


def test_uninstall_hooks(tmp_path):
    claude_home = str(tmp_path / "claude")
    Path(claude_home).mkdir()
    _install_hooks(claude_home)
    result = _uninstall_hooks(claude_home)
    assert result is True

    settings_path = Path(claude_home) / "settings.json"
    with open(settings_path) as f:
        settings = json.load(f)

    # All hook events should be removed since they only had claude-afk entries
    assert "PreToolUse" not in settings.get("hooks", {})
    assert "Stop" not in settings.get("hooks", {})


def test_uninstall_hooks_no_file(tmp_path):
    result = _uninstall_hooks(str(tmp_path / "nonexistent"))
    assert result is False
