# AionUI Session Manager

WebSocket client for managing AionUI conversations programmatically.

## Features

- Create conversations (acp or aionrs types)
- Send messages to conversations
- Delete conversations
- List all conversations
- Support for multiple backends (claude, codex, gemini, opencode)
- Configurable session modes (default, bypassPermissions, yolo)

## Installation

```bash
pip install websocket-client
```

## Usage

### Create a conversation

```bash
# ACP type (built-in backends)
python scripts/session.py create --name "My Session" --backend claude --workspace "D:\my-project"

# AIONRS type (custom model)
python scripts/session.py create --type aionrs --name "Custom Session" --model '{"id":"xxx","platform":"custom",...}'
```

### List conversations

```bash
python scripts/session.py list
```

### Send a message

```bash
python scripts/session.py send --id 8f65f4b7 --message "Hello"
```

### Delete a conversation

```bash
python scripts/session.py delete --id 8f65f4b7
```

## Options

### Global Options
- `--ws-url`: WebSocket URL (default: ws://localhost:25808/)
- `--timeout`: Timeout in seconds (default: 30)

### Create Options
- `--name`: Conversation name (default: 新会话)
- `--type`: Conversation type - acp or aionrs (default: acp)
- `--backend`: Backend for acp type - claude, codex, gemini, opencode (default: claude)
- `--workspace`: Workspace path (default: empty)
- `--session-mode`: Session mode - default, bypassPermissions, yolo (default: default)
- `--model`: Model config JSON string (required for aionrs type)

### Delete/Send Options
- `--id`: Conversation ID (required)
- `--message`: Message content (required for send)

## Output

All results are output as JSON to stdout, making it easy to parse in scripts or other tools.

Errors are output to stderr as JSON with an "error" field.

## License

MIT
