"""Tests for hooks.notify — format functions and run() with mocked WebClient."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from claude_afk.config import SlackConfig
from claude_afk.hooks.notify import _format_notification, _format_stop, run


def test_format_stop():
    data = {"cwd": "/home/user/myproject", "stop_reason": "end_turn"}
    result = _format_stop(data)
    assert "myproject" in result
    assert "end_turn" in result
    assert "finished" in result


def test_format_notification():
    data = {"cwd": "/home/user/myproject", "message": "Need your input"}
    result = _format_notification(data)
    assert "myproject" in result
    assert "Need your input" in result
    assert "attention" in result


@patch("claude_afk.hooks.notify.WebClient")
def test_run_stop_success(mock_wc_cls):
    mock_client = MagicMock()
    mock_client.chat_postMessage.return_value = {"ok": True}
    mock_wc_cls.return_value = mock_client

    cfg = SlackConfig(
        bot_token="xoxb-x", socket_mode_token="xapp-x", user_id="U1", dm_channel_id="D1"
    )
    data = {"cwd": "/tmp/proj", "stop_reason": "done"}
    result = run(data, cfg, "stop")
    assert result is True
    mock_client.chat_postMessage.assert_called_once()


def test_run_notification_skip_idle():
    cfg = SlackConfig(
        bot_token="xoxb-x", socket_mode_token="xapp-x", user_id="U1", dm_channel_id="D1"
    )
    data = {"notification_type": "idle_prompt"}
    result = run(data, cfg, "notification")
    assert result is True


def test_run_unknown_event():
    cfg = SlackConfig(
        bot_token="xoxb-x", socket_mode_token="xapp-x", user_id="U1", dm_channel_id="D1"
    )
    result = run({}, cfg, "unknown_event")
    assert result is False
