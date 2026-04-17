#!/usr/bin/env python3
"""
Manage AionUI conversations through the local WebSocket endpoint.
"""

from __future__ import annotations

import argparse
import io
import json
import os
import sys
import time
import uuid
from typing import Any, Dict, Iterable, Optional


DEFAULT_WS_URL = "ws://localhost:25808/"
DEFAULT_TIMEOUT = 30
DEFAULT_CONVERSATION_NAME = "New Session"
DEFAULT_SESSION_MODE = "default"
COOKIE_BASE = "multica_logged_in=1; sidebar_state=true"
JSONDict = Dict[str, Any]


def _configure_stdio() -> None:
    if sys.platform != "win32":
        return
    if hasattr(sys.stdout, "buffer"):
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
    if hasattr(sys.stderr, "buffer"):
        sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8")


class AionUIError(RuntimeError):
    """Raised when an AionUI WebSocket operation fails."""


def _read_json_file(path: str) -> Any:
    with open(path, "r", encoding="utf-8") as handle:
        return json.load(handle)


def extract_conversation_id(payload: Any, expected_name: Optional[str] = None) -> Optional[str]:
    """
    Best-effort extraction of a conversation id from callback payloads.

    The exact callback shape may differ across AionUI builds, so search common
    field names recursively and prefer objects that look like conversation data.
    """

    visited: set[int] = set()

    def _looks_like_conversation(node: JSONDict) -> bool:
        if expected_name and node.get("name") == expected_name:
            return True
        conversation_markers = {
            "name",
            "type",
            "workspace",
            "extra",
            "conversation_id",
            "conversationId",
        }
        return bool(conversation_markers.intersection(node.keys()))

    def _search(node: Any) -> Optional[str]:
        node_id = id(node)
        if node_id in visited:
            return None
        visited.add(node_id)

        if isinstance(node, dict):
            for key in ("conversation_id", "conversationId"):
                value = node.get(key)
                if isinstance(value, str) and value:
                    return value

            raw_id = node.get("id")
            if isinstance(raw_id, str) and raw_id and _looks_like_conversation(node):
                return raw_id

            for value in node.values():
                found = _search(value)
                if found:
                    return found

        if isinstance(node, list):
            for item in node:
                found = _search(item)
                if found:
                    return found

        return None

    return _search(payload)


class AionUISessionManager:
    def __init__(
        self,
        ws_url: str = DEFAULT_WS_URL,
        timeout: int = DEFAULT_TIMEOUT,
        session_token: Optional[str] = None,
        csrf_token: Optional[str] = None,
    ) -> None:
        self.ws_url = ws_url
        self.timeout = timeout
        self.session_token = session_token
        self.csrf_token = csrf_token
        self.ws = None

    def connect(self) -> None:
        try:
            from websocket import create_connection
        except ImportError as exc:
            raise AionUIError(
                "Missing dependency 'websocket-client'. Install it or run with "
                "'uv run --with websocket-client ...'."
            ) from exc

        headers = {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko)"
            ),
            "Origin": "http://localhost:25808",
            "Cache-Control": "no-cache",
            "Pragma": "no-cache",
            "Cookie": self._build_cookie_header(),
        }

        try:
            self.ws = create_connection(
                self.ws_url,
                timeout=self.timeout,
                ping_interval=30,
                ping_timeout=10,
                header=headers,
            )
        except Exception as exc:
            raise AionUIError(f"Failed to connect to {self.ws_url}: {exc}") from exc

    def disconnect(self) -> None:
        if self.ws is not None:
            try:
                self.ws.close()
            finally:
                self.ws = None

    def list_conversations(self, page: int = 0, page_size: int = 10000) -> JSONDict:
        request_id = self._generate_id("database.get-user-conversations")
        payload = {"page": page, "pageSize": page_size}
        return self._send_request("subscribe-database.get-user-conversations", request_id, payload)

    def create_conversation(
        self,
        name: str,
        conv_type: str = "acp",
        backend: str = "claude",
        workspace: str = "",
        session_mode: str = DEFAULT_SESSION_MODE,
        model: Optional[JSONDict] = None,
    ) -> JSONDict:
        request_id = self._generate_id("create-conversation")

        if conv_type == "acp":
            payload: JSONDict = {
                "type": "acp",
                "name": name,
                "extra": {
                    "workspace": workspace,
                    "customWorkspace": bool(workspace),
                    "defaultFiles": [],
                    "backend": backend,
                    "agentName": self._get_agent_name(backend),
                    "cliPath": backend,
                    "sessionMode": session_mode,
                },
            }
        elif conv_type == "aionrs":
            if not model:
                raise AionUIError("Model configuration is required for aionrs conversations.")
            payload = {
                "type": "aionrs",
                "name": name,
                "model": model,
                "extra": {
                    "workspace": workspace,
                    "customWorkspace": bool(workspace),
                    "defaultFiles": [],
                    "sessionMode": session_mode,
                },
            }
        else:
            raise AionUIError(f"Unknown conversation type: {conv_type}")

        return self._send_request("subscribe-create-conversation", request_id, payload)

    def send_message(
        self,
        conversation_id: str,
        message: str,
        files: Optional[list[Any]] = None,
    ) -> JSONDict:
        request_id = self._generate_id("chat.send.message")
        payload = {
            "input": message,
            "msg_id": uuid.uuid4().hex[:8],
            "conversation_id": conversation_id,
            "files": files or [],
        }
        return self._send_request("subscribe-chat.send.message", request_id, payload)

    def delete_conversation(self, conversation_id: str) -> JSONDict:
        request_id = self._generate_id("remove-conversation")
        return self._send_request(
            "subscribe-remove-conversation",
            request_id,
            {"id": conversation_id},
        )

    def _build_cookie_header(self) -> str:
        cookie_parts = [COOKIE_BASE]
        if self.session_token:
            cookie_parts.append(f"aionui-session={self.session_token}")
        if self.csrf_token:
            cookie_parts.append(f"csrfToken={self.csrf_token}")
        return "; ".join(cookie_parts)

    def _generate_id(self, prefix: str) -> str:
        return f"{prefix}{uuid.uuid4().hex[:8]}"

    def _send_request(self, name: str, request_id: str, data: JSONDict) -> JSONDict:
        if self.ws is None:
            raise AionUIError("WebSocket is not connected.")

        request = {"name": name, "data": {"id": request_id, "data": data}}
        expected_callback = f"subscribe.callback-{name.replace('subscribe-', '')}{request_id}"
        started = time.time()

        try:
            self.ws.send(json.dumps(request))
        except Exception as exc:
            raise AionUIError(f"Failed to send request '{name}': {exc}") from exc

        while time.time() - started < self.timeout:
            try:
                self.ws.settimeout(1)
                raw_message = self.ws.recv()
            except Exception as exc:
                if "timed out" in str(exc).lower():
                    continue
                raise AionUIError(f"Error receiving response for '{name}': {exc}") from exc

            if not raw_message:
                continue

            try:
                decoded = json.loads(raw_message)
            except json.JSONDecodeError:
                continue

            if decoded.get("name") == expected_callback:
                payload = decoded.get("data", decoded)
                if isinstance(payload, dict):
                    return payload
                return {"data": payload}

        raise AionUIError(
            f"Timed out after {self.timeout}s waiting for callback '{expected_callback}'."
        )

    @staticmethod
    def _get_agent_name(backend: str) -> str:
        mapping = {
            "claude": "Claude Code",
            "codex": "Codex",
            "gemini": "Gemini",
            "opencode": "OpenCode",
        }
        return mapping.get(backend, backend)


def _emit_json(payload: Any, stream: Any = None) -> None:
    stream = sys.stdout if stream is None else stream
    stream.write(json.dumps(payload, ensure_ascii=False, indent=2))
    stream.write("\n")


def _normalize_files_arg(files_json: Optional[str], files_file: Optional[str]) -> list[Any]:
    if files_json and files_file:
        raise AionUIError("Use only one of --files-json or --files-file.")
    if files_json:
        try:
            value = json.loads(files_json)
        except json.JSONDecodeError as exc:
            raise AionUIError(f"Invalid JSON passed to --files-json: {exc}") from exc
        if not isinstance(value, list):
            raise AionUIError("--files-json must decode to a JSON array.")
        return value
    if files_file:
        value = _read_json_file(files_file)
        if not isinstance(value, list):
            raise AionUIError("--files-file must contain a JSON array.")
        return value
    return []


def _load_model(model_json: Optional[str], model_file: Optional[str]) -> Optional[JSONDict]:
    if model_json and model_file:
        raise AionUIError("Use only one of --model or --model-file.")
    if model_json:
        try:
            value = json.loads(model_json)
        except json.JSONDecodeError as exc:
            raise AionUIError(f"Invalid JSON passed to --model: {exc}") from exc
        if not isinstance(value, dict):
            raise AionUIError("--model must decode to a JSON object.")
        return value
    if model_file:
        value = _read_json_file(model_file)
        if not isinstance(value, dict):
            raise AionUIError("--model-file must contain a JSON object.")
        return value
    return None


def _manager_from_args(args: argparse.Namespace) -> AionUISessionManager:
    return AionUISessionManager(
        ws_url=args.ws_url,
        timeout=args.timeout,
        session_token=args.session_token,
        csrf_token=args.csrf_token,
    )


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="AionUI session manager")
    parser.add_argument("action", choices=["create", "delete", "list", "send"])
    parser.add_argument(
        "--ws-url",
        default=os.getenv("AIONUI_WS_URL", DEFAULT_WS_URL),
        help=f"WebSocket URL (default: {DEFAULT_WS_URL})",
    )
    parser.add_argument(
        "--timeout",
        type=int,
        default=int(os.getenv("AIONUI_TIMEOUT", str(DEFAULT_TIMEOUT))),
        help=f"Timeout in seconds (default: {DEFAULT_TIMEOUT})",
    )
    parser.add_argument(
        "--session-token",
        default=os.getenv("AIONUI_SESSION_TOKEN"),
        help="AionUI session JWT token",
    )
    parser.add_argument(
        "--csrf-token",
        default=os.getenv("AIONUI_CSRF_TOKEN"),
        help="CSRF token",
    )

    parser.add_argument(
        "--name",
        default=DEFAULT_CONVERSATION_NAME,
        help=f"Conversation name (default: {DEFAULT_CONVERSATION_NAME})",
    )
    parser.add_argument("--type", choices=["acp", "aionrs"], default="acp")
    parser.add_argument(
        "--backend",
        choices=["claude", "codex", "gemini", "opencode"],
        default="claude",
    )
    parser.add_argument("--workspace", default="", help="Workspace path")
    parser.add_argument(
        "--session-mode",
        choices=["default", "bypassPermissions", "yolo"],
        default=DEFAULT_SESSION_MODE,
    )
    parser.add_argument("--model", help="Inline JSON string for aionrs model config")
    parser.add_argument("--model-file", help="Path to a JSON file for aionrs model config")

    parser.add_argument("--id", help="Conversation ID for delete/send")
    parser.add_argument("--message", help="Message content for send")
    parser.add_argument("--files-json", help="JSON array of files for send")
    parser.add_argument("--files-file", help="Path to a JSON file containing files for send")
    parser.add_argument("--page", type=int, default=0, help="List page number")
    parser.add_argument("--page-size", type=int, default=10000, help="List page size")
    return parser


def main(argv: Optional[Iterable[str]] = None) -> int:
    _configure_stdio()
    parser = _build_parser()
    args = parser.parse_args(list(argv) if argv is not None else None)

    manager = _manager_from_args(args)

    try:
        manager.connect()

        if args.action == "create":
            model = _load_model(args.model, args.model_file)
            result = manager.create_conversation(
                name=args.name,
                conv_type=args.type,
                backend=args.backend,
                workspace=args.workspace,
                session_mode=args.session_mode,
                model=model,
            )
            _emit_json(result)
            return 0

        if args.action == "list":
            result = manager.list_conversations(page=args.page, page_size=args.page_size)
            _emit_json(result)
            return 0

        if args.action == "delete":
            if not args.id:
                raise AionUIError("--id is required for delete.")
            result = manager.delete_conversation(args.id)
            _emit_json(result)
            return 0

        if args.action == "send":
            if not args.id:
                raise AionUIError("--id is required for send.")
            if not args.message:
                raise AionUIError("--message is required for send.")
            files = _normalize_files_arg(args.files_json, args.files_file)
            result = manager.send_message(args.id, args.message, files=files)
            _emit_json(result)
            return 0

        raise AionUIError(f"Unknown action: {args.action}")
    except AionUIError as exc:
        _emit_json({"error": str(exc)}, stream=sys.stderr)
        return 1
    finally:
        manager.disconnect()


if __name__ == "__main__":
    raise SystemExit(main())
