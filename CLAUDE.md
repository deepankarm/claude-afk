# CLAUDE.md

## What is claude-afk?

A CLI tool that routes Claude Code's interactive prompts (permissions, questions, plan approvals, stop notifications) to Slack DMs. Users approve/deny via emoji reactions or reply with feedback from their phone.

## Project structure

```
src/claude_afk/
  cli.py              # Click CLI: setup, enable/disable, hook subcommands
  config.py           # SlackConfig dataclass, state persistence, AFK_HOME (~/.claude-afk)
  permissions.py      # Tool policies, CC rule loading, session permission cache
  transcript.py       # JSONL transcript parsing for session metadata
  hooks/
    stop.py           # Stop hook: posts last message, waits for reply to continue session
    pretooluse.py     # PreToolUse hook: tool permissions + AskUserQuestion routing
    planapproval.py   # PermissionRequest hook: plan approval via ExitPlanMode
    notify.py         # Notification hook: one-way alerts (no reply needed)
  slack/
    bridge.py         # SlackBridge: Socket Mode + polling fallback, concurrency control
    formatting.py     # Markdown to Slack mrkdwn, message formatting, truncation
    thread.py         # Thread_ts persistence per session
```

## Development commands

```bash
uv sync                           # Install deps
uv run pytest tests/ -x -q        # Run tests (161 tests)
uv run ruff check src/ tests/     # Lint
uv run ruff format src/ tests/    # Format
```

Python >= 3.10 required. Uses `hatchling` build backend.

## How hooks work

CC fires hook commands with JSON on stdin. Hooks read it, interact with Slack, and write JSON decisions to stdout.

**Hook types and their response formats:**

| Hook | Event | Response format |
|------|-------|-----------------|
| `PreToolUse` | Tool permission, AskUserQuestion | `hookSpecificOutput.permissionDecision` = allow/deny |
| `Stop` | Claude finishes | `decision: "block"` with reason (or nothing to allow stop) |
| `PermissionRequest` | ExitPlanMode | `hookSpecificOutput.decision.behavior` = allow/deny |
| `Notification` | Completion/attention | One-way post, no response |

**Important:** PreToolUse and PermissionRequest have different JSON response schemas. Don't mix them up.

## Concurrency model

This is critical to understand. Multiple CC sessions = multiple hook processes = multiple potential Slack connections.

**Global Socket Mode lock** (`~/.claude-afk/bridge/sm.lock`):
- Only ONE bridge uses Socket Mode at a time (real-time, low latency)
- Others fall back to polling `conversations.replies` + `reactions.get` every 3 seconds
- Lock acquired with `fcntl.flock(LOCK_EX | LOCK_NB)` in `SlackBridge.__enter__`
- Released in `__exit__`. OS auto-releases if process crashes.

**Per-session lock** (`/tmp/slack_bridge_{session_id}.lock`):
- Serializes parallel PreToolUse hooks within a single session
- Session permission cache is checked inside this lock to prevent races

**Why this matters:** Socket Mode distributes events across all connected clients. Without the global lock, reactions/replies can be delivered to the wrong session's bridge, acked, and lost forever.

**Reaction ack safety:** `_handle_event` checks `item.ts == self._last_post_ts` BEFORE acking reactions. Foreign reactions are not acked, so Slack retries delivery.

## Permission system

**Tool policies** (in `permissions.py`):
- `AUTO_ALLOW`: Read, Grep, Glob, TaskCreate/Update/List/Get, Skill — no Slack prompt
- `ASK_ONCE`: Edit — prompt once per file, cached for session
- `ALWAYS_ASK`: Write, Bash, Task, WebFetch, WebSearch, NotebookEdit

**Sensitive files** always prompt even for AUTO_ALLOW tools: `.env*`, `*.key`, `*.pem`, SSH keys, credentials.json, etc.

**CC rule check**: Before prompting on Slack, the hook checks if CC already has an allow/deny rule in `~/.claude/settings.json` or project `.claude/settings.json`. If so, it skips the Slack round-trip.

**Session cache**: Only ALLOW decisions are cached (never deny). Prevents lock-out where a deny gets cached and auto-denies all subsequent uses of the same tool.

## User interaction model

- Emoji reactions for allow/deny: thumbsup/thumbsdown (and variants)
- Any text reply = deny with feedback (fed back to Claude as guidance)
- Sentinel constants `REPLY_ALLOW` / `REPLY_DENY` distinguish reactions from typed text in bridge.py

## Key files to read first

1. `bridge.py` — The core of Slack communication. Understand Socket Mode vs polling, event filtering, the global lock.
2. `pretooluse.py` — Most complex hook. Handles permissions, questions, caching, file locking.
3. `permissions.py` — Tool policies, CC rule loading, session cache.
4. `cli.py` — Hook installation into `~/.claude/settings.json`, setup flow.

## Gotchas

- `str(SomeEnum.VALUE)` returns `"SomeEnum.VALUE"` not `"VALUE"`. Always use `.value` for serialization.
- `Decision` and `ToolPolicy` use `(str, Enum)` pattern for Python 3.10 compat.
- Slack messages are truncated to 3000 chars. Long plans/diffs get cut.
- PreToolUse timeout = silent pass-through (no output). Stop timeout = allow stop.
- The per-session lock path is in `/tmp/`, not `~/.claude-afk/`. The global SM lock is in `~/.claude-afk/bridge/`.
- Hook installation deduplicates by filtering previous claude-afk entries from settings.json.

## State files

```
~/.claude-afk/
  config.json                          # Slack tokens (mode 600)
  state.json                           # Enabled sessions list
  slack/threads/{session_id}.json      # Thread_ts per session
  sessions/{session_id}/permissions.json  # Per-file permission cache
  bridge/sm.lock                       # Global Socket Mode lock
  logs/claude-afk.log                  # Debug logs
```

## Testing patterns

- `conftest.py` provides `afk_home` (tmp dir) and `sample_config` fixtures
- Bridge tests use `_make_bridge()` helper to create bridges without `__enter__`
- Hook tests mock `SlackBridge` at the import path level (lambda returning MagicMock with `__enter__/__exit__`)
- Use `capsys.readouterr().out` to capture and validate JSON output from hooks
- Permission tests use `monkeypatch.setattr(perms, "AFK_HOME", tmp_path)` for isolation
