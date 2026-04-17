# Batch Plan Format

Use this reference when preparing JSON for `scripts/batch_dispatch.py`.

## Shape

```json
{
  "defaults": {
    "type": "acp",
    "backend": "codex",
    "workspace": "D:\\path\\to\\repo",
    "session_mode": "default",
    "ws_url": "ws://localhost:25808/",
    "timeout": 30
  },
  "tasks": [
    {
      "name": "Worker A",
      "message": "Inspect the auth module and return findings only."
    },
    {
      "id": "8f65f4b7",
      "message": "Continue from the previous thread and produce a patch plan."
    }
  ]
}
```

## Fields

- `defaults`: optional shared settings applied to every task before task-level overrides
- `tasks`: required array of per-session work items
- `tasks[].id`: existing conversation id to reuse; skip creation when present
- `tasks[].name`: conversation name used when creating a new session
- `tasks[].message`: prompt sent into the session; optional only with `--create-only`
- `tasks[].type`: `acp` or `aionrs`
- `tasks[].backend`: for `acp`, one of `claude`, `codex`, `gemini`, `opencode`
- `tasks[].workspace`: workspace path for the conversation
- `tasks[].session_mode`: `default`, `bypassPermissions`, or `yolo`
- `tasks[].model`: JSON object required for `aionrs`
- `tasks[].files`: JSON array passed through as the `files` field on send

## Accepted Aliases

The batch script also accepts these camelCase aliases:

- `sessionMode` -> `session_mode`
- `wsUrl` -> `ws_url`
- `conversationId` -> `id`

## Notes

- Prefer unique task names when creating many new sessions in one run.
- The script emits raw `create_response` and `send_response` payloads so you can inspect callback shapes when AionUI changes.
- Dispatch is concurrent, but completion tracking still happens inside the AionUI UI; the script only creates sessions and sends prompts.
