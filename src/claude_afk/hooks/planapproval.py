"""PermissionRequest hook handler for ExitPlanMode.

When Claude exits plan mode, CC fires a PermissionRequest for
ExitPlanMode. This hook intercepts it, posts the plan to Slack,
and waits for the user to approve or request changes.

Approve → CC starts coding.
Deny (with feedback) → CC revises the plan and re-enters plan mode.
"""

from __future__ import annotations

import json
import logging
import sys

from claude_afk.config import SlackConfig, is_session_enabled, setup_logging
from claude_afk.hooks.pretooluse import parse_permission_reply
from claude_afk.permissions import Decision
from claude_afk.slack.bridge import SlackBridge
from claude_afk.slack.formatting import format_plan_approval

log = logging.getLogger("claude-afk.hooks.planapproval")


def _emit(behavior: str, message: str | None = None) -> None:
    """Print a PermissionRequest hook response to stdout."""
    decision: dict = {"behavior": behavior}
    if message:
        decision["message"] = message
    result = {
        "hookSpecificOutput": {
            "hookEventName": "PermissionRequest",
            "decision": decision,
        },
    }
    print(json.dumps(result))


def run(data: dict, config: SlackConfig) -> None:
    session_id = data.get("session_id", "unknown")
    tool_input = data.get("tool_input", {})

    plan = tool_input.get("plan", "")
    allowed_prompts = tool_input.get("allowedPrompts", [])

    if not plan and not allowed_prompts:
        log.debug("no plan content or prompts, auto-approving")
        _emit("allow")
        return

    text = format_plan_approval(plan, allowed_prompts or None)

    with SlackBridge(config, session_id) as bridge:
        if not bridge.post(text):
            log.warning("failed to post plan to Slack, auto-approving")
            _emit("allow")
            return

        reply = bridge.wait_for_reply()
        if reply is None:
            log.debug("plan approval timed out, auto-approving")
            _emit("allow")
            return

        decision = parse_permission_reply(reply)
        log.debug("plan reply=%r decision=%s", reply, decision)

        if decision == Decision.DENY:
            bridge.post(f":x: *Plan rejected.* Claude will revise.\n> {reply}")
            _emit("deny", f"User requested changes via Slack: {reply}")
        elif decision == Decision.ALLOW:
            bridge.post(":white_check_mark: *Plan approved.* Starting work.")
            _emit("allow")
        else:
            # Unclear reply → treat as feedback (deny with the reply text)
            bridge.post(
                f":speech_balloon: *Feedback sent.* Claude will revise.\n> {reply}"
            )
            _emit("deny", f"User feedback via Slack: {reply}")


def main() -> None:
    setup_logging()
    if sys.stdin.isatty():
        print(
            "Error: This hook reads JSON from stdin, not meant to be called directly.",
            file=sys.stderr,
        )
        sys.exit(1)
    try:
        data = json.load(sys.stdin)
    except json.JSONDecodeError:
        data = {}

    session_id = data.get("session_id", "")
    log.debug("planapproval hook fired session=%s", session_id)

    if not session_id or not is_session_enabled(session_id):
        log.debug("session not enabled, skipping")
        sys.exit(0)

    config = SlackConfig.from_file()
    if not config.is_valid():
        log.debug("config invalid, skipping")
        sys.exit(0)

    run(data, config)
