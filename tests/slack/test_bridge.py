"""Tests for slack.bridge — SlackBridge event filtering."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from claude_afk.config import SlackConfig
from claude_afk.slack.bridge import REPLY_ALLOW, REPLY_DENY, SlackBridge


def _make_bridge(config: SlackConfig, session_id: str = "test-sess") -> SlackBridge:
    """Create a SlackBridge without connecting (skip __enter__)."""
    with patch("claude_afk.slack.bridge.thread_state.load", return_value={}):
        bridge = SlackBridge(config, session_id)
    bridge.thread_ts = "1234.5678"
    bridge._bot_user_id = "BBOT"
    return bridge


def _make_request(event: dict) -> MagicMock:
    req = MagicMock()
    req.type = "events_api"
    req.payload = {"event": event}
    req.envelope_id = "env-123"
    return req


def test_handle_event_accepts_valid_reply():
    cfg = SlackConfig(
        bot_token="xoxb-x", socket_mode_token="xapp-x", user_id="U123", dm_channel_id="D456"
    )
    bridge = _make_bridge(cfg)

    event = {
        "type": "message",
        "user": "U123",
        "channel": "D456",
        "thread_ts": "1234.5678",
        "text": "approved",
    }
    req = _make_request(event)
    sm_client = MagicMock()

    bridge._handle_event(sm_client, req)
    assert bridge._reply_text == "approved"
    assert bridge._reply_event.is_set()


def test_handle_event_rejects_wrong_user():
    cfg = SlackConfig(
        bot_token="xoxb-x", socket_mode_token="xapp-x", user_id="U123", dm_channel_id="D456"
    )
    bridge = _make_bridge(cfg)

    event = {
        "type": "message",
        "user": "U999",
        "channel": "D456",
        "thread_ts": "1234.5678",
        "text": "hello",
    }
    req = _make_request(event)
    sm_client = MagicMock()

    bridge._handle_event(sm_client, req)
    assert not bridge._reply_event.is_set()


def test_handle_event_rejects_wrong_thread():
    cfg = SlackConfig(
        bot_token="xoxb-x", socket_mode_token="xapp-x", user_id="U123", dm_channel_id="D456"
    )
    bridge = _make_bridge(cfg)

    event = {
        "type": "message",
        "user": "U123",
        "channel": "D456",
        "thread_ts": "9999.0000",
        "text": "hello",
    }
    req = _make_request(event)
    sm_client = MagicMock()

    bridge._handle_event(sm_client, req)
    assert not bridge._reply_event.is_set()


def test_handle_event_rejects_bot():
    cfg = SlackConfig(
        bot_token="xoxb-x", socket_mode_token="xapp-x", user_id="U123", dm_channel_id="D456"
    )
    bridge = _make_bridge(cfg)

    event = {
        "type": "message",
        "user": "U123",
        "channel": "D456",
        "thread_ts": "1234.5678",
        "text": "bot msg",
        "bot_id": "B123",
    }
    req = _make_request(event)
    sm_client = MagicMock()

    bridge._handle_event(sm_client, req)
    assert not bridge._reply_event.is_set()


# --- Reaction handling ---


def test_handle_reaction_thumbsup_allows():
    cfg = SlackConfig(
        bot_token="xoxb-x", socket_mode_token="xapp-x", user_id="U123", dm_channel_id="D456"
    )
    bridge = _make_bridge(cfg)
    bridge._last_post_ts = "msg-ts-001"

    event = {
        "type": "reaction_added",
        "user": "U123",
        "reaction": "+1",
        "item": {"type": "message", "channel": "D456", "ts": "msg-ts-001"},
    }
    req = _make_request(event)
    sm_client = MagicMock()

    bridge._handle_event(sm_client, req)
    assert bridge._reply_text == REPLY_ALLOW
    assert bridge._reply_event.is_set()


def test_handle_reaction_thumbsdown_denies():
    cfg = SlackConfig(
        bot_token="xoxb-x", socket_mode_token="xapp-x", user_id="U123", dm_channel_id="D456"
    )
    bridge = _make_bridge(cfg)
    bridge._last_post_ts = "msg-ts-001"

    event = {
        "type": "reaction_added",
        "user": "U123",
        "reaction": "x",
        "item": {"type": "message", "channel": "D456", "ts": "msg-ts-001"},
    }
    req = _make_request(event)
    sm_client = MagicMock()

    bridge._handle_event(sm_client, req)
    assert bridge._reply_text == REPLY_DENY
    assert bridge._reply_event.is_set()


def test_handle_reaction_wrong_message_ignored():
    cfg = SlackConfig(
        bot_token="xoxb-x", socket_mode_token="xapp-x", user_id="U123", dm_channel_id="D456"
    )
    bridge = _make_bridge(cfg)
    bridge._last_post_ts = "msg-ts-001"

    event = {
        "type": "reaction_added",
        "user": "U123",
        "reaction": "+1",
        "item": {"type": "message", "channel": "D456", "ts": "old-msg-999"},
    }
    req = _make_request(event)
    sm_client = MagicMock()

    bridge._handle_event(sm_client, req)
    assert not bridge._reply_event.is_set()


def test_handle_reaction_wrong_user_ignored():
    cfg = SlackConfig(
        bot_token="xoxb-x", socket_mode_token="xapp-x", user_id="U123", dm_channel_id="D456"
    )
    bridge = _make_bridge(cfg)
    bridge._last_post_ts = "msg-ts-001"

    event = {
        "type": "reaction_added",
        "user": "U999",
        "reaction": "+1",
        "item": {"type": "message", "channel": "D456", "ts": "msg-ts-001"},
    }
    req = _make_request(event)
    sm_client = MagicMock()

    bridge._handle_event(sm_client, req)
    assert not bridge._reply_event.is_set()


def test_handle_reaction_unknown_emoji_ignored():
    cfg = SlackConfig(
        bot_token="xoxb-x", socket_mode_token="xapp-x", user_id="U123", dm_channel_id="D456"
    )
    bridge = _make_bridge(cfg)
    bridge._last_post_ts = "msg-ts-001"

    event = {
        "type": "reaction_added",
        "user": "U123",
        "reaction": "eyes",
        "item": {"type": "message", "channel": "D456", "ts": "msg-ts-001"},
    }
    req = _make_request(event)
    sm_client = MagicMock()

    bridge._handle_event(sm_client, req)
    assert not bridge._reply_event.is_set()


# --- Post ---


@patch("claude_afk.slack.bridge.thread_state")
def test_post_creates_thread(mock_thread_state):
    mock_thread_state.load.return_value = {}

    cfg = SlackConfig(
        bot_token="xoxb-x", socket_mode_token="xapp-x", user_id="U123", dm_channel_id="D456"
    )
    bridge = SlackBridge(cfg, "test-sess")
    bridge._web_client = MagicMock()
    bridge._web_client.chat_postMessage.return_value = {"ok": True, "ts": "new-ts-123"}

    result = bridge.post("Hello!")
    assert result is True
    assert bridge.thread_ts == "new-ts-123"
    mock_thread_state.save.assert_called_once_with("test-sess", "new-ts-123")
