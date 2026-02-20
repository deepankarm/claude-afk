"""Configuration and state management for claude-afk.

All persistent state lives under ~/.claude-afk/:
  config.json        — Slack tokens, user ID, DM channel (chmod 600)
  state.json         — which sessions are enabled for Slack routing
  slack/threads/     — per-session Slack thread state
  logs/              — debug logs
"""

from __future__ import annotations

import json
import logging
import os
import stat
from dataclasses import dataclass, field
from pathlib import Path

DEFAULT_TIMEOUT = 300
MAX_SLACK_TEXT = 3000

AFK_HOME = Path(os.environ.get("CLAUDE_AFK_HOME", "~/.claude-afk")).expanduser()

log = logging.getLogger("claude-afk")


def setup_logging() -> None:
    """Configure logging to write to ~/.claude-afk/logs/claude-afk.log."""
    ensure_home()
    log_path = AFK_HOME / "logs" / "claude-afk.log"
    handler = logging.FileHandler(log_path)
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s %(message)s"))
    root = logging.getLogger("claude-afk")
    root.setLevel(logging.DEBUG)
    if not root.handlers:
        root.addHandler(handler)


def ensure_home() -> None:
    """Create the ~/.claude-afk directory structure if it doesn't exist."""
    AFK_HOME.mkdir(parents=True, exist_ok=True)
    (AFK_HOME / "slack" / "threads").mkdir(parents=True, exist_ok=True)
    (AFK_HOME / "logs").mkdir(parents=True, exist_ok=True)


@dataclass(frozen=True)
class SlackConfig:
    """Slack connection configuration, loaded from ~/.claude-afk/config.json."""

    bot_token: str = ""
    socket_mode_token: str = ""
    user_id: str = ""
    dm_channel_id: str = ""
    timeout: int = DEFAULT_TIMEOUT
    claude_homes: list[str] = field(default_factory=list)

    @classmethod
    def from_file(cls) -> SlackConfig:
        path = AFK_HOME / "config.json"
        if not path.exists():
            return cls()
        try:
            with open(path) as f:
                data = json.load(f)
            return cls(
                bot_token=data.get("slack_bot_token", ""),
                socket_mode_token=data.get("slack_socket_mode_token", ""),
                user_id=data.get("slack_user_id", ""),
                dm_channel_id=data.get("slack_dm_channel_id", ""),
                timeout=data.get("timeout", DEFAULT_TIMEOUT),
                claude_homes=data.get("claude_homes", []),
            )
        except (json.JSONDecodeError, OSError):
            return cls()

    def save(self) -> None:
        """Persist config to ~/.claude-afk/config.json with restricted permissions."""
        ensure_home()
        path = AFK_HOME / "config.json"
        data = {
            "slack_bot_token": self.bot_token,
            "slack_socket_mode_token": self.socket_mode_token,
            "slack_user_id": self.user_id,
            "slack_dm_channel_id": self.dm_channel_id,
            "timeout": self.timeout,
            "claude_homes": self.claude_homes,
        }
        with open(path, "w") as f:
            json.dump(data, f, indent=2)
            f.write("\n")
        os.chmod(path, stat.S_IRUSR | stat.S_IWUSR)  # 600

    def is_valid(self) -> bool:
        return bool(
            self.bot_token and self.socket_mode_token and self.user_id and self.dm_channel_id
        )


def load_state() -> dict:
    """Load session state from ~/.claude-afk/state.json."""
    path = AFK_HOME / "state.json"
    if not path.exists():
        return {"enabled": []}
    try:
        with open(path) as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return {"enabled": []}


def save_state(state: dict) -> None:
    """Save session state to ~/.claude-afk/state.json."""
    ensure_home()
    path = AFK_HOME / "state.json"
    with open(path, "w") as f:
        json.dump(state, f, indent=2)
        f.write("\n")


def is_session_enabled(session_id: str) -> bool:
    """Check if a session is enabled for Slack routing."""
    state = load_state()
    enabled = state.get("enabled", [])
    if enabled == "all":
        return True
    if isinstance(enabled, list):
        return session_id in enabled
    return False
