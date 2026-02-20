"""Shared fixtures for claude-afk tests."""

from __future__ import annotations

import pytest

from claude_afk import config
from claude_afk.config import SlackConfig


@pytest.fixture()
def afk_home(tmp_path, monkeypatch):
    """Point AFK_HOME to a temp directory and create the directory structure."""
    monkeypatch.setattr(config, "AFK_HOME", tmp_path)
    config.ensure_home()
    return tmp_path


@pytest.fixture()
def sample_config():
    """Return a valid SlackConfig for testing."""
    return SlackConfig(
        bot_token="xoxb-test",
        socket_mode_token="xapp-test",
        user_id="U123",
        dm_channel_id="D456",
        timeout=10,
    )
