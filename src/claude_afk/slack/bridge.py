"""Bidirectional Slack bridge via Socket Mode.

Provides a context manager that handles the common pattern shared by
stop and pretooluse hooks: connect to Slack via Socket Mode, post messages
in a persistent DM thread, and wait for verified human replies.

Concurrency: Only one bridge at a time uses Socket Mode (enforced by a
global file lock). Additional bridges fall back to polling the Web API,
preventing cross-session event routing issues.
"""

from __future__ import annotations

import contextlib
import fcntl
import logging
import threading
import time

from slack_sdk import WebClient
from slack_sdk.socket_mode import SocketModeClient
from slack_sdk.socket_mode.request import SocketModeRequest
from slack_sdk.socket_mode.response import SocketModeResponse

from claude_afk.config import SlackConfig
from claude_afk.slack import thread as thread_state

log = logging.getLogger("claude-afk.slack.bridge")

# Emoji reactions mapped to allow/deny - lets users react instead of typing.
_REACTION_ALLOW = {"+1", "thumbsup", "white_check_mark", "heavy_check_mark"}
_REACTION_DENY = {"-1", "thumbsdown", "x", "no_entry_sign", "no_entry"}
_REACTION_ALWAYS_ALLOW = {
    "fast_forward",
    "black_right_pointing_double_triangle_with_vertical_bar",
}

# Sentinel values returned by wait_for_reply() for reactions.
# Distinct from any text a user could type.
REPLY_ALLOW = "__REACTION_ALLOW__"
REPLY_DENY = "__REACTION_DENY__"
REPLY_ALWAYS_ALLOW = "__REACTION_ALWAYS_ALLOW__"


class SlackBridge:
    """Context manager for bidirectional Slack communication via DM.

    Posts to a DM channel and only accepts replies from the verified user.

    Usage::

        with SlackBridge(config, session_id) as bridge:
            bridge.post("Hello from Claude!", header="Session started")
            reply = bridge.wait_for_reply()
    """

    _POLL_INTERVAL = 3  # seconds between polling attempts

    def __init__(self, config: SlackConfig, session_id: str) -> None:
        self._config = config
        self._session_id = session_id

        self._web_client = WebClient(token=config.bot_token)
        self._sm_client: SocketModeClient | None = None
        self._bot_user_id: str | None = None

        # Thread state — loaded from disk so we continue in the same Slack thread
        state = thread_state.load(session_id)
        self.thread_ts: str | None = state.get("thread_ts")
        self._needs_header = not self.thread_ts

        # Reply synchronization (socket mode)
        self._reply_event = threading.Event()
        self._reply_text: str | None = None
        self._last_post_ts: str | None = None  # reject replies older than this

        # Connection mode: "socket" (holds global lock) or "poll" (fallback)
        self._mode: str = "socket"
        self._lock_fd = None

    def __enter__(self) -> SlackBridge:
        from claude_afk.config import BRIDGE_LOCK_PATH, ensure_home

        ensure_home()

        auth = self._web_client.auth_test()
        if auth.get("ok"):
            self._bot_user_id = auth.get("user_id")
            log.debug("authenticated as bot user %s", self._bot_user_id)

        # Try to acquire the global Socket Mode lock (non-blocking).
        # Only one bridge at a time should use Socket Mode.
        self._lock_fd = open(BRIDGE_LOCK_PATH, "w")
        try:
            fcntl.flock(self._lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            self._mode = "socket"
            log.debug("acquired SM lock, using socket mode session=%s", self._session_id)
        except (BlockingIOError, OSError):
            self._mode = "poll"
            self._lock_fd.close()
            self._lock_fd = None
            log.debug(
                "SM lock held by another bridge, using poll mode session=%s",
                self._session_id,
            )

        if self._mode == "socket":
            self._sm_client = SocketModeClient(
                app_token=self._config.socket_mode_token,
                web_client=self._web_client,
            )
            self._sm_client.socket_mode_request_listeners.append(self._handle_event)
            self._sm_client.connect()
            log.debug("socket mode connected session=%s", self._session_id)

        return self

    def __exit__(self, *exc) -> None:
        if self._sm_client:
            self._sm_client.disconnect()
            log.debug("socket mode disconnected session=%s", self._session_id)

        if self._lock_fd:
            with contextlib.suppress(OSError):
                fcntl.flock(self._lock_fd, fcntl.LOCK_UN)
            self._lock_fd.close()
            self._lock_fd = None
            log.debug("SM lock released session=%s", self._session_id)

    def post(self, text: str, header: str | None = None) -> bool:
        """Post a message to the DM, creating or continuing a thread.

        Args:
            text: The message body.
            header: Optional header prepended to the first message in a new thread.

        Returns:
            True if the message was posted successfully.
        """
        if self._needs_header and header:
            text = header + "\n\n" + text
            self._needs_header = False

        kwargs: dict = {"channel": self._config.dm_channel_id, "text": text}
        if self.thread_ts:
            kwargs["thread_ts"] = self.thread_ts

        resp = self._web_client.chat_postMessage(**kwargs)
        if not resp.get("ok"):
            log.warning("chat_postMessage failed: %s", resp.get("error"))
            return False

        if not self.thread_ts:
            self.thread_ts = resp.get("ts")
            log.debug("new thread started ts=%s", self.thread_ts)

        self._last_post_ts = resp.get("ts")
        thread_state.save(self._session_id, self.thread_ts)
        return True

    def wait_for_reply(self) -> str | None:
        """Block until the verified user replies in the thread, or timeout.

        Uses Socket Mode if we hold the global lock, otherwise polls the
        Slack Web API.

        Returns:
            The reply text, or None if timed out.
        """
        if self._mode == "socket":
            return self._wait_for_reply_socket()
        return self._wait_for_reply_poll()

    # -- Socket Mode waiting (original behavior) --

    def _wait_for_reply_socket(self) -> str | None:
        """Wait using Socket Mode event listener."""
        self._reply_event.clear()
        self._reply_text = None
        log.debug(
            "waiting for reply (socket) timeout=%ss thread=%s",
            self._config.timeout,
            self.thread_ts,
        )
        got_reply = self._reply_event.wait(timeout=self._config.timeout)
        if got_reply and self._reply_text is not None:
            log.debug("received reply: %r", self._reply_text[:100])
            return self._reply_text
        log.debug("reply timed out after %ss", self._config.timeout)
        return None

    def _handle_event(
        self,
        sm_client: SocketModeClient,
        req: SocketModeRequest,
    ) -> None:
        if req.type != "events_api":
            sm_client.send_socket_mode_response(SocketModeResponse(envelope_id=req.envelope_id))
            return

        event = req.payload.get("event", {})
        event_type = event.get("type")

        is_thread_reply = (
            event_type == "message"
            and not event.get("subtype")
            and event.get("thread_ts")
        )
        is_reaction = event_type == "reaction_added"

        # Don't ack thread replies meant for another session — Slack will
        # retry delivery to the connection that owns that thread.
        if is_thread_reply and event.get("thread_ts") != self.thread_ts:
            return

        # Don't ack reactions on messages we didn't post — Slack will
        # retry delivery to the connection that owns that message.
        if is_reaction:
            item = event.get("item", {})
            if item.get("ts") != self._last_post_ts:
                return

        # This event belongs to us (or is irrelevant) — ack it
        sm_client.send_socket_mode_response(SocketModeResponse(envelope_id=req.envelope_id))

        if is_thread_reply:
            self._handle_thread_reply(event)
        elif is_reaction:
            self._handle_reaction(event)

    def _handle_thread_reply(self, event: dict) -> None:
        """Process a validated thread reply."""
        if event.get("channel") != self._config.dm_channel_id:
            return
        if event.get("bot_id"):
            return
        if self._bot_user_id and event.get("user") == self._bot_user_id:
            return
        if self._config.user_id and event.get("user") != self._config.user_id:
            log.debug("ignoring reply from non-verified user %s", event.get("user"))
            return

        # Ignore stale messages sent before the bot's latest post
        msg_ts = event.get("ts", "")
        if self._last_post_ts and msg_ts <= self._last_post_ts:
            log.debug(
                "ignoring stale message ts=%s (bot posted at %s)", msg_ts, self._last_post_ts
            )
            return

        self._reply_text = event.get("text", "")
        self._reply_event.set()

    def _handle_reaction(self, event: dict) -> None:
        """Process an emoji reaction on our last posted message."""
        item = event.get("item", {})

        # Only reactions on our last posted message
        if item.get("channel") != self._config.dm_channel_id:
            return
        if not self._last_post_ts or item.get("ts") != self._last_post_ts:
            return

        # Verify user
        if self._config.user_id and event.get("user") != self._config.user_id:
            return

        reaction = event.get("reaction", "")
        if reaction in _REACTION_ALLOW:
            log.debug("reaction %s -> allow", reaction)
            self._reply_text = REPLY_ALLOW
            self._reply_event.set()
        elif reaction in _REACTION_DENY:
            log.debug("reaction %s -> deny", reaction)
            self._reply_text = REPLY_DENY
            self._reply_event.set()
        elif reaction in _REACTION_ALWAYS_ALLOW:
            log.debug("reaction %s -> always_allow", reaction)
            self._reply_text = REPLY_ALWAYS_ALLOW
            self._reply_event.set()

    # -- Poll-based waiting (fallback when SM lock is held) --

    def _wait_for_reply_poll(self) -> str | None:
        """Wait by polling Slack Web API for new thread replies and reactions."""
        log.debug(
            "waiting for reply (poll) timeout=%ss thread=%s",
            self._config.timeout,
            self.thread_ts,
        )
        deadline = time.monotonic() + self._config.timeout

        while time.monotonic() < deadline:
            reply = self._poll_thread_replies()
            if reply is not None:
                log.debug("poll: received reply: %r", reply[:100])
                return reply

            reaction = self._poll_reactions()
            if reaction is not None:
                log.debug("poll: received reaction: %r", reaction)
                return reaction

            remaining = deadline - time.monotonic()
            if remaining <= 0:
                break
            time.sleep(min(self._POLL_INTERVAL, remaining))

        log.debug("poll: reply timed out after %ss", self._config.timeout)
        return None

    def _poll_thread_replies(self) -> str | None:
        """Poll conversations.replies for new thread messages."""
        if not self.thread_ts:
            return None
        try:
            resp = self._web_client.conversations_replies(
                channel=self._config.dm_channel_id,
                ts=self.thread_ts,
                oldest=self._last_post_ts or self.thread_ts,
                limit=10,
            )
        except Exception:
            log.debug("poll: conversations.replies failed", exc_info=True)
            return None

        if not resp.get("ok"):
            return None

        for msg in resp.get("messages", []):
            if msg.get("subtype"):
                continue
            if msg.get("bot_id"):
                continue
            if self._bot_user_id and msg.get("user") == self._bot_user_id:
                continue
            if self._config.user_id and msg.get("user") != self._config.user_id:
                continue
            msg_ts = msg.get("ts", "")
            if self._last_post_ts and msg_ts <= self._last_post_ts:
                continue
            return msg.get("text", "")

        return None

    def _poll_reactions(self) -> str | None:
        """Poll reactions.get for emoji reactions on our last posted message."""
        if not self._last_post_ts:
            return None
        try:
            resp = self._web_client.reactions_get(
                channel=self._config.dm_channel_id,
                timestamp=self._last_post_ts,
            )
        except Exception:
            log.debug("poll: reactions.get failed", exc_info=True)
            return None

        if not resp.get("ok"):
            return None

        message = resp.get("message", {})
        for reaction_obj in message.get("reactions", []):
            name = reaction_obj.get("name", "")
            users = reaction_obj.get("users", [])

            if self._config.user_id and self._config.user_id not in users:
                continue

            if name in _REACTION_ALLOW:
                return REPLY_ALLOW
            if name in _REACTION_DENY:
                return REPLY_DENY
            if name in _REACTION_ALWAYS_ALLOW:
                return REPLY_ALWAYS_ALLOW

        return None
