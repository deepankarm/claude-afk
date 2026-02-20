"""Stop hook handler.

When Claude stops, posts the last assistant message to Slack DM and waits
for a human reply. If a reply arrives, blocks the stop and feeds the
reply back to Claude as a continuation prompt.
"""

from __future__ import annotations

import json
import logging
import os
import sys
import time

from claude_afk.config import SlackConfig, is_session_enabled, setup_logging
from claude_afk.slack.bridge import SlackBridge
from claude_afk.slack.formatting import md_to_mrkdwn, truncate
from claude_afk.transcript import get_last_assistant_message, get_session_name

log = logging.getLogger("claude-afk.hooks.stop")


def run(data: dict, config: SlackConfig) -> None:
    session_id = data.get("session_id", "unknown")
    short_id = session_id[:8]
    cwd = data.get("cwd", "")
    project = os.path.basename(cwd) if cwd else "unknown"
    transcript_path = data.get("transcript_path", "")

    # Small delay to let Claude flush the transcript to disk
    time.sleep(1)

    assistant_msg = get_last_assistant_message(transcript_path)
    session_name = get_session_name(transcript_path)

    # Build header for new threads
    header_lines = [
        ":white_check_mark: *Claude finished*",
        f"> *Session ID:* `{short_id}`",
    ]
    if session_name:
        first_line = session_name.split("\n")[0].strip()
        header_lines.append(f"> *Session name:* {first_line}")
    header_lines.append(f"> *Project:* `{project}`")
    header_lines.append("\n> Reply to this thread to continue the session.")
    header = "\n".join(header_lines)

    # Build message body
    if assistant_msg:
        body = truncate(md_to_mrkdwn(assistant_msg))
    else:
        body = "_Claude finished (no text response)_"

    log.debug("stop connecting to Slack session=%s project=%s", short_id, project)

    with SlackBridge(config, session_id) as bridge:
        if bridge.thread_ts:
            bridge.post(body)
        else:
            bridge.post(body, header=header)

        log.debug("stop waiting for reply session=%s", short_id)
        reply = bridge.wait_for_reply()

        if reply is not None:
            log.debug("stop got reply session=%s reply=%r", short_id, reply[:100])
            result = {
                "decision": "block",
                "reason": f"User replied from Slack: {reply}",
            }
            print(json.dumps(result))
        else:
            log.debug("stop timed out session=%s", short_id)


def main() -> None:
    setup_logging()
    try:
        data = json.load(sys.stdin)
    except json.JSONDecodeError:
        data = {}

    session_id = data.get("session_id", "")
    log.debug("stop hook fired session=%s", session_id)

    if not session_id or not is_session_enabled(session_id):
        log.debug("session not enabled, skipping")
        sys.exit(0)

    config = SlackConfig.from_file()
    if not config.is_valid():
        log.debug("config invalid, skipping")
        sys.exit(0)

    run(data, config)
