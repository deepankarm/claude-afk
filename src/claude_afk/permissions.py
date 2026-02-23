"""Claude Code permission rule loading and matching.

Reads CC's permission rules from settings files (read-only, never writes)
to determine if a tool call already has an allow/deny rule, avoiding
unnecessary Slack round-trips.

Also manages a per-session permission cache so that repeated tool calls
(e.g. Read for the same file) don't flood Slack after the first approval.
"""

from __future__ import annotations

import fnmatch
import json
import os
from enum import Enum
from pathlib import Path

from claude_afk.config import AFK_HOME


class ToolPolicy(str, Enum):
    """How the PreToolUse hook handles a given tool."""

    AUTO_ALLOW = "auto_allow"
    ASK_ONCE = "ask_once"
    ALWAYS_ASK = "always_ask"


class Decision(str, Enum):
    """Permission decision from a Slack reply or cache lookup."""

    ALLOW = "allow"
    DENY = "deny"
    UNCLEAR = "unclear"


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


def get_tool_input_value(tool_name: str, tool_input: dict) -> str:
    """Get the primary input value for a tool (file_path for Read, command for Bash, etc.)."""
    field = _TOOL_SPECIFIER_FIELD.get(tool_name, "")
    if not field:
        return ""
    return tool_input.get(field, "")


# ── Tool permission policies ──────────────────────────────────────
# Controls how each tool is handled when CC fires PreToolUse.
# Edit this table to tune the Slack notification behaviour.
#
#   AUTO_ALLOW  - silently approve, never prompt on Slack
#                 (sensitive files still prompt — see below)
#   ASK_ONCE    - prompt once per file, remember for the session
#   ALWAYS_ASK  - always prompt on Slack
#
TOOL_POLICIES: dict[str, ToolPolicy] = {
    "Read": ToolPolicy.AUTO_ALLOW,
    "Grep": ToolPolicy.AUTO_ALLOW,
    "Glob": ToolPolicy.AUTO_ALLOW,
    "Edit": ToolPolicy.ASK_ONCE,
    "Write": ToolPolicy.ALWAYS_ASK,
    "Bash": ToolPolicy.ALWAYS_ASK,
    "Task": ToolPolicy.ALWAYS_ASK,
    "WebFetch": ToolPolicy.ALWAYS_ASK,
    "WebSearch": ToolPolicy.ALWAYS_ASK,
    "NotebookEdit": ToolPolicy.ALWAYS_ASK,
}

# Files matching these patterns always prompt, even for auto_allow tools.
# Matched against the basename (e.g. ".env" matches "/path/to/.env").
SENSITIVE_FILE_PATTERNS: list[str] = [
    ".env",
    ".env.*",
    "*.pem",
    "*.key",
    "*.p12",
    "*.pfx",
    "id_rsa",
    "id_rsa.*",
    "id_ed25519",
    "id_ed25519.*",
    ".npmrc",
    ".pypirc",
    "credentials.json",
    "secrets.*",
]


def is_sensitive_path(file_path: str) -> bool:
    """Check if a file path matches any sensitive file pattern."""
    if not file_path:
        return False
    basename = os.path.basename(file_path)
    return any(fnmatch.fnmatch(basename, pat) for pat in SENSITIVE_FILE_PATTERNS)


# --- Session-level permission cache ---

# ask_once tools are always cached; Read is auto_allow but caches sensitive-file decisions.
_SESSION_CACHEABLE_TOOLS: set[str] = {
    tool for tool, policy in TOOL_POLICIES.items() if policy == ToolPolicy.ASK_ONCE
} | {"Read"}


def _session_permissions_path(session_id: str) -> Path:
    """Return path to session permission cache file."""
    return AFK_HOME / "sessions" / session_id / "permissions.json"


def check_session_permission(
    session_id: str, tool_name: str, tool_input: dict
) -> Decision | None:
    """Check session cache. Returns Decision.ALLOW, Decision.DENY, or None (not cached)."""
    path = _session_permissions_path(session_id)
    if not path.exists():
        return None
    try:
        with open(path) as f:
            data = json.load(f)
    except (json.JSONDecodeError, OSError):
        return None

    perms = data.get("permissions", {})

    # Check deny first — specific denials take precedence over broad allows
    deny_rules = perms.get("deny", [])
    if tool_has_cc_rule(tool_name, tool_input, deny_rules):
        return Decision.DENY

    allow_rules = perms.get("allow", [])
    if tool_has_cc_rule(tool_name, tool_input, allow_rules):
        return Decision.ALLOW

    return None


def build_session_rule(tool_name: str, tool_input: dict) -> str | None:
    """Build a per-file permission rule, or None if not cacheable.

    Returns e.g. "Edit(/path/to/file.py)" or "Read(/path/.env)".
    """
    if tool_name not in _SESSION_CACHEABLE_TOOLS:
        return None
    value = get_tool_input_value(tool_name, tool_input)
    if not value:
        return None
    return f"{tool_name}({value})"


def save_session_permission(session_id: str, rule: str, decision: Decision) -> None:
    """Append a rule to the session permission cache."""
    path = _session_permissions_path(session_id)
    path.parent.mkdir(parents=True, exist_ok=True)

    data: dict = {"permissions": {"allow": [], "deny": []}}
    if path.exists():
        try:
            with open(path) as f:
                data = json.load(f)
        except (json.JSONDecodeError, OSError):
            pass

    perms = data.setdefault("permissions", {})
    lst = perms.setdefault(decision, [])
    if rule not in lst:
        lst.append(rule)

    with open(path, "w") as f:
        json.dump(data, f, indent=2)
        f.write("\n")
