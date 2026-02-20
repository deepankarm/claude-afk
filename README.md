# claude-afk

Control [Claude Code](https://docs.anthropic.com/en/docs/claude-code) remotely via Slack — approve permissions, answer questions, and continue sessions while AFK.

## How it works

claude-afk installs [hooks](https://docs.anthropic.com/en/docs/claude-code/hooks) into Claude Code that route interactive prompts to your Slack DMs:

- **Stop** — when Claude finishes, posts the last message to Slack. Reply in the thread to continue the session.
- **PreToolUse** — tool permission requests and `AskUserQuestion` prompts are forwarded to Slack. Reply to approve/deny or answer.
- **Notification** — one-way DM when Claude needs attention.

## Install

```bash
uv tool install claude-afk            # or: pip install claude-afk
```

## Slack app setup

1. Go to [api.slack.com/apps](https://api.slack.com/apps) → **Create New App** → **From an app manifest**
2. Paste this manifest:

```json
{
    "display_information": {
        "name": "Claude Code Bridge",
        "description": "Claude Code and Slack bridge",
        "background_color": "#505870"
    },
    "features": {
        "app_home": {
            "messages_tab_enabled": true,
            "messages_tab_read_only_enabled": false
        },
        "bot_user": {
            "display_name": "Claude Code Bridge",
            "always_online": false
        }
    },
    "oauth_config": {
        "scopes": {
            "bot": [
                "chat:write",
                "im:history",
                "im:write"
            ]
        }
    },
    "settings": {
        "event_subscriptions": {
            "bot_events": [
                "message.im"
            ]
        },
        "interactivity": {
            "is_enabled": true
        },
        "org_deploy_enabled": false,
        "socket_mode_enabled": true,
        "token_rotation_enabled": false
    }
}
```

3. Install the app to your workspace
4. Grab the tokens:
   - **Bot Token** (`xoxb-...`): OAuth & Permissions → Bot User OAuth Token
   - **App-Level Token** (`xapp-...`): Basic Information → App-Level Tokens → Generate (scope: `connections:write`)
5. Find your **Slack User ID**: click your profile → three dots → Copy member ID

## Setup

```bash
claude-afk setup                       # prompts for tokens + verifies via Slack DM
```

Re-running `setup` preserves existing values — just press Enter to keep them.

## Usage

```bash
claude-afk enable all                  # route all sessions to Slack
claude-afk enable <session-id>         # route a specific session
claude-afk disable <session-id>        # stop routing a session
claude-afk disable all                 # stop routing everything
claude-afk status                      # show config and enabled sessions
```

### Multiple Claude homes

```bash
claude-afk add-home ~/.claude-personal # register another Claude Code config dir
claude-afk uninstall --claude-home ~/.claude-personal  # remove one
claude-afk uninstall                   # remove hooks from all registered homes
```

## Development

```bash
git clone https://github.com/deepankarm/claude-afk.git
cd claude-afk
uv sync
uv run pytest tests/ -v
```

## License

Apache-2.0
