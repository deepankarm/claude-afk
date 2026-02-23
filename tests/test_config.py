"""Tests for config — SlackConfig, state management, ensure_home."""

from __future__ import annotations

import os
import stat

from claude_afk.config import (
    SlackConfig,
    is_session_enabled,
    load_state,
    save_state,
    session_exists,
    setup_logging,
)


def test_ensure_home_creates_dirs(afk_home):
    assert (afk_home / "slack" / "threads").is_dir()
    assert (afk_home / "logs").is_dir()


def test_slack_config_from_file_missing(afk_home):
    cfg = SlackConfig.from_file()
    assert cfg.bot_token == ""
    assert cfg.user_id == ""


def test_slack_config_roundtrip(afk_home):
    original = SlackConfig(
        bot_token="xoxb-abc",
        socket_mode_token="xapp-xyz",
        user_id="U999",
        dm_channel_id="D888",
        timeout=60,
        claude_homes=["/home/user/.claude"],
    )
    original.save()
    loaded = SlackConfig.from_file()
    assert loaded.bot_token == "xoxb-abc"
    assert loaded.socket_mode_token == "xapp-xyz"
    assert loaded.user_id == "U999"
    assert loaded.dm_channel_id == "D888"
    assert loaded.timeout == 60
    assert loaded.claude_homes == ["/home/user/.claude"]


def test_slack_config_file_permissions(afk_home):
    cfg = SlackConfig(
        bot_token="xoxb-secret", socket_mode_token="x", user_id="U1", dm_channel_id="D1"
    )
    cfg.save()
    path = afk_home / "config.json"
    mode = stat.S_IMODE(os.stat(path).st_mode)
    assert mode == 0o600


def test_slack_config_is_valid():
    valid = SlackConfig(
        bot_token="xoxb-x", socket_mode_token="xapp-x", user_id="U1", dm_channel_id="D1"
    )
    assert valid.is_valid() is True

    invalid = SlackConfig(bot_token="xoxb-x")
    assert invalid.is_valid() is False


def test_load_state_missing(afk_home):
    state = load_state()
    assert state == {"enabled": []}


def test_state_roundtrip(afk_home):
    save_state({"enabled": ["sess-1", "sess-2"]})
    state = load_state()
    assert state["enabled"] == ["sess-1", "sess-2"]


def test_is_session_enabled_list(afk_home):
    save_state({"enabled": ["abc", "def"]})
    assert is_session_enabled("abc") is True
    assert is_session_enabled("def") is True


def test_is_session_enabled_all(afk_home):
    save_state({"enabled": "all"})
    assert is_session_enabled("anything") is True


def test_is_session_enabled_not_in_list(afk_home):
    save_state({"enabled": ["abc"]})
    assert is_session_enabled("xyz") is False


def test_setup_logging(afk_home):
    setup_logging()
    import logging

    logger = logging.getLogger("claude-afk")
    assert len(logger.handlers) > 0
    assert (afk_home / "logs" / "claude-afk.log").exists()


# --- session_exists ---


def test_session_exists_found(tmp_path):
    home = tmp_path / "home1"
    session_dir = home / "projects" / "myproject"
    session_dir.mkdir(parents=True)
    (session_dir / "sess-abc.jsonl").touch()
    assert session_exists("sess-abc", [str(home)]) is True


def test_session_exists_not_found(tmp_path):
    home = tmp_path / "home1"
    (home / "projects" / "myproject").mkdir(parents=True)
    assert session_exists("sess-missing", [str(home)]) is False


def test_session_exists_empty_homes():
    assert session_exists("sess-abc", []) is False


def test_session_exists_no_projects_dir(tmp_path):
    home = tmp_path / "home1"
    home.mkdir()
    assert session_exists("sess-abc", [str(home)]) is False


def test_session_exists_multiple_homes(tmp_path):
    home1 = tmp_path / "home1"
    home1.mkdir()
    home2 = tmp_path / "home2"
    session_dir = home2 / "projects" / "myproject"
    session_dir.mkdir(parents=True)
    (session_dir / "sess-xyz.jsonl").touch()
    assert session_exists("sess-xyz", [str(home1), str(home2)]) is True
