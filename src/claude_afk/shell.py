"""Shell command parsing utilities.

Provides quote-aware splitting of shell commands and prefix extraction
for the bash auto-approval feature.
"""

from __future__ import annotations

import re

# Commands where the first word is ambiguous — need 2-word prefix.
# E.g. "git log --oneline" -> prefix "git log", not just "git".
_TWO_WORD_PREFIX_COMMANDS: set[str] = {
    "git",
    "go",
    "npm",
    "npx",
    "docker",
    "uv",
    "cargo",
    "kubectl",
    "pip",
    "pip3",
    "poetry",
    "yarn",
    "pnpm",
    "brew",
    "apt",
    "make",
    "dotnet",
    "az",
    "aws",
    "gcloud",
    "terraform",
}

# Pattern to match env var assignments at the start of a command.
_ENV_VAR_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*=\S*$")


def split_shell_commands(command: str) -> list[str]:
    """Split a shell command on ``|``, ``&&``, ``||``, ``;`` respecting quoting.

    The following constructs suppress delimiter recognition:

    * Single quotes (``'...'``) — everything literal, no escaping
    * Double quotes (``"..."``) — backslash escapes ``\\``, ``\"``, ``\$``, ``\\```
    * Backtick substitution (`` `...` ``)
    * Parentheses / braces nesting (``$(…)``, ``${…}``, subshells, process
      substitution ``<(…)`` / ``>(…)``)
    * Backslash escape outside quotes (``\\|``, ``\\;`` etc.)
    """
    parts: list[str] = []
    current: list[str] = []
    i = 0
    n = len(command)
    in_single = False
    in_double = False
    in_backtick = False
    depth = 0  # nesting depth for () and {}

    while i < n:
        c = command[i]

        # ── Inside single quotes: everything literal until closing ' ──
        if in_single:
            current.append(c)
            if c == "'":
                in_single = False
            i += 1
            continue

        # ── Inside backticks: everything literal until closing ` ──
        if in_backtick:
            current.append(c)
            if c == "\\" and i + 1 < n:
                current.append(command[i + 1])
                i += 2
                continue
            if c == "`":
                in_backtick = False
            i += 1
            continue

        # ── Inside double quotes ──
        if in_double:
            current.append(c)
            if c == "\\" and i + 1 < n:
                current.append(command[i + 1])
                i += 2
                continue
            if c == '"':
                in_double = False
            i += 1
            continue

        # ── Inside grouping (parens/braces) ──
        if depth > 0:
            current.append(c)
            if c == "'":
                in_single = True
            elif c == '"':
                in_double = True
            elif c == "`":
                in_backtick = True
            elif c in ("(", "{"):
                depth += 1
            elif c in (")", "}"):
                depth -= 1
            i += 1
            continue

        # ── Top-level parsing ──

        # Backslash escape: next char is literal
        if c == "\\" and i + 1 < n:
            current.append(c)
            current.append(command[i + 1])
            i += 2
            continue

        if c == "'":
            in_single = True
            current.append(c)
        elif c == '"':
            in_double = True
            current.append(c)
        elif c == "`":
            in_backtick = True
            current.append(c)
        elif c in ("(", "{"):
            depth += 1
            current.append(c)
        elif c == "|" and i + 1 < n and command[i + 1] == "|":
            parts.append("".join(current))
            current = []
            i += 1
        elif c == "|":
            parts.append("".join(current))
            current = []
        elif c == "&" and i + 1 < n and command[i + 1] == "&":
            parts.append("".join(current))
            current = []
            i += 1
        elif c == ";":
            parts.append("".join(current))
            current = []
        else:
            current.append(c)

        i += 1

    if current:
        parts.append("".join(current))

    return [p for p in parts if p.strip()]


def extract_command_prefixes(command: str) -> list[str]:
    """Extract command prefixes from a Bash command string.

    Splits on ``|``, ``&&``, ``;`` into sub-commands (respecting quotes and
    grouping characters).  For each, extracts a 1- or 2-word prefix depending
    on whether the base command is ambiguous.

    Examples::

        "git log --oneline | head -20"  -> ["git log", "head"]
        "grep -r foo . | wc -l"        -> ["grep", "wc"]
        "VAR=1 docker compose up"      -> ["docker compose"]
        'grep -E "(a|b|c)" file'       -> ["grep"]
    """
    if not command or not command.strip():
        return []

    sub_commands = split_shell_commands(command)
    seen: set[str] = set()
    prefixes: list[str] = []

    for sub in sub_commands:
        tokens = sub.strip().split()
        # Skip env var assignments (VAR=val)
        while tokens and _ENV_VAR_RE.match(tokens[0]):
            tokens = tokens[1:]
        if not tokens:
            continue

        base = tokens[0]
        if base in _TWO_WORD_PREFIX_COMMANDS and len(tokens) > 1:
            prefix = f"{base} {tokens[1]}"
        else:
            prefix = base

        if prefix not in seen:
            seen.add(prefix)
            prefixes.append(prefix)

    return prefixes
