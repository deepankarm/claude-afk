"""Bidirectional Slack bridge via Socket Mode.

Provides a context manager that handles the common pattern shared by
stop and pretooluse hooks: connect to Slack via Socket Mode, post messages
in a persistent DM thread, and wait for verified human replies.
"""

from __future__ import annotations

import logging
import threading

from slack_sdk import WebClient
from slack_sdk.socket_mode import SocketModeClient
from slack_sdk.socket_mode.request import SocketModeRequest
from slack_sdk.socket_mode.response import SocketModeResponse

from claude_afk.config import SlackConfig
from claude_afk.slack import thread as thread_state

log = logging.getLogger("claude-afk.slack.bridge")


class SlackBridge:
    """Context manager for bidirectional Slack communication via DM.

    Posts to a DM channel and only accepts replies from the verified user.

    Usage::

        with SlackBridge(config, session_id) as bridge:
            bridge.post("Hello from Claude!", header="Session started")
            reply = bridge.wait_for_reply()
    """

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

        # Reply synchronization
        self._reply_event = threading.Event()
        self._reply_text: str | None = None

    def __enter__(self) -> SlackBridge:
        auth = self._web_client.auth_test()
        if auth.get("ok"):
            self._bot_user_id = auth.get("user_id")
            log.debug("authenticated as bot user %s", self._bot_user_id)

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

        thread_state.save(self._session_id, self.thread_ts)
        return True

    def wait_for_reply(self) -> str | None:
        """Block until the verified user replies in the thread, or timeout.

        Returns:
            The reply text, or None if timed out.
        """
        self._reply_event.clear()
        self._reply_text = None
        log.debug("waiting for reply timeout=%ss thread=%s", self._config.timeout, self.thread_ts)
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
        # Always acknowledge to prevent retries
        sm_client.send_socket_mode_response(
            SocketModeResponse(envelope_id=req.envelope_id),
        )

        if req.type != "events_api":
            return

        event = req.payload.get("event", {})

        if event.get("type") != "message":
            return
        if event.get("subtype"):
            return
        if event.get("thread_ts") != self.thread_ts:
            return
        if event.get("channel") != self._config.dm_channel_id:
            return
        if event.get("bot_id"):
            return
        if self._bot_user_id and event.get("user") == self._bot_user_id:
            return
        if self._config.user_id and event.get("user") != self._config.user_id:
            log.debug("ignoring reply from non-verified user %s", event.get("user"))
            return

        self._reply_text = event.get("text", "")
        self._reply_event.set()
