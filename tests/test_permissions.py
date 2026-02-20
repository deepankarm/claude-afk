"""Tests for permissions — CC rule loading and matching."""

from __future__ import annotations

import json

from claude_afk.permissions import load_cc_permission_rules, tool_has_cc_rule


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
