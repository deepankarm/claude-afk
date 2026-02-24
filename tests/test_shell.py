"""Tests for shell — command splitting and prefix extraction."""

from __future__ import annotations

from claude_afk.shell import extract_command_prefixes, split_shell_commands

# --- split_shell_commands ---


def test_split_simple_pipe():
    assert split_shell_commands("ls | head") == ["ls ", " head"]


def test_split_double_pipe():
    assert split_shell_commands("test -f foo || echo no") == ["test -f foo ", " echo no"]


def test_split_and():
    assert split_shell_commands("mkdir foo && cd foo") == ["mkdir foo ", " cd foo"]


def test_split_semicolon():
    assert split_shell_commands("echo a; echo b") == ["echo a", " echo b"]


def test_split_preserves_single_quotes():
    result = split_shell_commands("grep 'a|b' file | head")
    assert len(result) == 2
    assert "'a|b'" in result[0]


def test_split_preserves_double_quotes():
    result = split_shell_commands('grep "a|b" file | head')
    assert len(result) == 2
    assert '"a|b"' in result[0]


def test_split_preserves_backticks():
    result = split_shell_commands("echo `cat foo | wc -l` | head")
    assert len(result) == 2
    assert "`cat foo | wc -l`" in result[0]


def test_split_preserves_parentheses():
    result = split_shell_commands("echo $(cat foo | wc -l) | head")
    assert len(result) == 2
    assert "$(cat foo | wc -l)" in result[0]


def test_split_backslash_escaped_pipe():
    result = split_shell_commands(r"echo foo \| bar")
    assert len(result) == 1


def test_split_backslash_escaped_semicolon():
    result = split_shell_commands(r"find . -exec rm {} \;")
    assert len(result) == 1


def test_split_nested_parens():
    result = split_shell_commands("echo $(echo $(cat f | head) | tail) | wc")
    assert len(result) == 2


def test_split_curly_braces():
    result = split_shell_commands("echo ${VAR:-default|fallback} | head")
    assert len(result) == 2
    assert "${VAR:-default|fallback}" in result[0]


def test_split_empty():
    assert split_shell_commands("") == []
    assert split_shell_commands("   ") == []


def test_split_no_delimiters():
    assert split_shell_commands("echo hello world") == ["echo hello world"]


# --- extract_command_prefixes ---


def test_extract_prefixes_simple_command():
    assert extract_command_prefixes("grep -r foo .") == ["grep"]


def test_extract_prefixes_two_word_git():
    assert extract_command_prefixes("git log --oneline") == ["git log"]


def test_extract_prefixes_two_word_docker():
    assert extract_command_prefixes("docker compose up -d") == ["docker compose"]


def test_extract_prefixes_piped():
    result = extract_command_prefixes("git log --oneline | head -20")
    assert result == ["git log", "head"]


def test_extract_prefixes_chained():
    result = extract_command_prefixes("git add . && git commit -m 'msg'")
    assert result == ["git add", "git commit"]


def test_extract_prefixes_semicolon():
    result = extract_command_prefixes("ls -la; wc -l")
    assert result == ["ls", "wc"]


def test_extract_prefixes_env_vars():
    result = extract_command_prefixes("VAR=1 docker compose up")
    assert result == ["docker compose"]


def test_extract_prefixes_multiple_env_vars():
    result = extract_command_prefixes("FOO=bar BAZ=qux npm run build")
    assert result == ["npm run"]


def test_extract_prefixes_dedup():
    result = extract_command_prefixes("grep foo | grep bar")
    assert result == ["grep"]


def test_extract_prefixes_empty():
    assert extract_command_prefixes("") == []
    assert extract_command_prefixes("   ") == []


def test_extract_prefixes_single_word_two_word_cmd():
    """When a two-word command has only one token, use single word."""
    assert extract_command_prefixes("git") == ["git"]


def test_extract_prefixes_mixed_pipe_and_chain():
    result = extract_command_prefixes("git diff HEAD | grep TODO && echo done")
    assert result == ["git diff", "grep", "echo"]


def test_extract_prefixes_pipe_inside_double_quotes():
    """Pipes inside double-quoted regex should not split."""
    result = extract_command_prefixes('grep -E "(foo|bar|baz)" file.txt | head -5')
    assert result == ["grep", "head"]


def test_extract_prefixes_pipe_inside_single_quotes():
    result = extract_command_prefixes("grep -E '(a|b)' file.txt")
    assert result == ["grep"]


def test_extract_prefixes_pipe_inside_parentheses():
    """Pipes inside $(...) subshell should not split."""
    result = extract_command_prefixes("echo $(cat foo | wc -l) | head")
    assert result == ["echo", "head"]


def test_extract_prefixes_complex_quoted_grep():
    """Real-world grep with multiple pipe-separated patterns in quotes."""
    cmd = 'grep -E "(saved bash prefixes|all bash prefixes approved|unapproved)" log | tail -30'
    result = extract_command_prefixes(cmd)
    assert result == ["grep", "tail"]


def test_extract_prefixes_or_operator():
    """|| should split like &&."""
    result = extract_command_prefixes("test -f foo || echo missing")
    assert result == ["test", "echo"]


def test_extract_prefixes_backtick_substitution():
    """Pipes inside backtick command substitution should not split."""
    result = extract_command_prefixes("echo `cat foo | wc -l` | head")
    assert result == ["echo", "head"]


def test_extract_prefixes_nested_backtick():
    result = extract_command_prefixes("echo `grep -E 'a|b' file` done")
    assert result == ["echo"]


def test_extract_prefixes_backslash_escaped_pipe():
    r"""A backslash-escaped pipe \| is not a delimiter."""
    result = extract_command_prefixes(r"echo hello \| world")
    assert result == ["echo"]


def test_extract_prefixes_backslash_escaped_semicolon():
    r"""A backslash-escaped semicolon \; is not a delimiter."""
    result = extract_command_prefixes(r"find . -name '*.py' -exec rm {} \;")
    assert result == ["find"]


def test_extract_prefixes_process_substitution():
    """diff <(cmd1) <(cmd2) — pipes inside <(...) should not split."""
    result = extract_command_prefixes("diff <(cat a | sort) <(cat b | sort)")
    assert result == ["diff"]


def test_extract_prefixes_subshell_with_pipes():
    """Pipes inside a subshell (...) should not split."""
    result = extract_command_prefixes("(grep foo file | head -5) && echo done")
    assert result == ["(grep", "echo"]


def test_extract_prefixes_dollar_paren_nested():
    """Nested $(...$(...)) should stay grouped."""
    result = extract_command_prefixes("echo $(echo $(cat f | head) | tail) | wc")
    assert result == ["echo", "wc"]


def test_extract_prefixes_mixed_quotes_and_pipe():
    """Pipe outside quotes should split, pipe inside should not."""
    result = extract_command_prefixes("""grep "a|b" file | awk '{print $1}'""")
    assert result == ["grep", "awk"]


def test_extract_prefixes_escaped_quote_in_double_quotes():
    r"""Escaped quote inside double quotes should not break parsing."""
    result = extract_command_prefixes(r'echo "he said \"hello\"" | wc')
    assert result == ["echo", "wc"]


def test_extract_prefixes_semicolon_in_single_quotes():
    """Semicolons inside single quotes should not split."""
    result = extract_command_prefixes("echo 'hello; world' | cat")
    assert result == ["echo", "cat"]


def test_extract_prefixes_ampersand_in_quotes():
    """&& inside quotes should not split."""
    result = extract_command_prefixes('echo "foo && bar" | head')
    assert result == ["echo", "head"]


def test_extract_prefixes_curly_brace_expansion():
    """Curly braces should be treated as grouping."""
    result = extract_command_prefixes("echo ${VAR:-default} | head")
    assert result == ["echo", "head"]


def test_extract_prefixes_real_world_grep_pattern():
    """Real-world command that triggered the original bug."""
    cmd = (
        'grep -E "(saved bash prefixes|all bash prefixes approved'
        '|unapproved prefixes|Always-allowed|REPLY_ALWAYS_ALLOW'
        '|fast_forward)" ~/.claude-afk/logs/claude-afk.log | tail -30'
    )
    result = extract_command_prefixes(cmd)
    assert result == ["grep", "tail"]
