"""Tests for permissions — CC rule loading and matching + session cache."""

from __future__ import annotations

import json

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

# --- tool_has_cc_rule ---


def test_tool_has_cc_rule_bare():
    assert tool_has_cc_rule("Bash", {"command": "anything"}, ["Bash"]) is True


def test_tool_has_cc_rule_glob():
    rules = ["Bash(npm run *)"]
    assert tool_has_cc_rule("Bash", {"command": "npm run test"}, rules) is True
    assert tool_has_cc_rule("Bash", {"command": "npm run build"}, rules) is True


def test_tool_has_cc_rule_no_match():
    assert tool_has_cc_rule("Write", {"file_path": "/tmp/x"}, ["Bash"]) is False


def test_tool_has_cc_rule_file_glob():
    rules = ["Read(~/.zshrc)"]
    assert tool_has_cc_rule("Read", {"file_path": "~/.zshrc"}, rules) is True
    assert tool_has_cc_rule("Read", {"file_path": "/etc/passwd"}, rules) is False


# --- load_cc_permission_rules ---


def test_load_cc_permission_rules(tmp_path, monkeypatch):
    # Set up a fake CLAUDE_CONFIG_DIR with settings
    config_dir = tmp_path / "claude-config"
    config_dir.mkdir()
    settings = {
        "permissions": {
            "allow": ["Bash(npm run *)"],
            "deny": ["Write(/etc/*)"],
        }
    }
    (config_dir / "settings.json").write_text(json.dumps(settings))
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(config_dir))

    # Set up project-level settings
    project_dir = tmp_path / "myproject"
    (project_dir / ".claude").mkdir(parents=True)
    proj_settings = {"permissions": {"allow": ["Read"]}}
    (project_dir / ".claude" / "settings.json").write_text(json.dumps(proj_settings))

    rules = load_cc_permission_rules(str(project_dir))
    assert "Bash(npm run *)" in rules
    assert "Write(/etc/*)" in rules
    assert "Read" in rules


def test_load_cc_permission_rules_missing_files(tmp_path, monkeypatch):
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(tmp_path / "nonexistent"))
    rules = load_cc_permission_rules(str(tmp_path / "nope"))
    assert rules == []


# --- tool policies ---


def test_tool_policies_read_is_auto_allow():
    assert TOOL_POLICIES["Read"] == ToolPolicy.AUTO_ALLOW


def test_tool_policies_grep_glob_auto_allow():
    assert TOOL_POLICIES["Grep"] == ToolPolicy.AUTO_ALLOW
    assert TOOL_POLICIES["Glob"] == ToolPolicy.AUTO_ALLOW


def test_tool_policies_edit_ask_once():
    assert TOOL_POLICIES["Edit"] == ToolPolicy.ASK_ONCE


def test_tool_policies_bash_always_ask():
    assert TOOL_POLICIES["Bash"] == ToolPolicy.ALWAYS_ASK


# --- get_tool_input_value ---


def test_get_tool_input_value_read():
    assert get_tool_input_value("Read", {"file_path": "/tmp/foo.py"}) == "/tmp/foo.py"


def test_get_tool_input_value_bash():
    assert get_tool_input_value("Bash", {"command": "ls -la"}) == "ls -la"


def test_get_tool_input_value_unknown_tool():
    assert get_tool_input_value("UnknownTool", {"foo": "bar"}) == ""


# --- is_sensitive_path ---


def test_sensitive_path_env():
    assert is_sensitive_path("/path/to/.env") is True
    assert is_sensitive_path("/path/to/.env.local") is True
    assert is_sensitive_path("/path/to/.env.production") is True


def test_sensitive_path_keys():
    assert is_sensitive_path("/home/user/.ssh/id_rsa") is True
    assert is_sensitive_path("/home/user/.ssh/id_ed25519") is True
    assert is_sensitive_path("/certs/server.pem") is True
    assert is_sensitive_path("/certs/server.key") is True


def test_sensitive_path_credentials():
    assert is_sensitive_path("/path/credentials.json") is True
    assert is_sensitive_path("/path/.npmrc") is True
    assert is_sensitive_path("/path/.pypirc") is True


def test_sensitive_path_normal_files():
    assert is_sensitive_path("/path/to/main.py") is False
    assert is_sensitive_path("/path/to/README.md") is False
    assert is_sensitive_path("/path/to/settings.json") is False
    assert is_sensitive_path("/path/to/environment.py") is False


def test_sensitive_path_empty():
    assert is_sensitive_path("") is False


# --- build_session_rule ---


def test_build_session_rule_read():
    rule = build_session_rule("Read", {"file_path": "/tmp/.env"})
    assert rule == "Read(/tmp/.env)"


def test_build_session_rule_edit():
    rule = build_session_rule("Edit", {"file_path": "/tmp/foo.py"})
    assert rule == "Edit(/tmp/foo.py)"


def test_build_session_rule_bash():
    assert build_session_rule("Bash", {"command": "ls"}) is None


def test_build_session_rule_grep():
    assert build_session_rule("Grep", {"pattern": "foo"}) is None


def test_build_session_rule_empty_value():
    assert build_session_rule("Read", {"file_path": ""}) is None


# --- save / check session permissions ---


def test_save_and_check_session_permission_allow(tmp_path, monkeypatch):
    import claude_afk.permissions as perms

    monkeypatch.setattr(perms, "AFK_HOME", tmp_path)

    # Per-file allow — covers that specific file
    save_session_permission("sess-1", "Read(/tmp/foo.py)", Decision.ALLOW)

    result = check_session_permission("sess-1", "Read", {"file_path": "/tmp/foo.py"})
    assert result == Decision.ALLOW
    # Different file is not cached
    result2 = check_session_permission("sess-1", "Read", {"file_path": "/tmp/bar.py"})
    assert result2 is None


def test_save_and_check_session_permission_edit(tmp_path, monkeypatch):
    import claude_afk.permissions as perms

    monkeypatch.setattr(perms, "AFK_HOME", tmp_path)

    save_session_permission("sess-1", "Edit(/tmp/main.py)", Decision.ALLOW)

    result = check_session_permission("sess-1", "Edit", {"file_path": "/tmp/main.py"})
    assert result == Decision.ALLOW
    assert check_session_permission("sess-1", "Edit", {"file_path": "/tmp/other.py"}) is None


def test_check_session_permission_deny(tmp_path, monkeypatch):
    import claude_afk.permissions as perms

    monkeypatch.setattr(perms, "AFK_HOME", tmp_path)

    save_session_permission("sess-1", "Read(/tmp/.env)", Decision.DENY)

    result = check_session_permission("sess-1", "Read", {"file_path": "/tmp/.env"})
    assert result == Decision.DENY


def test_check_session_permission_not_cached(tmp_path, monkeypatch):
    import claude_afk.permissions as perms

    monkeypatch.setattr(perms, "AFK_HOME", tmp_path)

    result = check_session_permission("sess-1", "Read", {"file_path": "/tmp/bar.py"})
    assert result is None


def test_save_session_permission_no_duplicates(tmp_path, monkeypatch):
    import claude_afk.permissions as perms

    monkeypatch.setattr(perms, "AFK_HOME", tmp_path)

    save_session_permission("sess-1", "Edit(/tmp/foo.py)", Decision.ALLOW)
    save_session_permission("sess-1", "Edit(/tmp/foo.py)", Decision.ALLOW)

    path = tmp_path / "sessions" / "sess-1" / "permissions.json"
    data = json.loads(path.read_text())
    assert data["permissions"]["allow"].count("Edit(/tmp/foo.py)") == 1


def test_deny_takes_precedence_over_allow(tmp_path, monkeypatch):
    """Deny for a file beats allow for the same file."""
    import claude_afk.permissions as perms

    monkeypatch.setattr(perms, "AFK_HOME", tmp_path)

    save_session_permission("sess-1", "Edit(/tmp/main.py)", Decision.ALLOW)
    save_session_permission("sess-1", "Edit(/tmp/main.py)", Decision.DENY)

    # Deny checked first, takes precedence
    result = check_session_permission("sess-1", "Edit", {"file_path": "/tmp/main.py"})
    assert result == Decision.DENY
