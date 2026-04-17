---
name: aionui-multi-session
description: Operate AionUI conversations through the local WebSocket service to create, list, message, and delete sessions, and to batch-dispatch prompts across multiple conversations in parallel. Use when Codex inside AionUI needs to fan out a task plan into several sessions, bootstrap parallel workstreams, bulk-send prompts to existing or newly created conversations, or clean up programmatically managed sessions.
---

# AionUI Multi Session

## Overview

Use this skill to drive AionUI conversations from local scripts instead of clicking through the UI one session at a time.

The bundled scripts support two levels of control:

- `scripts/aionui_session.py` for single-session operations such as `create`, `list`, `send`, and `delete`
- `scripts/batch_dispatch.py` for creating or reusing many sessions and sending prompts to them concurrently

## Recommended Workflow

1. Confirm AionUI is running locally and exposing its WebSocket endpoint.
2. Decide whether the request is single-session or batch fan-out.
3. For batch work, copy the structure from `assets/batch-plan.template.json` and fill in the task list.
4. Run a dry run first to validate the plan before dispatching real work.
5. Execute the batch dispatch and return the JSON summary, especially the created conversation IDs.
6. Delete sessions only when the user explicitly asks for cleanup.

## Quick Commands

Run commands from this skill directory or reference the script paths directly.

Single-session examples:

```powershell
uv run scripts/aionui_session.py list
uv run scripts/aionui_session.py create --name "Parallel Worker A" --backend codex --workspace "D:\work\repo"
uv run scripts/aionui_session.py send --id 8f65f4b7 --message "Review the auth module and summarize risks."
```

Batch examples:

```powershell
uv run scripts/batch_dispatch.py --plan assets/batch-plan.template.json --dry-run
uv run scripts/batch_dispatch.py --plan D:\work\plans\parallel-tasks.json --max-workers 4
```

If `websocket-client` is not installed in the current Python environment, run through `uv` with the dependency:

```powershell
uv run --with websocket-client scripts/aionui_session.py list
uv run --with websocket-client scripts/batch_dispatch.py --plan assets/batch-plan.template.json --dry-run
```

## Authentication And Endpoint Handling

- Default WebSocket URL is `ws://localhost:25808/`.
- **Authentication is required.** Pass `--session-token` and `--csrf-token` when connecting to AionUI. Without them the connection will be rejected with a 401/403 error.
- Tokens are resolved in this priority order: CLI args → env vars (`AIONUI_SESSION_TOKEN`, `AIONUI_CSRF_TOKEN`) → saved cookie file (`~/.aionui_cookies.json`).
- To retrieve tokens: open AionUI in a browser → DevTools → Application → Cookies → copy `aionui-session` (session token) and `csrfToken` (CSRF token).
- **Save tokens once** so you never need to pass them again:

```powershell
uv run scripts/aionui_session.py save-cookies --session-token TOKEN --csrf-token TOKEN
```

- To remove saved tokens:

```powershell
uv run scripts/aionui_session.py clear-cookies
```

- If the connection fails with an auth error, ask the user to run `save-cookies` with fresh tokens from their browser.

## Session Modes

Control the permission level of a created session with `--session-mode`:

| Value | Meaning |
|---|---|
| `default` | Standard permission prompts (default) |
| `bypassPermissions` | Skip most permission prompts |
| `yolo` | Maximum permissions — no prompts at all |

Example:

```powershell
uv run scripts/aionui_session.py create --name "Worker A" --backend codex --workspace "D:\work" --session-mode yolo
```

## Message Dispatch

`send` is **fire-and-forget**: the script confirms the WebSocket frame was sent and returns immediately. It does not wait for the agent to finish processing. The response will be `{"status": "dispatched", ...}` — this is expected and correct.

## Batch Plan Rules

Read `references/plan-format.md` when you need the full plan schema.

Use these fields by default:

- `defaults`: shared settings for all tasks, such as `backend`, `workspace`, `type`, `session_mode`, `ws_url`, and `timeout`
- `tasks`: an array of per-session jobs
- `tasks[].id`: reuse an existing conversation instead of creating a new one
- `tasks[].name`: required when creating a new conversation
- `tasks[].message`: required unless running `--create-only`
- `tasks[].model`: required only for `type: "aionrs"`

## Operational Guidance

- Prefer one task per session when the goal is true parallel fan-out.
- Keep prompts self-contained because the script only dispatches work; it does not gather streamed completion results back into the terminal.
- Return the machine-readable JSON summary after batch dispatch so the caller can reuse conversation IDs in later steps.
- Avoid deleting sessions automatically after send unless the user explicitly wants ephemeral sessions.

## Failure Handling

- Start with `--dry-run` when building a new batch plan.
- If a create response does not expose the conversation ID in the expected shape, inspect the raw `create_response` included in the batch output before retrying.
- When a subset of tasks fails, preserve the successful conversation IDs so the user can continue from partial progress instead of starting over.
