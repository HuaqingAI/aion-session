#!/usr/bin/env python3
"""
AionUI Session Manager - WebSocket client for managing AionUI conversations
"""

import json
import sys
import argparse
import uuid
import time
from typing import Optional, Dict, Any
from websocket import create_connection, WebSocketException

# Fix encoding for Windows
if sys.platform == 'win32':
    import io
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

class AionUISessionManager:
    def __init__(self, ws_url: str = "ws://localhost:25808/", timeout: int = 30,
                 session_token: Optional[str] = None, csrf_token: Optional[str] = None):
        self.ws_url = ws_url
        self.timeout = timeout
        self.session_token = session_token
        self.csrf_token = csrf_token
        self.ws = None

    def connect(self):
        """Connect to WebSocket server"""
        try:
            headers = {
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
                "Origin": "http://localhost:25808",
                "Cache-Control": "no-cache",
                "Pragma": "no-cache"
            }

            cookie_str = "multica_logged_in=1; sidebar_state=true"
            if self.session_token:
                cookie_str += f"; aionui-session={self.session_token}"
            if self.csrf_token:
                cookie_str += f"; csrfToken={self.csrf_token}"

            headers["Cookie"] = cookie_str

            self.ws = create_connection(
                self.ws_url,
                timeout=self.timeout,
                ping_interval=30,
                ping_timeout=10,
                header=headers
            )
        except Exception as e:
            self._error(f"Failed to connect to {self.ws_url}: {e}")

    def disconnect(self):
        """Close WebSocket connection"""
        if self.ws:
            self.ws.close()

    def _generate_id(self, prefix: str) -> str:
        """Generate unique ID with prefix"""
        return f"{prefix}{uuid.uuid4().hex[:8]}"

    def _send_request(self, name: str, request_id: str, data: Dict[str, Any]) -> Dict[str, Any]:
        """Send request and wait for callback response"""
        payload = {
            "name": name,
            "data": {
                "id": request_id,
                "data": data
            }
        }

        try:
            self.ws.send(json.dumps(payload))
        except Exception as e:
            self._error(f"Failed to send request: {e}")

        # Wait for callback response
        expected_callback = f"subscribe.callback-{name.replace('subscribe-', '')}{request_id}"
        start_time = time.time()

        while time.time() - start_time < self.timeout:
            try:
                self.ws.settimeout(1)
                response = self.ws.recv()
                if not response:
                    continue
                msg = json.loads(response)

                if msg.get("name") == expected_callback:
                    return msg.get("data", msg)
            except json.JSONDecodeError:
                continue
            except Exception as e:
                if "timed out" not in str(e).lower():
                    self._error(f"Error receiving response: {e}")
                continue

        self._error(f"Timeout waiting for response (expected: {expected_callback})")

    def create_conversation(self, name: str, conv_type: str = "acp",
                           backend: str = "claude", workspace: str = "",
                           session_mode: str = "default", model: Optional[Dict] = None) -> Dict[str, Any]:
        """Create a new conversation"""
        request_id = self._generate_id("create-conversation")

        if conv_type == "acp":
            data = {
                "type": "acp",
                "name": name,
                "extra": {
                    "workspace": workspace,
                    "customWorkspace": bool(workspace),
                    "defaultFiles": [],
                    "backend": backend,
                    "agentName": self._get_agent_name(backend),
                    "cliPath": backend,
                    "sessionMode": session_mode
                }
            }
        elif conv_type == "aionrs":
            if not model:
                self._error("Model configuration required for aionrs type")
            data = {
                "type": "aionrs",
                "name": name,
                "model": model,
                "extra": {
                    "workspace": workspace,
                    "customWorkspace": bool(workspace),
                    "defaultFiles": [],
                    "sessionMode": session_mode
                }
            }
        else:
            self._error(f"Unknown conversation type: {conv_type}")

        return self._send_request("subscribe-create-conversation", request_id, data)

    def delete_conversation(self, conversation_id: str) -> Dict[str, Any]:
        """Delete a conversation"""
        request_id = self._generate_id("remove-conversation")
        data = {"id": conversation_id}
        return self._send_request("subscribe-remove-conversation", request_id, data)

    def list_conversations(self, page: int = 0, page_size: int = 10000) -> Dict[str, Any]:
        """List all conversations"""
        request_id = self._generate_id("database.get-user-conversations")
        data = {"page": page, "pageSize": page_size}
        return self._send_request("subscribe-database.get-user-conversations", request_id, data)

    def send_message(self, conversation_id: str, message: str, files: Optional[list] = None) -> Dict[str, Any]:
        """Send a message to a conversation"""
        request_id = self._generate_id("chat.send.message")
        msg_id = uuid.uuid4().hex[:8]

        data = {
            "input": message,
            "msg_id": msg_id,
            "conversation_id": conversation_id,
            "files": files or []
        }

        return self._send_request("subscribe-chat.send.message", request_id, data)

    @staticmethod
    def _get_agent_name(backend: str) -> str:
        """Get agent name for backend"""
        mapping = {
            "claude": "Claude Code",
            "codex": "Codex",
            "gemini": "Gemini",
            "opencode": "OpenCode"
        }
        return mapping.get(backend, backend)

    @staticmethod
    def _output(data: Dict[str, Any]):
        """Output JSON to stdout"""
        output = json.dumps(data, ensure_ascii=False, indent=2)
        sys.stdout.write(output)
        sys.stdout.write('\n')

    @staticmethod
    def _error(message: str):
        """Output error to stderr and exit"""
        print(json.dumps({"error": message}, ensure_ascii=False), file=sys.stderr)
        sys.exit(1)


def main():
    parser = argparse.ArgumentParser(description="AionUI Session Manager")
    parser.add_argument("action", choices=["create", "delete", "list", "send"],
                       help="Action to perform")
    parser.add_argument("--ws-url", default="ws://localhost:25808/",
                       help="WebSocket URL (default: ws://localhost:25808/)")
    parser.add_argument("--timeout", type=int, default=30,
                       help="Timeout in seconds (default: 30)")
    parser.add_argument("--session-token", help="AionUI session JWT token")
    parser.add_argument("--csrf-token", help="CSRF token")

    # Create options
    parser.add_argument("--name", default="新会话",
                       help="Conversation name (default: 新会话)")
    parser.add_argument("--type", choices=["acp", "aionrs"], default="acp",
                       help="Conversation type (default: acp)")
    parser.add_argument("--backend", choices=["claude", "codex", "gemini", "opencode"],
                       default="claude", help="Backend for acp type (default: claude)")
    parser.add_argument("--workspace", default="",
                       help="Workspace path (default: empty)")
    parser.add_argument("--session-mode", choices=["default", "bypassPermissions", "yolo"],
                       default="default", help="Session mode (default: default)")
    parser.add_argument("--model", help="Model config JSON string (required for aionrs type)")

    # Delete/Send options
    parser.add_argument("--id", help="Conversation ID (required for delete/send)")
    parser.add_argument("--message", help="Message content (required for send)")

    args = parser.parse_args()

    manager = AionUISessionManager(
        ws_url=args.ws_url,
        timeout=args.timeout,
        session_token=args.session_token,
        csrf_token=args.csrf_token
    )

    try:
        manager.connect()

        if args.action == "create":
            model = None
            if args.type == "aionrs":
                if not args.model:
                    manager._error("--model is required for aionrs type")
                try:
                    model = json.loads(args.model)
                except json.JSONDecodeError as e:
                    manager._error(f"Invalid model JSON: {e}")

            result = manager.create_conversation(
                name=args.name,
                conv_type=args.type,
                backend=args.backend,
                workspace=args.workspace,
                session_mode=args.session_mode,
                model=model
            )
            manager._output(result)

        elif args.action == "delete":
            if not args.id:
                manager._error("--id is required for delete action")
            result = manager.delete_conversation(args.id)
            manager._output(result)

        elif args.action == "list":
            result = manager.list_conversations()
            manager._output(result)

        elif args.action == "send":
            if not args.id:
                manager._error("--id is required for send action")
            if not args.message:
                manager._error("--message is required for send action")
            result = manager.send_message(args.id, args.message)
            manager._output(result)

    finally:
        manager.disconnect()


if __name__ == "__main__":
    main()
