# claude-afk

Control [Claude Code](https://docs.anthropic.com/en/docs/claude-code) remotely via Slack — approve permissions, answer questions, and continue sessions while AFK.

## Install

```bash
pip install claude-afk
```

## Slack app setup

1. Go to [api.slack.com/apps](https://api.slack.com/apps) → **Create New App** → **From an app manifest**
2. Paste the manifest:

    <details>
    <summary>Slack app manifest (click to expand)</summary>

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

    </details>

3. Install the app to your workspace
4. Grab the tokens:
   - **Bot Token** (`xoxb-...`): OAuth & Permissions → Bot User OAuth Token
   - **App-Level Token** (`xapp-...`): Basic Information → App-Level Tokens → Generate (scope: `connections:write`)
5. Find your **Slack User ID**: click your profile → three dots → Copy member ID

## Usage

### 1. Run setup

```bash
claude-afk setup
```

This prompts for your Slack tokens and user ID, verifies the connection by sending a code to your DMs, and installs hooks into Claude Code's `~/.claude/settings.json`.

Re-running `setup` preserves existing values — press Enter to keep them.

### 2. Enable a session

```bash
claude-afk enable <session-id>
```

Now when Claude stops, needs a permission, or asks a question in that session, it gets routed to your Slack DMs. Reply in the thread to respond.

<!-- TODO: add screenshot -->

### 3. Optionally, enable all sessions

```bash
claude-afk enable all
```

Routes every Claude Code session to Slack. Useful if you're stepping away and have multiple sessions running.

### 4. When you're back, disable

```bash
claude-afk disable <session-id>    # disable one session
claude-afk disable all              # disable everything
```

### Other commands

```bash
claude-afk status                              # show config and enabled sessions
claude-afk add-home ~/.claude-personal         # register another Claude Code config dir
claude-afk uninstall --claude-home ~/.claude    # remove hooks from one home
claude-afk uninstall                           # remove hooks from all registered homes
```

## How it works

claude-afk installs [hooks](https://docs.anthropic.com/en/docs/claude-code/hooks) into Claude Code that route interactive prompts to your Slack DMs:

- **Stop** — when Claude finishes, posts the last message to Slack. Reply in the thread to continue the session.
- **PreToolUse** — tool permission requests and `AskUserQuestion` prompts are forwarded to Slack. Reply to approve/deny or answer.
- **Notification** — one-way DM when Claude needs attention.

## Caution

This is alpha software. Proceed with care.

- **`settings.json` modification** — claude-afk merges hooks into your Claude Code config. It's tested to preserve existing settings, but back up your `settings.json` if you're cautious.
- **Security** — this effectively gives you remote control of your machine through Slack. Anyone with access to your Slack bot tokens or your DM thread can approve tool executions. Treat your tokens like passwords.
- **Not fully tested** — edge cases exist. If something breaks, `claude-afk uninstall` removes all hooks cleanly.
