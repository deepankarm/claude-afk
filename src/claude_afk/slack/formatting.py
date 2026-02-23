"""Slack message formatting utilities.

Converts Markdown to Slack mrkdwn, formats tool permission prompts
and AskUserQuestion messages for display in Slack.
"""

from __future__ import annotations

import json
import re

from claude_afk.config import MAX_SLACK_TEXT

# Markdown → Slack mrkdwn conversion patterns
# Adapted from https://github.com/fla9ua/markdown_to_mrkdwn
_MRKDWN_PATTERNS: list[tuple[re.Pattern, str]] = [
    # Task lists
    (re.compile(r"^(\s*)- \[([ ])\] (.+)", re.MULTILINE), r"\1• ☐ \3"),
    (re.compile(r"^(\s*)- \[([xX])\] (.+)", re.MULTILINE), r"\1• ☑ \3"),
    # Unordered lists
    (re.compile(r"^(\s*)- (.+)", re.MULTILINE), r"\1• \2"),
    # Images
    (re.compile(r"!\[.*?\]\((.+?)\)", re.MULTILINE), r"<\1>"),
    # Bold+italic (***text***) — must come before bold/italic
    (re.compile(r"(?<!\*)\*\*\*([^*\n]+?)\*\*\*(?!\*)", re.MULTILINE), r"*_\1_*"),
    # Italic (*text*) — must come BEFORE bold so *text* → _text_ first
    (re.compile(r"(?<!\*)\*([^*\n]+?)\*(?!\*)", re.MULTILINE), r"_\1_"),
    # Bold (**text** or __text__) — after italic, so **text** still intact
    (re.compile(r"(?<!\*)\*\*(.+?)\*\*(?!\*)", re.MULTILINE), r"*\1*"),
    (re.compile(r"__(.+?)__", re.MULTILINE), r"*\1*"),
    # Headers → bold
    (re.compile(r"^#{1,6} (.+?)\s*$", re.MULTILINE), r"*\1*"),
    # Links
    (re.compile(r"\[(.+?)\]\((.+?)\)", re.MULTILINE), r"<\2|\1>"),
    # Strikethrough
    (re.compile(r"~~(.+?)~~", re.MULTILINE), r"~\1~"),
    # Horizontal rules
    (re.compile(r"^(---|\*\*\*|___)$", re.MULTILINE), r"──────────"),
]

_TABLE_PATTERN = re.compile(
    r"^\|(.+)\|\s*$\n^\|[-:| ]+\|\s*$(\n^\|.+\|\s*$)*",
    re.MULTILINE,
)

_EMOJI_NUMS = ["1️⃣", "2️⃣", "3️⃣", "4️⃣"]

PERMISSION_HINT = "\n:lock: _To proceed, reply *y* or *n*_"
PLAN_HINT = (
    "\n:clipboard: _Reply *approve* to start coding,"
    " or reply with feedback to revise the plan_"
)


def truncate(text: str, limit: int = MAX_SLACK_TEXT) -> str:
    if len(text) <= limit:
        return text
    return text[: limit - 3] + "..."


def _convert_tables(text: str) -> str:
    """Convert Markdown tables to a readable Slack format."""

    def _convert_single(match: re.Match) -> str:
        lines = match.group(0).strip().split("\n")
        headers = [cell.strip() for cell in lines[0].strip("|").split("|")]
        blocks = []
        for line in lines[2:]:
            cells = [cell.strip() for cell in line.strip("|").split("|")]
            fields = [f"*{h}:* {c}" for h, c in zip(headers, cells, strict=False)]
            blocks.append("\n".join(fields))
        return "\n\n".join(blocks)

    return _TABLE_PATTERN.sub(_convert_single, text)


def md_to_mrkdwn(text: str) -> str:
    """Convert Markdown to Slack mrkdwn format, preserving code blocks."""
    parts = re.split(r"(```[\s\S]*?```)", text)
    result = []
    for i, part in enumerate(parts):
        if i % 2 == 1:
            result.append(part)
        else:
            part = _convert_tables(part)
            for pattern, replacement in _MRKDWN_PATTERNS:
                part = pattern.sub(replacement, part)
            result.append(part)
    return "".join(result)


def format_tool_permission(tool_name: str, tool_input: dict) -> str:
    """Format a tool call as a Slack permission prompt."""
    if tool_name == "Bash":
        cmd = tool_input.get("command", "")
        desc = tool_input.get("description", "")
        text = "Tool: `Bash`\n"
        if desc:
            text += f"Description: {desc}\n"
        text += f"```\n{cmd[:2000]}\n```"

    elif tool_name == "Edit":
        fp = tool_input.get("file_path", "")
        old = tool_input.get("old_string", "")[:500]
        new = tool_input.get("new_string", "")[:500]
        text = f"Tool: `Edit` → `{fp}`\n"
        text += f"Replace:\n```\n{old}\n```\nWith:\n```\n{new}\n```"

    elif tool_name == "Write":
        fp = tool_input.get("file_path", "")
        content = tool_input.get("content", "")[:1000]
        text = f"Tool: `Write` → `{fp}`\n"
        text += f"```\n{content}\n```"

    elif tool_name == "NotebookEdit":
        nb = tool_input.get("notebook_path", "")
        mode = tool_input.get("edit_mode", "replace")
        text = f"Tool: `NotebookEdit` ({mode}) → `{nb}`\n"
        src = tool_input.get("new_source", "")[:1000]
        if src:
            text += f"```\n{src}\n```"

    else:
        input_str = json.dumps(tool_input, indent=2)[:1500]
        text = f"Tool: `{tool_name}`\n"
        text += f"```\n{input_str}\n```"

    text += PERMISSION_HINT
    return truncate(text)


def format_single_question(q: dict, question_num: int, total: int) -> str:
    """Format a single AskUserQuestion for Slack."""
    question_text = q.get("question", "")
    header = q.get("header", "")
    options = q.get("options", [])
    multi = q.get("multiSelect", False)

    parts: list[str] = []

    if total > 1:
        parts.append(f":question: *Question {question_num}/{total}*\n")
    else:
        parts.append(":question: *Claude is asking:*\n")

    if header:
        parts.append(f"*[{header}]*")
    parts.append(f"{question_text}\n")

    for i, opt in enumerate(options, 1):
        label = opt.get("label", "")
        desc = opt.get("description", "")
        num = _EMOJI_NUMS[i - 1] if i <= len(_EMOJI_NUMS) else f"{i}."
        line = f"{num} *{label}*"
        if desc:
            line += f" — {desc}"
        parts.append(line)

    if multi:
        parts.append("\n_Reply with one or more numbers (e.g. `1,3`) or your own text_")
    else:
        parts.append("\n_Reply with a number or your own answer_")

    return truncate("\n".join(parts))


def format_plan_approval(plan: str, allowed_prompts: list[dict] | None = None) -> str:
    """Format a plan approval prompt for Slack.

    Args:
        plan: The plan markdown content from ExitPlanMode.
        allowed_prompts: Optional list of permission prompts the plan requests.
    """
    parts: list[str] = [":memo: *Claude has a plan — ready to code?*\n"]

    if plan:
        plan_mrkdwn = md_to_mrkdwn(plan)
        parts.append(plan_mrkdwn)

    if allowed_prompts:
        parts.append("\n*Requested permissions:*")
        for p in allowed_prompts:
            tool = p.get("tool", "")
            prompt = p.get("prompt", "")
            parts.append(f"• `{tool}` — {prompt}")

    parts.append(PLAN_HINT)
    return truncate("\n".join(parts))
