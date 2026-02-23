# claude-afk

You're running Claude Code on your terminal. It's writing code, you're approving. But you have groceries to pick up, a dentist appointment, or a filter coffee waiting at Rameshwaram Cafe. The coding shouldn't stop - Claude writes the code anyway, you just approve. Why sit in front of the computer? Go touch grass.

`claude-afk` routes Claude's prompts to your Slack DMs so you can keep things moving from your phone. Proceed with [Caution](#caution).

## Install

```bash
pip install claude-afk
```

## Slack app setup (One time, for admins)

1. Go to [api.slack.com/apps](https://api.slack.com/apps) → **Create New App** → **From an app manifest**
2. Paste the manifest:

    <details>
    <summary>Slack app manifest (click to expand)</summary>

    ```json
    {
        "display_information": {
            "name": "Claude AFK",
            "description": "Control Claude Code remotely via Slack",
            "background_color": "#505870"
        },
        "features": {
            "app_home": {
                "messages_tab_enabled": true,
                "messages_tab_read_only_enabled": false
            },
            "bot_user": {
                "display_name": "Claude AFK",
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

This prompts for your Slack tokens and user ID, verifies the connection by sending a code to your DMs, and installs hooks into Claude Code's `~/.claude/settings.json`.

```bash
✗ claude-afk setup

Slack Bot Token (xoxb-...): <xoxb-your-bot-token>
Slack App-Level Token (xapp-...): <xapp-your-app-level-token>
Your Slack User ID (e.g. U05ABC123): <your-user-id>

Opening DM conversation...
Sent a verification code to your Slack DMs.
Enter the 6-digit code from Slack: <code-you-just-received>
Verified!

Config saved to .../.claude-afk/config.json
Hooks installed in .../.claude/settings.json

Done! Use `claude-afk enable all` to start routing to Slack.
```

### 2. Enable and keep coding

```bash
claude-afk enable <session-id>   # or `claude-afk enable all`
```

Then keep using Claude Code like before:

```bash
claude --resume <session-id>
```

When Claude needs a permission, asks a question, or finishes - it gets routed to your Slack DMs. Reply in the thread to respond.

<!-- TODO: add screenshot -->

### 3. When you're back, disable

```bash
claude-afk disable <session-id>    # disable one session
claude-afk disable all             # disable all sessions
claude --resume <session-id>       # continue like before
```

### Other commands

```bash
claude-afk status                              # show config and enabled sessions
claude-afk add-home ~/.claude-personal         # register another Claude Code config dir
claude-afk uninstall --claude-home ~/.claude   # remove hooks from one home
claude-afk uninstall                           # remove hooks from all registered homes
```

## How it works

claude-afk installs [hooks](https://docs.anthropic.com/en/docs/claude-code/hooks) into Claude Code that route interactive prompts to your Slack DMs:

- **Stop** - when Claude finishes, posts the last message to Slack. Reply in the thread to continue the session.
- **PreToolUse** - tool permission requests and `AskUserQuestion` prompts are forwarded to Slack. Reply to approve/deny or answer.
- **Notification** - one-way DM when Claude needs attention.

## Caution

This is new. Please proceed with care.

- **`settings.json` modification** - `claude-afk` merges hooks into your Claude Code config. It's tested to preserve existing settings, but back up your `settings.json` to be safe.
- **Security** - this effectively gives you remote control of your machine through Slack. Anyone with access to your Slack DM can approve tool executions.
- **Not fully tested** - edge cases exist. If something breaks, `claude-afk uninstall` removes all hooks cleanly.
