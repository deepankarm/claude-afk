"""CLI entry point for claude-afk."""

from __future__ import annotations

import contextlib
import json
import random
import sys
from pathlib import Path

import click

from claude_afk import __version__
from claude_afk.config import (
    AFK_HOME,
    SlackConfig,
    load_state,
    save_state,
)


@click.group()
@click.version_option(version=__version__)
def main() -> None:
    """claude-afk: Control Claude Code remotely via Slack."""


@main.group()
def hook() -> None:
    """Run a Claude Code hook handler (called by CC, not directly)."""


@hook.command()
def stop() -> None:
    """Handle the Stop hook — post last message to Slack, wait for reply."""
    from claude_afk.hooks.stop import main as stop_main

    stop_main()


@hook.command()
def pretooluse() -> None:
    """Handle the PreToolUse hook — route permissions and questions to Slack."""
    from claude_afk.hooks.pretooluse import main as pretooluse_main

    pretooluse_main()


@hook.command()
@click.option(
    "--event",
    type=click.Choice(["stop", "notification"]),
    default="notification",
    help="The hook event type.",
)
def notify(event: str) -> None:
    """Handle the Notification hook — send one-way DM notification."""
    from claude_afk.hooks.notify import main as notify_main

    notify_main(event=event)


_HOOK_MARKER = "claude-afk"

_HOOKS_TO_INSTALL = {
    "PreToolUse": [
        {
            "matcher": "AskUserQuestion",
            "hooks": [{"type": "command", "command": "claude-afk hook pretooluse"}],
        },
        {
            "matcher": "",
            "hooks": [{"type": "command", "command": "claude-afk hook pretooluse"}],
        },
    ],
    "Stop": [
        {
            "matcher": "",
            "hooks": [{"type": "command", "command": "claude-afk hook stop"}],
        },
    ],
    "Notification": [
        {
            "matcher": "",
            "hooks": [{"type": "command", "command": "claude-afk hook notify"}],
        },
    ],
}


def _install_hooks(claude_home: str) -> bool:
    """Merge claude-afk hooks into a Claude Code settings.json."""
    settings_path = Path(claude_home).expanduser() / "settings.json"

    if settings_path.exists():
        try:
            with open(settings_path) as f:
                settings = json.load(f)
        except (json.JSONDecodeError, OSError):
            settings = {}
    else:
        settings_path.parent.mkdir(parents=True, exist_ok=True)
        settings = {}

    hooks = settings.setdefault("hooks", {})

    for event_name, entries in _HOOKS_TO_INSTALL.items():
        existing = hooks.get(event_name, [])

        # Remove any previous claude-afk entries to avoid duplicates
        existing = [
            e
            for e in existing
            if not any(_HOOK_MARKER in h.get("command", "") for h in e.get("hooks", []))
        ]

        existing.extend(entries)
        hooks[event_name] = existing

    with open(settings_path, "w") as f:
        json.dump(settings, f, indent=2)
        f.write("\n")

    return True


def _uninstall_hooks(claude_home: str) -> bool:
    """Remove claude-afk hooks from a Claude Code settings.json."""
    settings_path = Path(claude_home).expanduser() / "settings.json"

    if not settings_path.exists():
        return False

    try:
        with open(settings_path) as f:
            settings = json.load(f)
    except (json.JSONDecodeError, OSError):
        return False

    hooks = settings.get("hooks", {})
    changed = False

    for event_name in list(hooks.keys()):
        original = hooks[event_name]
        filtered = [
            e
            for e in original
            if not any(_HOOK_MARKER in h.get("command", "") for h in e.get("hooks", []))
        ]
        if len(filtered) != len(original):
            changed = True
            if filtered:
                hooks[event_name] = filtered
            else:
                del hooks[event_name]

    if changed:
        with open(settings_path, "w") as f:
            json.dump(settings, f, indent=2)
            f.write("\n")

    return changed


@main.command()
@click.option(
    "--claude-home",
    default="~/.claude",
    help="Path to Claude Code config directory (default: ~/.claude).",
)
def setup(claude_home: str) -> None:
    """Set up claude-afk — configure Slack tokens and install hooks."""
    from slack_sdk import WebClient

    click.echo("claude-afk setup\n")

    bot_token = click.prompt("Slack Bot Token (xoxb-...)", hide_input=True)
    socket_token = click.prompt("Slack App-Level Token (xapp-...)", hide_input=True)
    user_id = click.prompt("Your Slack User ID (e.g. U05ABC123)")

    click.echo("\nOpening DM conversation...")
    client = WebClient(token=bot_token)

    try:
        dm_resp = client.conversations_open(users=user_id)
    except Exception as e:
        click.echo(f"Error: Could not open DM with user {user_id}: {e}", err=True)
        sys.exit(1)

    if not dm_resp.get("ok"):
        click.echo(f"Error: conversations.open failed: {dm_resp.get('error')}", err=True)
        sys.exit(1)

    dm_channel_id = dm_resp["channel"]["id"]

    code = f"{random.randint(100000, 999999)}"
    try:
        client.chat_postMessage(
            channel=dm_channel_id,
            text=(
                f":key: *claude-afk verification code*\n\n"
                f"Your code is: `{code}`\n\n"
                f"_Enter this code in your terminal to complete setup._"
            ),
        )
    except Exception as e:
        click.echo(f"Error: Could not send verification code: {e}", err=True)
        sys.exit(1)

    click.echo("Sent a verification code to your Slack DMs.")
    entered = click.prompt("Enter the 6-digit code from Slack")

    if entered.strip() != code:
        click.echo("Verification failed — code does not match.", err=True)
        sys.exit(1)

    click.echo("Verified!\n")

    expanded_home = str(Path(claude_home).expanduser())
    existing = SlackConfig.from_file()
    claude_homes = list(existing.claude_homes)
    if expanded_home not in claude_homes:
        claude_homes.append(expanded_home)

    config = SlackConfig(
        bot_token=bot_token,
        socket_mode_token=socket_token,
        user_id=user_id,
        dm_channel_id=dm_channel_id,
        timeout=existing.timeout if existing.timeout else 300,
        claude_homes=claude_homes,
    )
    config.save()
    click.echo(f"Config saved to {AFK_HOME / 'config.json'}")

    _install_hooks(claude_home)
    click.echo(f"Hooks installed in {Path(claude_home).expanduser() / 'settings.json'}")

    with contextlib.suppress(Exception):
        client.chat_postMessage(
            channel=dm_channel_id,
            text=(
                ":white_check_mark: *claude-afk is set up!*\n\n"
                "I'll send permission requests and questions here when you're AFK.\n"
                f"Claude home: `{expanded_home}`\n\n"
                "_Use `claude-afk enable <session-id>` or `claude-afk enable all` to start._"
            ),
        )

    click.echo("\nDone! Use `claude-afk enable all` to start routing to Slack.")


@main.command()
@click.argument("target")
def enable(target: str) -> None:
    """Enable Slack routing for a session ID or 'all'."""
    state = load_state()

    if target == "all":
        state["enabled"] = "all"
        save_state(state)
        click.echo("Enabled for all sessions.")
        return

    enabled = state.get("enabled", [])
    if enabled == "all":
        click.echo("Already enabled for all sessions.")
        return

    if target not in enabled:
        enabled.append(target)
    state["enabled"] = enabled
    save_state(state)
    click.echo(f"Enabled for session {target}")


@main.command()
@click.argument("target")
def disable(target: str) -> None:
    """Disable Slack routing for a session ID or 'all'."""
    state = load_state()

    if target == "all":
        state["enabled"] = []
        save_state(state)
        click.echo("Disabled for all sessions.")
        return

    enabled = state.get("enabled", [])
    if enabled == "all":
        click.echo(
            "Currently enabled for all. Use `disable all` first, then enable specific sessions."
        )
        return

    if target in enabled:
        enabled.remove(target)
    state["enabled"] = enabled
    save_state(state)
    click.echo(f"Disabled for session {target}")


@main.command()
def status() -> None:
    """Show claude-afk status — config, enabled sessions, hooks."""
    click.echo(f"claude-afk v{__version__}\n")

    config = SlackConfig.from_file()
    if not config.is_valid():
        click.echo("Not configured. Run `claude-afk setup` first.")
        return

    click.echo(f"Slack user:    {config.user_id}")
    click.echo(f"DM channel:    {config.dm_channel_id}")
    click.echo(f"Timeout:       {config.timeout}s")
    click.echo(f"Claude homes:  {', '.join(config.claude_homes) or '(none)'}")

    state = load_state()
    enabled = state.get("enabled", [])
    click.echo()
    if enabled == "all":
        click.echo("Sessions:      ALL enabled")
    elif enabled:
        click.echo(f"Sessions:      {', '.join(enabled)}")
    else:
        click.echo("Sessions:      none enabled")


@main.command()
@click.option(
    "--claude-home",
    default="~/.claude",
    help="Path to Claude Code config directory (default: ~/.claude).",
)
def uninstall(claude_home: str) -> None:
    """Remove claude-afk hooks from a Claude Code config directory."""
    expanded_home = str(Path(claude_home).expanduser())

    if _uninstall_hooks(claude_home):
        click.echo(
            f"Removed claude-afk hooks from {Path(claude_home).expanduser() / 'settings.json'}"
        )
    else:
        click.echo(
            f"No claude-afk hooks found in {Path(claude_home).expanduser() / 'settings.json'}"
        )

    # Remove from config's claude_homes list
    config = SlackConfig.from_file()
    if expanded_home in config.claude_homes:
        new_homes = [h for h in config.claude_homes if h != expanded_home]
        updated = SlackConfig(
            bot_token=config.bot_token,
            socket_mode_token=config.socket_mode_token,
            user_id=config.user_id,
            dm_channel_id=config.dm_channel_id,
            timeout=config.timeout,
            claude_homes=new_homes,
        )
        updated.save()
        click.echo(f"Removed {expanded_home} from registered Claude homes.")
