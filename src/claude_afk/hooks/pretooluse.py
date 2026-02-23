"""PreToolUse hook handler.

Routes tool permission prompts and AskUserQuestion calls to Slack DM.
Respects CC's built-in permission rules — if a tool already has an
allow/deny rule, lets CC handle it without a Slack round-trip.

Uses file locking to serialize parallel hook invocations that would
otherwise race for Slack replies.
"""

from __future__ import annotations

import fcntl
import json
import logging
import sys

from claude_afk.config import SlackConfig, is_session_enabled, setup_logging
from claude_afk.permissions import (
    TOOL_POLICIES,
    Decision,
    ToolPolicy,
    build_session_rule,
    check_session_permission,
    get_tool_input_value,
    is_sensitive_path,
    load_cc_permission_rules,
    save_session_permission,
    tool_has_cc_rule,
)
from claude_afk.slack.bridge import SlackBridge
from claude_afk.slack.formatting import format_single_question, format_tool_permission

log = logging.getLogger("claude-afk.hooks.pretooluse")

_ALLOW_WORDS = {"allow", "yes", "y", "approve", "ok", "lgtm", "go", "proceed", "sure", "yep"}
_DENY_WORDS = {"deny", "no", "n", "reject", "block", "stop", "nope", "cancel"}


def parse_permission_reply(text: str) -> Decision:
    """Parse allow/deny from a Slack reply."""
    normalized = text.strip().lower().rstrip("!.,")
    if normalized in _ALLOW_WORDS:
        return Decision.ALLOW
    if normalized in _DENY_WORDS:
        return Decision.DENY
    return Decision.UNCLEAR


def resolve_question_answer(reply: str, question: dict) -> str:
    """Map a numbered reply back to an option label when possible."""
    reply = reply.strip()
    options = question.get("options", [])
    multi = question.get("multiSelect", False)

    try:
        num = int(reply)
        if 1 <= num <= len(options):
            return options[num - 1].get("label", reply)
    except ValueError:
        pass

    if multi and "," in reply:
        parts = [p.strip() for p in reply.split(",")]
        labels: list[str] = []
        for p in parts:
            try:
                num = int(p)
                if 1 <= num <= len(options):
                    labels.append(options[num - 1].get("label", p))
                else:
                    labels.append(p)
            except ValueError:
                labels.append(p)
        if labels:
            return ", ".join(labels)

    return reply


def _emit(decision: Decision, reason: str) -> None:
    """Print a PreToolUse hook response to stdout."""
    result = {
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": decision,
            "permissionDecisionReason": reason,
        },
    }
    print(json.dumps(result))


def _handle_ask_user_question(
    bridge: SlackBridge,
    questions: list[dict],
) -> None:
    """Post questions one at a time, collect answers, deny with combined response."""
    total = len(questions)
    answers: list[str] = []

    for qi, q in enumerate(questions):
        text = format_single_question(q, qi + 1, total)
        if not bridge.post(text):
            return

        reply = bridge.wait_for_reply()
        if reply is None:
            return

        answer = resolve_question_answer(reply, q)
        answers.append(answer)

    if total == 1:
        combined = answers[0]
    else:
        parts: list[str] = []
        for qi, (q, a) in enumerate(zip(questions, answers, strict=True)):
            header = q.get("header", f"Question {qi + 1}")
            parts.append(f"{header}: {a}")
        combined = "; ".join(parts)

    confirm_parts = [f":white_check_mark: *All {total} answers received*\n"] if total > 1 else []
    for qi, (q, a) in enumerate(zip(questions, answers, strict=True)):
        hdr = q.get("header", f"Q{qi + 1}")
        confirm_parts.append(f"*{hdr}:* {a}")
    bridge.post("\n".join(confirm_parts))

    log.debug("question answers combined=%r", combined)
    _emit(Decision.DENY, f"User replied from Slack: {combined}")


def _handle_permission(
    bridge: SlackBridge,
    tool_name: str,
    tool_input: dict,
    session_id: str,
) -> None:
    """Post permission prompt, wait for allow/deny reply."""
    text = format_tool_permission(tool_name, tool_input)
    if not bridge.post(text):
        return

    reply = bridge.wait_for_reply()
    if reply is None:
        return

    decision = parse_permission_reply(reply)

    log.debug("permission reply=%r decision=%s tool=%s", reply, decision, tool_name)

    if decision == Decision.ALLOW:
        _emit(Decision.ALLOW, "Approved via Slack")
    elif decision == Decision.DENY:
        _emit(Decision.DENY, f"Denied via Slack: {reply}")
    else:
        _emit(Decision.ALLOW, f"User said via Slack: {reply}")

    # Cache the decision for cacheable tools (e.g. Edit, sensitive Reads)
    effective = decision if decision != Decision.UNCLEAR else Decision.ALLOW
    rule = build_session_rule(tool_name, tool_input)
    if rule:
        save_session_permission(session_id, rule, effective)
        log.debug("cached session permission: %s -> %s", rule, effective)


def _check_auto_allow(tool_name: str, tool_input: dict) -> bool:
    """Return True if the tool should be silently auto-allowed."""
    policy = TOOL_POLICIES.get(tool_name, ToolPolicy.ALWAYS_ASK)
    if policy != ToolPolicy.AUTO_ALLOW:
        return False
    value = get_tool_input_value(tool_name, tool_input)
    return not is_sensitive_path(value)


def run(data: dict, config: SlackConfig) -> None:
    tool_name = data.get("tool_name", "")
    tool_input = data.get("tool_input", {})
    session_id = data.get("session_id", "unknown")

    cwd = data.get("cwd", "")
    cc_rules = load_cc_permission_rules(cwd)
    if tool_has_cc_rule(tool_name, tool_input, cc_rules):
        log.debug("tool %s matched CC rule, skipping Slack", tool_name)
        sys.exit(0)

    is_ask = tool_name == "AskUserQuestion"
    questions = tool_input.get("questions", []) if is_ask else []

    if is_ask and not questions:
        sys.exit(0)

    # Auto-allow safe tools (Read non-sensitive, Grep, Glob)
    if not is_ask and _check_auto_allow(tool_name, tool_input):
        log.debug("auto-allow %s (safe tool, non-sensitive)", tool_name)
        _emit(Decision.ALLOW, f"Auto-allowed ({tool_name})")
        return

    lock_path = f"/tmp/slack_bridge_{session_id}.lock"
    log.debug("acquiring lock %s", lock_path)
    with open(lock_path, "w") as lock_fd:
        fcntl.flock(lock_fd, fcntl.LOCK_EX)
        log.debug("lock acquired, connecting to Slack")

        # Check session cache inside the lock — parallel hooks may have
        # written a cache entry while we were waiting for the lock.
        cached = check_session_permission(session_id, tool_name, tool_input)
        if cached == Decision.ALLOW:
            log.debug("tool %s matched session allow rule, auto-approving", tool_name)
            _emit(Decision.ALLOW, "Auto-approved from session cache")
            return
        if cached == Decision.DENY:
            log.debug("tool %s matched session deny rule, auto-denying", tool_name)
            _emit(Decision.DENY, "Auto-denied from session cache")
            return

        try:
            with SlackBridge(config, session_id) as bridge:
                if is_ask:
                    _handle_ask_user_question(bridge, questions)
                else:
                    _handle_permission(bridge, tool_name, tool_input, session_id)
        finally:
            fcntl.flock(lock_fd, fcntl.LOCK_UN)
            log.debug("lock released")


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
    tool_name = data.get("tool_name", "")
    log.debug("pretooluse hook fired session=%s tool=%s", session_id, tool_name)

    if not session_id or not is_session_enabled(session_id):
        log.debug("session not enabled, skipping")
        sys.exit(0)

    config = SlackConfig.from_file()
    if not config.is_valid():
        log.debug("config invalid, skipping")
        sys.exit(0)

    run(data, config)
