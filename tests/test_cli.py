"""Tests for cli — enable/disable/status/uninstall via CliRunner."""

from __future__ import annotations

import json
from pathlib import Path

from click.testing import CliRunner

from claude_afk import config
from claude_afk.cli import _install_hooks, _uninstall_hooks, main
from claude_afk.config import SlackConfig, load_state, save_state


# --- enable/disable ---


def test_enable_not_configured(afk_home):
    runner = CliRunner()
    result = runner.invoke(main, ["enable", "all"])
    assert result.exit_code == 1
    assert "Not configured" in result.output


def test_disable_not_configured(afk_home):
    runner = CliRunner()
    result = runner.invoke(main, ["disable", "all"])
    assert result.exit_code == 1
    assert "Not configured" in result.output


def test_enable_all(afk_home, sample_config):
    sample_config.save()
    runner = CliRunner()
    result = runner.invoke(main, ["enable", "all"])
    assert result.exit_code == 0
    state = load_state()
    assert state["enabled"] == "all"
    assert str(afk_home) in result.output


def test_enable_session(afk_home, sample_config, tmp_path):
    # Create a claude home with a session file so validation passes
    claude_home = tmp_path / "claude-home"
    session_dir = claude_home / "projects" / "myproject"
    session_dir.mkdir(parents=True)
    (session_dir / "sess-42.jsonl").touch()

    cfg = SlackConfig(
        bot_token=sample_config.bot_token,
        socket_mode_token=sample_config.socket_mode_token,
        user_id=sample_config.user_id,
        dm_channel_id=sample_config.dm_channel_id,
        timeout=sample_config.timeout,
        claude_homes=[str(claude_home)],
    )
    cfg.save()

    runner = CliRunner()
    result = runner.invoke(main, ["enable", "sess-42"])
    assert result.exit_code == 0
    state = load_state()
    assert "sess-42" in state["enabled"]
    assert str(afk_home) in result.output


def test_disable_all(afk_home, sample_config):
    sample_config.save()
    save_state({"enabled": "all"})
    runner = CliRunner()
    result = runner.invoke(main, ["disable", "all"])
    assert result.exit_code == 0
    state = load_state()
    assert state["enabled"] == []
    assert str(afk_home) in result.output


def test_disable_session(afk_home, sample_config, tmp_path):
    claude_home = tmp_path / "claude-home"
    session_dir = claude_home / "projects" / "myproject"
    session_dir.mkdir(parents=True)
    (session_dir / "sess-1.jsonl").touch()

    cfg = SlackConfig(
        bot_token=sample_config.bot_token,
        socket_mode_token=sample_config.socket_mode_token,
        user_id=sample_config.user_id,
        dm_channel_id=sample_config.dm_channel_id,
        timeout=sample_config.timeout,
        claude_homes=[str(claude_home)],
    )
    cfg.save()
    save_state({"enabled": ["sess-1", "sess-2"]})
    runner = CliRunner()
    result = runner.invoke(main, ["disable", "sess-1"])
    assert result.exit_code == 0
    state = load_state()
    assert "sess-1" not in state["enabled"]
    assert "sess-2" in state["enabled"]
    assert str(afk_home) in result.output


def test_disable_session_not_found(afk_home, sample_config):
    cfg = SlackConfig(
        bot_token=sample_config.bot_token,
        socket_mode_token=sample_config.socket_mode_token,
        user_id=sample_config.user_id,
        dm_channel_id=sample_config.dm_channel_id,
        timeout=sample_config.timeout,
        claude_homes=[str(afk_home)],
    )
    cfg.save()
    save_state({"enabled": ["sess-ghost"]})
    runner = CliRunner()
    result = runner.invoke(main, ["disable", "sess-ghost"])
    assert result.exit_code == 1
    assert "not found" in result.output


def test_enable_session_not_found(afk_home, sample_config):
    cfg = SlackConfig(
        bot_token=sample_config.bot_token,
        socket_mode_token=sample_config.socket_mode_token,
        user_id=sample_config.user_id,
        dm_channel_id=sample_config.dm_channel_id,
        timeout=sample_config.timeout,
        claude_homes=[str(afk_home)],
    )
    cfg.save()
    runner = CliRunner()
    result = runner.invoke(main, ["enable", "nonexistent-sess"])
    assert result.exit_code == 1
    assert "not found" in result.output


def test_enable_session_no_claude_homes(afk_home, sample_config):
    sample_config.save()  # sample_config has no claude_homes
    runner = CliRunner()
    result = runner.invoke(main, ["enable", "sess-99"])
    assert result.exit_code == 1
    assert "not found" in result.output


# --- add-home ---


def test_add_home_not_configured(afk_home):
    runner = CliRunner()
    result = runner.invoke(main, ["add-home", "/some/path"])
    assert result.exit_code == 1
    assert "Not configured" in result.output


def test_add_home_path_not_exists(afk_home, sample_config):
    sample_config.save()
    runner = CliRunner()
    result = runner.invoke(main, ["add-home", "/nonexistent/path"])
    assert result.exit_code == 1
    assert "not an existing directory" in result.output


def test_add_home_success(afk_home, sample_config, tmp_path):
    sample_config.save()
    new_home = tmp_path / "new-claude-home"
    new_home.mkdir()

    runner = CliRunner()
    result = runner.invoke(main, ["add-home", str(new_home)])
    assert result.exit_code == 0
    assert "Hooks installed" in result.output
    assert "Registered" in result.output

    # Verify config was updated
    cfg = SlackConfig.from_file()
    assert str(new_home) in cfg.claude_homes

    # Verify hooks were installed
    settings_path = new_home / "settings.json"
    assert settings_path.exists()


def test_add_home_already_registered(afk_home, sample_config, tmp_path):
    new_home = tmp_path / "existing-home"
    new_home.mkdir()
    cfg = SlackConfig(
        bot_token=sample_config.bot_token,
        socket_mode_token=sample_config.socket_mode_token,
        user_id=sample_config.user_id,
        dm_channel_id=sample_config.dm_channel_id,
        timeout=sample_config.timeout,
        claude_homes=[str(new_home)],
    )
    cfg.save()

    runner = CliRunner()
    result = runner.invoke(main, ["add-home", str(new_home)])
    assert result.exit_code == 0
    assert "already registered" in result.output


# --- status ---


def test_status_not_configured(afk_home):
    runner = CliRunner()
    result = runner.invoke(main, ["status"])
    assert result.exit_code == 1
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
    assert str(afk_home) in result.output


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


def test_install_hooks_preserves_existing_hooks_same_event(tmp_path):
    """User has their own PreToolUse hook — it must survive installation."""
    claude_home = tmp_path / "claude"
    claude_home.mkdir()
    user_hook = {
        "matcher": "Bash",
        "hooks": [{"type": "command", "command": "my-custom-linter"}],
    }
    settings_path = claude_home / "settings.json"
    settings_path.write_text(json.dumps({"hooks": {"PreToolUse": [user_hook]}}, indent=2))

    _install_hooks(str(claude_home))

    with open(settings_path) as f:
        settings = json.load(f)

    pre_tool_use = settings["hooks"]["PreToolUse"]
    # User's hook should still be first
    assert pre_tool_use[0] == user_hook
    # claude-afk hooks appended after
    afk_entries = [
        e for e in pre_tool_use
        if any("claude-afk" in h.get("command", "") for h in e.get("hooks", []))
    ]
    assert len(afk_entries) == 2


def test_install_hooks_preserves_existing_hooks_different_event(tmp_path):
    """User has hooks on an event claude-afk doesn't touch — they must survive."""
    claude_home = tmp_path / "claude"
    claude_home.mkdir()
    user_hook = {
        "matcher": "",
        "hooks": [{"type": "command", "command": "my-post-tool-hook"}],
    }
    settings_path = claude_home / "settings.json"
    settings_path.write_text(json.dumps({"hooks": {"PostToolUse": [user_hook]}}, indent=2))

    _install_hooks(str(claude_home))

    with open(settings_path) as f:
        settings = json.load(f)

    # User's PostToolUse hook untouched
    assert settings["hooks"]["PostToolUse"] == [user_hook]
    # claude-afk hooks added to their own events
    assert "PreToolUse" in settings["hooks"]
    assert "Stop" in settings["hooks"]


def test_install_hooks_preserves_non_hook_settings(tmp_path):
    """Non-hook keys in settings.json (permissions, env, etc.) must survive."""
    claude_home = tmp_path / "claude"
    claude_home.mkdir()
    settings_path = claude_home / "settings.json"
    original = {
        "permissions": {"allow": ["Bash(*)"]},
        "env": {"MY_VAR": "hello"},
        "hooks": {},
    }
    settings_path.write_text(json.dumps(original, indent=2))

    _install_hooks(str(claude_home))

    with open(settings_path) as f:
        settings = json.load(f)

    assert settings["permissions"] == {"allow": ["Bash(*)"]}
    assert settings["env"] == {"MY_VAR": "hello"}
    assert "PreToolUse" in settings["hooks"]


def test_install_hooks_reinstall_preserves_user_hooks(tmp_path):
    """Reinstalling claude-afk hooks must not eat user hooks added between installs."""
    claude_home = tmp_path / "claude"
    claude_home.mkdir()

    _install_hooks(str(claude_home))

    # User manually adds their own Stop hook after our install
    settings_path = claude_home / "settings.json"
    with open(settings_path) as f:
        settings = json.load(f)
    user_stop_hook = {
        "matcher": "",
        "hooks": [{"type": "command", "command": "my-stop-notifier"}],
    }
    settings["hooks"]["Stop"].append(user_stop_hook)
    with open(settings_path, "w") as f:
        json.dump(settings, f, indent=2)

    # Reinstall claude-afk
    _install_hooks(str(claude_home))

    with open(settings_path) as f:
        settings = json.load(f)

    stop_hooks = settings["hooks"]["Stop"]
    user_entries = [
        e for e in stop_hooks
        if not any("claude-afk" in h.get("command", "") for h in e.get("hooks", []))
    ]
    afk_entries = [
        e for e in stop_hooks
        if any("claude-afk" in h.get("command", "") for h in e.get("hooks", []))
    ]
    assert len(user_entries) == 1
    assert user_entries[0] == user_stop_hook
    assert len(afk_entries) == 1


def test_uninstall_hooks_preserves_user_hooks(tmp_path):
    """Uninstall removes only claude-afk hooks, user hooks stay."""
    claude_home = tmp_path / "claude"
    claude_home.mkdir()

    _install_hooks(str(claude_home))

    # Add a user hook to PreToolUse
    settings_path = claude_home / "settings.json"
    with open(settings_path) as f:
        settings = json.load(f)
    user_hook = {
        "matcher": "Write",
        "hooks": [{"type": "command", "command": "my-write-guard"}],
    }
    settings["hooks"]["PreToolUse"].insert(0, user_hook)
    with open(settings_path, "w") as f:
        json.dump(settings, f, indent=2)

    result = _uninstall_hooks(str(claude_home))
    assert result is True

    with open(settings_path) as f:
        settings = json.load(f)

    # User's PreToolUse hook survives
    assert settings["hooks"]["PreToolUse"] == [user_hook]
    # Stop and Notification only had claude-afk entries, so they're gone
    assert "Stop" not in settings["hooks"]
    assert "Notification" not in settings["hooks"]


def test_install_hooks_corrupt_settings_json(tmp_path):
    """Corrupt settings.json is replaced gracefully (not a crash)."""
    claude_home = tmp_path / "claude"
    claude_home.mkdir()
    settings_path = claude_home / "settings.json"
    settings_path.write_text("this is not json {{{")

    _install_hooks(str(claude_home))

    with open(settings_path) as f:
        settings = json.load(f)

    # Should have written a clean file with our hooks
    assert "PreToolUse" in settings["hooks"]
    assert "Stop" in settings["hooks"]


def test_uninstall_hooks_no_file(tmp_path):
    result = _uninstall_hooks(str(tmp_path / "nonexistent"))
    assert result is False


# --- uninstall command ---


def test_uninstall_all_homes(afk_home, tmp_path):
    """Bare `uninstall` removes hooks from every registered home."""
    home1 = tmp_path / "home1"
    home1.mkdir()
    _install_hooks(str(home1))

    home2 = tmp_path / "home2"
    home2.mkdir()
    _install_hooks(str(home2))

    cfg = SlackConfig(
        bot_token="xoxb-x",
        socket_mode_token="xapp-x",
        user_id="U1",
        dm_channel_id="D1",
        claude_homes=[str(home1), str(home2)],
    )
    cfg.save()

    runner = CliRunner()
    result = runner.invoke(main, ["uninstall"])
    assert result.exit_code == 0
    assert "Removed 2 Claude homes" in result.output

    # Both settings.json files should have hooks removed
    for home in [home1, home2]:
        with open(home / "settings.json") as f:
            settings = json.load(f)
        assert not settings.get("hooks", {})

    # Config should have empty claude_homes
    updated = SlackConfig.from_file()
    assert updated.claude_homes == []


def test_uninstall_single_home(afk_home, tmp_path):
    """--claude-home targets only one directory."""
    home1 = tmp_path / "home1"
    home1.mkdir()
    _install_hooks(str(home1))

    home2 = tmp_path / "home2"
    home2.mkdir()
    _install_hooks(str(home2))

    cfg = SlackConfig(
        bot_token="xoxb-x",
        socket_mode_token="xapp-x",
        user_id="U1",
        dm_channel_id="D1",
        claude_homes=[str(home1), str(home2)],
    )
    cfg.save()

    runner = CliRunner()
    result = runner.invoke(main, ["uninstall", "--claude-home", str(home1)])
    assert result.exit_code == 0
    assert f"Removed {home1}" in result.output

    # home1 hooks removed, home2 untouched
    with open(home1 / "settings.json") as f:
        assert not json.load(f).get("hooks", {})
    with open(home2 / "settings.json") as f:
        assert "Stop" in json.load(f).get("hooks", {})

    updated = SlackConfig.from_file()
    assert str(home1) not in updated.claude_homes
    assert str(home2) in updated.claude_homes


def test_uninstall_no_homes_registered(afk_home):
    """Bare `uninstall` with no registered homes prints a message and exits cleanly."""
    cfg = SlackConfig(
        bot_token="xoxb-x",
        socket_mode_token="xapp-x",
        user_id="U1",
        dm_channel_id="D1",
        claude_homes=[],
    )
    cfg.save()

    runner = CliRunner()
    result = runner.invoke(main, ["uninstall"])
    assert result.exit_code == 0
    assert "nothing to uninstall" in result.output.lower()
