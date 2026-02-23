"""Tests for slack.bridge — SlackBridge event filtering and concurrency."""

from __future__ import annotations

import fcntl
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


_CFG = SlackConfig(
    bot_token="xoxb-x", socket_mode_token="xapp-x", user_id="U123", dm_channel_id="D456"
)


# --- Thread reply handling ---


def test_handle_event_accepts_valid_reply():
    bridge = _make_bridge(_CFG)

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
    bridge = _make_bridge(_CFG)

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
    bridge = _make_bridge(_CFG)

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
    # Must NOT ack — Slack should retry to the correct connection
    sm_client.send_socket_mode_response.assert_not_called()


def test_handle_event_rejects_bot():
    bridge = _make_bridge(_CFG)

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
    bridge = _make_bridge(_CFG)
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
    bridge = _make_bridge(_CFG)
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


def test_handle_reaction_wrong_message_not_acked():
    """Reactions on other sessions' messages must NOT be acked."""
    bridge = _make_bridge(_CFG)
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
    # Critical: must NOT ack so Slack retries to the correct connection
    sm_client.send_socket_mode_response.assert_not_called()


def test_handle_reaction_wrong_user_ignored():
    bridge = _make_bridge(_CFG)
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
    bridge = _make_bridge(_CFG)
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

    bridge = SlackBridge(_CFG, "test-sess")
    bridge._web_client = MagicMock()
    bridge._web_client.chat_postMessage.return_value = {"ok": True, "ts": "new-ts-123"}

    result = bridge.post("Hello!")
    assert result is True
    assert bridge.thread_ts == "new-ts-123"
    mock_thread_state.save.assert_called_once_with("test-sess", "new-ts-123")


# --- Global lock + mode selection ---


@patch("claude_afk.slack.bridge.thread_state")
@patch("claude_afk.slack.bridge.SocketModeClient")
def test_enter_acquires_lock_socket_mode(mock_sm_cls, mock_thread_state, tmp_path, monkeypatch):
    """When SM lock is available, bridge uses socket mode."""
    import claude_afk.config as cfg

    monkeypatch.setattr(cfg, "AFK_HOME", tmp_path)
    monkeypatch.setattr(cfg, "BRIDGE_LOCK_PATH", tmp_path / "bridge" / "sm.lock")

    mock_thread_state.load.return_value = {}
    mock_sm_cls.return_value = MagicMock()

    bridge = SlackBridge(_CFG, "test-sess")
    bridge._web_client = MagicMock()
    bridge._web_client.auth_test.return_value = {"ok": True, "user_id": "BBOT"}

    bridge.__enter__()
    try:
        assert bridge._mode == "socket"
        assert bridge._sm_client is not None
        assert bridge._lock_fd is not None
    finally:
        bridge.__exit__(None, None, None)


@patch("claude_afk.slack.bridge.thread_state")
def test_enter_falls_back_to_poll_mode(mock_thread_state, tmp_path, monkeypatch):
    """When SM lock is held by another process, bridge falls back to poll mode."""
    import claude_afk.config as cfg

    monkeypatch.setattr(cfg, "AFK_HOME", tmp_path)
    lock_path = tmp_path / "bridge" / "sm.lock"
    monkeypatch.setattr(cfg, "BRIDGE_LOCK_PATH", lock_path)
    (tmp_path / "bridge").mkdir(parents=True, exist_ok=True)

    # Simulate another process holding the lock
    held_fd = open(lock_path, "w")  # noqa: SIM115
    fcntl.flock(held_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)

    mock_thread_state.load.return_value = {}

    bridge = SlackBridge(_CFG, "test-sess")
    bridge._web_client = MagicMock()
    bridge._web_client.auth_test.return_value = {"ok": True, "user_id": "BBOT"}

    bridge.__enter__()
    try:
        assert bridge._mode == "poll"
        assert bridge._sm_client is None
        assert bridge._lock_fd is None
    finally:
        bridge.__exit__(None, None, None)
        fcntl.flock(held_fd, fcntl.LOCK_UN)
        held_fd.close()


# --- Poll-based reply methods ---


def test_poll_thread_replies_finds_reply():
    bridge = _make_bridge(_CFG)
    bridge._last_post_ts = "1234.9999"

    bridge._web_client = MagicMock()
    bridge._web_client.conversations_replies.return_value = {
        "ok": True,
        "messages": [
            # Bot's own message (should be skipped)
            {"user": "BBOT", "ts": "1234.9999", "text": "bot msg"},
            # Valid human reply
            {"user": "U123", "ts": "1235.0001", "text": "go ahead"},
        ],
    }

    result = bridge._poll_thread_replies()
    assert result == "go ahead"


def test_poll_thread_replies_skips_stale():
    bridge = _make_bridge(_CFG)
    bridge._last_post_ts = "1234.9999"

    bridge._web_client = MagicMock()
    bridge._web_client.conversations_replies.return_value = {
        "ok": True,
        "messages": [
            # Message older than bot's post (stale)
            {"user": "U123", "ts": "1234.5000", "text": "old msg"},
        ],
    }

    result = bridge._poll_thread_replies()
    assert result is None


def test_poll_thread_replies_skips_wrong_user():
    bridge = _make_bridge(_CFG)
    bridge._last_post_ts = "1234.9999"

    bridge._web_client = MagicMock()
    bridge._web_client.conversations_replies.return_value = {
        "ok": True,
        "messages": [
            {"user": "U999", "ts": "1235.0001", "text": "intruder"},
        ],
    }

    result = bridge._poll_thread_replies()
    assert result is None


def test_poll_thread_replies_handles_api_error():
    bridge = _make_bridge(_CFG)
    bridge._last_post_ts = "1234.9999"

    bridge._web_client = MagicMock()
    bridge._web_client.conversations_replies.side_effect = Exception("rate limited")

    result = bridge._poll_thread_replies()
    assert result is None


def test_poll_reactions_finds_allow():
    bridge = _make_bridge(_CFG)
    bridge._last_post_ts = "msg-ts-001"

    bridge._web_client = MagicMock()
    bridge._web_client.reactions_get.return_value = {
        "ok": True,
        "message": {
            "reactions": [
                {"name": "+1", "users": ["U123"], "count": 1},
            ],
        },
    }

    result = bridge._poll_reactions()
    assert result == REPLY_ALLOW


def test_poll_reactions_finds_deny():
    bridge = _make_bridge(_CFG)
    bridge._last_post_ts = "msg-ts-001"

    bridge._web_client = MagicMock()
    bridge._web_client.reactions_get.return_value = {
        "ok": True,
        "message": {
            "reactions": [
                {"name": "thumbsdown", "users": ["U123"], "count": 1},
            ],
        },
    }

    result = bridge._poll_reactions()
    assert result == REPLY_DENY


def test_poll_reactions_ignores_wrong_user():
    bridge = _make_bridge(_CFG)
    bridge._last_post_ts = "msg-ts-001"

    bridge._web_client = MagicMock()
    bridge._web_client.reactions_get.return_value = {
        "ok": True,
        "message": {
            "reactions": [
                {"name": "+1", "users": ["U999"], "count": 1},
            ],
        },
    }

    result = bridge._poll_reactions()
    assert result is None


def test_poll_reactions_ignores_unknown_emoji():
    bridge = _make_bridge(_CFG)
    bridge._last_post_ts = "msg-ts-001"

    bridge._web_client = MagicMock()
    bridge._web_client.reactions_get.return_value = {
        "ok": True,
        "message": {
            "reactions": [
                {"name": "eyes", "users": ["U123"], "count": 1},
            ],
        },
    }

    result = bridge._poll_reactions()
    assert result is None


def test_poll_reactions_handles_api_error():
    bridge = _make_bridge(_CFG)
    bridge._last_post_ts = "msg-ts-001"

    bridge._web_client = MagicMock()
    bridge._web_client.reactions_get.side_effect = Exception("rate limited")

    result = bridge._poll_reactions()
    assert result is None


def test_poll_reactions_no_last_post():
    bridge = _make_bridge(_CFG)
    bridge._last_post_ts = None

    result = bridge._poll_reactions()
    assert result is None


def test_wait_for_reply_poll_timeout():
    """Poll mode respects timeout and returns None."""
    cfg = SlackConfig(
        bot_token="xoxb-x",
        socket_mode_token="xapp-x",
        user_id="U123",
        dm_channel_id="D456",
        timeout=1,
    )
    bridge = _make_bridge(cfg)
    bridge._mode = "poll"
    bridge._last_post_ts = "msg-ts-001"

    bridge._web_client = MagicMock()
    bridge._web_client.conversations_replies.return_value = {"ok": True, "messages": []}
    bridge._web_client.reactions_get.return_value = {"ok": True, "message": {"reactions": []}}

    result = bridge.wait_for_reply()
    assert result is None


def test_wait_for_reply_poll_finds_reply():
    """Poll mode returns when a reply is found."""
    cfg = SlackConfig(
        bot_token="xoxb-x",
        socket_mode_token="xapp-x",
        user_id="U123",
        dm_channel_id="D456",
        timeout=10,
    )
    bridge = _make_bridge(cfg)
    bridge._mode = "poll"
    bridge._last_post_ts = "1234.9999"

    bridge._web_client = MagicMock()
    bridge._web_client.conversations_replies.return_value = {
        "ok": True,
        "messages": [
            {"user": "U123", "ts": "1235.0001", "text": "looks good"},
        ],
    }

    result = bridge.wait_for_reply()
    assert result == "looks good"
