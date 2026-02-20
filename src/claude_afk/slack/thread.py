"""Thread state persistence for Slack bridge sessions.

Stores the Slack thread_ts under ~/.claude-afk/slack/threads/ so that all
messages within a Claude Code session stay in the same Slack thread —
shared by both stop and pretooluse hooks.
"""

from __future__ import annotations

import json

from claude_afk.config import AFK_HOME, ensure_home


def _threads_dir():
    return AFK_HOME / "slack" / "threads"


def get_state_path(session_id: str) -> str:
    return str(_threads_dir() / f"{session_id}.json")


def load(session_id: str) -> dict:
    path = _threads_dir() / f"{session_id}.json"
    if path.exists():
        try:
            with open(path) as f:
                return json.load(f)
        except (json.JSONDecodeError, OSError):
            pass
    return {}


def save(session_id: str, thread_ts: str) -> None:
    ensure_home()
    _threads_dir().mkdir(parents=True, exist_ok=True)
    path = _threads_dir() / f"{session_id}.json"
    with open(path, "w") as f:
        json.dump({"thread_ts": thread_ts}, f)
