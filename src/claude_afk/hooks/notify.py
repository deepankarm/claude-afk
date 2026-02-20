"""Notification hook handler.

Sends one-way Slack DM notifications when Claude Code needs attention
or completes a task. Uses the bot token to post directly to the DM channel
(no Socket Mode or webhook needed).
"""

from __future__ import annotations

import json
import logging
import os
import sys

from slack_sdk import WebClient

from claude_afk.config import SlackConfig, is_session_enabled, setup_logging

log = logging.getLogger("claude-afk.hooks.notify")


def _format_stop(data: dict) -> str:
    cwd = data.get("cwd", "unknown directory")
    project = os.path.basename(cwd) if cwd else "unknown"
    stop_reason = data.get("stop_reason", "")
    message = f":white_check_mark: *Claude Code finished*\n*Project:* `{project}`"
    if stop_reason:
        message += f"\n*Reason:* {stop_reason}"
    return message


def _format_notification(data: dict) -> str:
    cwd = data.get("cwd", "unknown directory")
    project = os.path.basename(cwd) if cwd else "unknown"
    body = data.get("message", "")
    message = f":bell: *Claude Code needs attention*\n*Project:* `{project}`"
    if body:
        message += f"\n>{body}"
    return message


def run(data: dict, config: SlackConfig, event: str) -> bool:
    if event == "stop":
        message = _format_stop(data)
    elif event == "notification":
        if data.get("notification_type") == "idle_prompt":
            return True
        message = _format_notification(data)
    else:
        return False

    client = WebClient(token=config.bot_token)
    try:
        resp = client.chat_postMessage(channel=config.dm_channel_id, text=message)
        ok = resp.get("ok", False)
        log.debug("notify posted event=%s ok=%s", event, ok)
        return ok
    except Exception:
        log.exception("Failed to send Slack notification")
        return False


def main(event: str = "notification") -> None:
    setup_logging()
    try:
        data = json.load(sys.stdin)
    except json.JSONDecodeError:
        data = {}

    session_id = data.get("session_id", "")
    log.debug("notify hook fired session=%s event=%s", session_id, event)

    if not session_id or not is_session_enabled(session_id):
        log.debug("session not enabled, skipping")
        sys.exit(0)

    config = SlackConfig.from_file()
    if not config.is_valid():
        log.debug("config invalid, skipping")
        sys.exit(0)

    success = run(data, config, event)
    sys.exit(0 if success else 1)
