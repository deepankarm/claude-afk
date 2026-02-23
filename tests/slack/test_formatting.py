"""Tests for slack.formatting — pure logic, no fixtures needed."""

from __future__ import annotations

from claude_afk.slack.formatting import (
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
    assert "y" in result
    assert "n" in result


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
