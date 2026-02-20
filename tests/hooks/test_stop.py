"""Tests for hooks.stop — run() with mocked SlackBridge."""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

from claude_afk.config import SlackConfig
from claude_afk.hooks.stop import run


@patch("claude_afk.hooks.stop.time.sleep")
@patch("claude_afk.hooks.stop.SlackBridge")
@patch("claude_afk.hooks.stop.get_last_assistant_message", return_value="Done!")
@patch("claude_afk.hooks.stop.get_session_name", return_value="Fix bug")
def test_run_posts_and_blocks_on_reply(
    mock_name, mock_msg, mock_bridge_cls, mock_sleep, capsys
):
    bridge = MagicMock()
    bridge.thread_ts = None
    bridge.post.return_value = True
    bridge.wait_for_reply.return_value = "continue please"
    mock_bridge_cls.return_value.__enter__ = MagicMock(return_value=bridge)
    mock_bridge_cls.return_value.__exit__ = MagicMock(return_value=False)

    cfg = SlackConfig(
        bot_token="xoxb-x", socket_mode_token="xapp-x", user_id="U1", dm_channel_id="D1"
    )
    data = {"session_id": "sess-abc", "cwd": "/tmp/proj", "transcript_path": "/tmp/t.jsonl"}
    run(data, cfg)

    output = json.loads(capsys.readouterr().out.strip())
    assert output["decision"] == "block"
    assert "continue please" in output["reason"]


@patch("claude_afk.hooks.stop.time.sleep")
@patch("claude_afk.hooks.stop.SlackBridge")
@patch("claude_afk.hooks.stop.get_last_assistant_message", return_value="Done!")
@patch("claude_afk.hooks.stop.get_session_name", return_value="")
def test_run_timeout_no_output(mock_name, mock_msg, mock_bridge_cls, mock_sleep, capsys):
    bridge = MagicMock()
    bridge.thread_ts = "existing-ts"
    bridge.post.return_value = True
    bridge.wait_for_reply.return_value = None
    mock_bridge_cls.return_value.__enter__ = MagicMock(return_value=bridge)
    mock_bridge_cls.return_value.__exit__ = MagicMock(return_value=False)

    cfg = SlackConfig(
        bot_token="xoxb-x", socket_mode_token="xapp-x", user_id="U1", dm_channel_id="D1"
    )
    data = {"session_id": "sess-xyz", "cwd": "/tmp/proj", "transcript_path": "/tmp/t.jsonl"}
    run(data, cfg)

    captured = capsys.readouterr().out.strip()
    assert captured == ""
