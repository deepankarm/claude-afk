"""Tests for slack.formatting — pure logic, no fixtures needed."""

from __future__ import annotations

from claude_afk.slack.formatting import (
    QUESTION_TIMEOUT_REMINDER,
    TIMEOUT_REMINDER,
    format_bash_prefix_hint,
    format_plan_approval,
    format_single_question,
    format_tool_permission,
    md_to_mrkdwn,
    truncate,
)

# --- truncate ---


def test_truncate_short():
    assert truncate("hello", 100) == "hello"


def test_truncate_long():
    result = truncate("abcdefghij", 7)
    assert result == "abcd..."
    assert len(result) == 7


# --- md_to_mrkdwn ---


def test_md_to_mrkdwn_bold():
    assert md_to_mrkdwn("**text**") == "*text*"


def test_md_to_mrkdwn_italic():
    assert md_to_mrkdwn("*text*") == "_text_"


def test_md_to_mrkdwn_headers():
    assert md_to_mrkdwn("## Header") == "*Header*"


def test_md_to_mrkdwn_code_blocks_preserved():
    text = "before\n```\ncode **block**\n```\nafter"
    result = md_to_mrkdwn(text)
    assert "```\ncode **block**\n```" in result


def test_md_to_mrkdwn_links():
    assert md_to_mrkdwn("[text](http://example.com)") == "<http://example.com|text>"


def test_md_to_mrkdwn_tables():
    table = "| Name | Age |\n|------|-----|\n| Alice | 30 |"
    result = md_to_mrkdwn(table)
    # Table headers get converted to *H:* by _convert_tables, then the italic
    # pattern converts *H:* → _H:_ since single-asterisk matches italic.
    assert "Name:" in result
    assert "Alice" in result


# --- format_tool_permission ---


def test_format_tool_permission_bash():
    result = format_tool_permission("Bash", {"command": "npm test", "description": "Run tests"})
    assert "`Bash`" in result
    assert "npm test" in result
    assert "Run tests" in result
    assert "allow" in result
    assert "deny" in result
    assert "───" in result
    assert "reply with feedback" in result


def test_format_tool_permission_edit():
    result = format_tool_permission(
        "Edit",
        {"file_path": "/tmp/foo.py", "old_string": "old", "new_string": "new"},
    )
    assert "`Edit`" in result
    assert "/tmp/foo.py" in result
    assert "old" in result
    assert "new" in result


def test_format_tool_permission_write():
    result = format_tool_permission("Write", {"file_path": "/tmp/bar.py", "content": "hello"})
    assert "`Write`" in result
    assert "/tmp/bar.py" in result
    assert "hello" in result


def test_format_tool_permission_generic():
    result = format_tool_permission("CustomTool", {"key": "val"})
    assert "`CustomTool`" in result
    assert "val" in result


# --- format_single_question ---


def test_format_single_question_basic():
    q = {
        "question": "Which option?",
        "header": "Choice",
        "options": [
            {"label": "A", "description": "Option A"},
            {"label": "B", "description": "Option B"},
        ],
        "multiSelect": False,
    }
    result = format_single_question(q, 1, 1)
    assert "Claude is asking:" in result
    assert "Which option?" in result
    assert "*A*" in result
    assert "*B*" in result
    assert "Reply with a number or your own answer" in result


def test_format_single_question_multiselect():
    q = {
        "question": "Pick many?",
        "header": "",
        "options": [{"label": "X", "description": ""}],
        "multiSelect": True,
    }
    result = format_single_question(q, 1, 1)
    assert "one or more numbers" in result


def test_format_single_question_multi_total():
    q = {
        "question": "First?",
        "header": "",
        "options": [{"label": "A", "description": ""}],
        "multiSelect": False,
    }
    result = format_single_question(q, 1, 3)
    assert "Question 1/3" in result


# --- format_plan_approval ---


def test_format_plan_approval_basic():
    result = format_plan_approval("## Steps\n1. Do thing\n2. Do other thing")
    assert "plan" in result.lower()
    assert "Do thing" in result
    assert "thumbsup" in result


def test_format_plan_approval_with_prompts():
    prompts = [
        {"tool": "Bash", "prompt": "run tests"},
        {"tool": "Bash", "prompt": "install dependencies"},
    ]
    result = format_plan_approval("My plan", prompts)
    assert "`Bash`" in result
    assert "run tests" in result
    assert "install dependencies" in result
    assert "Requested permissions" in result


def test_format_plan_approval_empty_plan():
    result = format_plan_approval("")
    assert "plan" in result.lower()
    assert "thumbsup" in result


def test_format_plan_approval_no_prompts():
    result = format_plan_approval("Simple plan")
    assert "Simple plan" in result
    assert "Requested permissions" not in result


# --- format_bash_prefix_hint ---


def test_format_bash_prefix_hint():
    result = format_bash_prefix_hint(["git log", "grep"])
    assert "`git log`" in result
    assert "`grep`" in result
    assert "fast_forward" in result


def test_format_bash_prefix_hint_single():
    result = format_bash_prefix_hint(["head"])
    assert "`head`" in result


# --- format_tool_permission with prefix hints ---


def test_format_tool_permission_bash_with_prefixes():
    result = format_tool_permission(
        "Bash",
        {"command": "git log --oneline | head -5"},
        unapproved_prefixes=["git log", "head"],
    )
    assert "`Bash`" in result
    assert "git log --oneline" in result
    assert "fast_forward" in result
    assert "`git log`" in result
    assert "`head`" in result


def test_format_tool_permission_bash_without_prefixes():
    result = format_tool_permission("Bash", {"command": "ls -la"})
    assert "`Bash`" in result
    assert "fast_forward" not in result


def test_format_tool_permission_non_bash_ignores_prefixes():
    result = format_tool_permission(
        "Write",
        {"file_path": "/tmp/f.py", "content": "x"},
        unapproved_prefixes=["something"],
    )
    assert "fast_forward" not in result


# --- timeout reminders ---


def test_timeout_reminder_has_action_hints():
    assert "Still waiting" in TIMEOUT_REMINDER
    assert "thumbsup" in TIMEOUT_REMINDER
    assert "thumbsdown" in TIMEOUT_REMINDER
    assert "───" in TIMEOUT_REMINDER


def test_question_timeout_reminder_has_action_hints():
    assert "Still waiting" in QUESTION_TIMEOUT_REMINDER
    assert "answer" in QUESTION_TIMEOUT_REMINDER
