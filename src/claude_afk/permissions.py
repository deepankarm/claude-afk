"""Claude Code permission rule loading and matching.

Reads CC's permission rules from settings files (read-only, never writes)
to determine if a tool call already has an allow/deny rule, avoiding
unnecessary Slack round-trips.
"""

from __future__ import annotations

import fnmatch
import json
import os

# Map tool names to the input field used for permission rule matching.
# E.g. rule "Bash(npm run *)" matches against tool_input["command"].
_TOOL_SPECIFIER_FIELD: dict[str, str] = {
    "Bash": "command",
    "Read": "file_path",
    "Edit": "file_path",
    "Write": "file_path",
    "NotebookEdit": "notebook_path",
    "WebFetch": "url",
    "WebSearch": "query",
}


def _load_json_permissions(path: str) -> list[str]:
    """Load the permissions.allow + permissions.deny lists from a JSON file."""
    if not os.path.exists(path):
        return []
    try:
        with open(path) as f:
            data = json.load(f)
        perms = data.get("permissions", {})
        return perms.get("allow", []) + perms.get("deny", [])
    except (json.JSONDecodeError, OSError):
        return []


def load_cc_permission_rules(cwd: str) -> list[str]:
    """Read CC's permission rules from all settings files (read-only).

    Checks (in order):
      1. CLAUDE_CONFIG_DIR/settings.json (user-level, e.g. ~/.claude/)
      2. <project>/.claude/settings.local.json (project-local, gitignored)
      3. <project>/.claude/settings.json (project-shared)

    Returns a combined list of all allow + deny rule strings.
    """
    rules: list[str] = []

    config_dir = os.environ.get("CLAUDE_CONFIG_DIR", os.path.expanduser("~/.claude"))
    rules.extend(_load_json_permissions(os.path.join(config_dir, "settings.json")))

    if cwd:
        rules.extend(_load_json_permissions(os.path.join(cwd, ".claude", "settings.local.json")))
        rules.extend(_load_json_permissions(os.path.join(cwd, ".claude", "settings.json")))

    return rules


def tool_has_cc_rule(tool_name: str, tool_input: dict, rules: list[str]) -> bool:
    """Check if a tool call matches any CC permission rule.

    Rule formats:
      "Bash"              — matches all Bash calls
      "Bash(npm run *)"   — matches Bash calls where command matches glob
      "Read(~/.zshrc)"    — matches Read calls for that file path
    """
    for rule in rules:
        if "(" in rule and rule.endswith(")"):
            rule_tool = rule[: rule.index("(")]
            rule_pattern = rule[rule.index("(") + 1 : -1]

            if rule_tool != tool_name:
                continue

            field = _TOOL_SPECIFIER_FIELD.get(tool_name, "")
            if field:
                value = tool_input.get(field, "")
                if fnmatch.fnmatch(value, rule_pattern):
                    return True
        else:
            if rule == tool_name:
                return True

    return False
