#!/usr/bin/env python3
"""
Create or reuse multiple AionUI conversations and send prompts in parallel.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any, Dict, Iterable, Optional

from aionui_session import (
    AionUIError,
    AionUISessionManager,
    DEFAULT_SESSION_MODE,
    DEFAULT_TIMEOUT,
    DEFAULT_WS_URL,
    extract_conversation_id,
)


JSONDict = Dict[str, Any]
TASK_ALIASES = {
    "sessionMode": "session_mode",
    "wsUrl": "ws_url",
    "conversationId": "id",
}


def _emit_json(payload: Any, stream: Any = None) -> None:
    stream = sys.stdout if stream is None else stream
    stream.write(json.dumps(payload, ensure_ascii=False, indent=2))
    stream.write("\n")


def _read_json(path: str) -> Any:
    with open(path, "r", encoding="utf-8") as handle:
        return json.load(handle)


def _normalize_mapping(raw: Any) -> JSONDict:
    if raw is None:
        return {}
    if not isinstance(raw, dict):
        raise AionUIError("Expected a JSON object.")

    normalized: JSONDict = {}
    for key, value in raw.items():
        normalized[TASK_ALIASES.get(key, key)] = value
    return normalized


def _load_plan(plan_path: Optional[str], plan_json: Optional[str]) -> JSONDict:
    if bool(plan_path) == bool(plan_json):
        raise AionUIError("Provide exactly one of --plan or --plan-json.")

    plan = _read_json(plan_path) if plan_path else json.loads(plan_json)
    if not isinstance(plan, dict):
        raise AionUIError("Batch plan must be a JSON object.")

    defaults = _normalize_mapping(plan.get("defaults"))
    tasks_raw = plan.get("tasks")
    if not isinstance(tasks_raw, list) or not tasks_raw:
        raise AionUIError("Batch plan must include a non-empty 'tasks' array.")

    tasks = []
    for index, raw_task in enumerate(tasks_raw):
        task = _normalize_mapping(raw_task)
        if not task.get("id") and not task.get("name"):
            raise AionUIError(f"Task {index} requires either 'id' or 'name'.")
        tasks.append(task)

    return {"defaults": defaults, "tasks": tasks}


def _resolve_defaults(plan_defaults: JSONDict, args: argparse.Namespace) -> JSONDict:
    resolved = dict(plan_defaults)
    if args.ws_url:
        resolved["ws_url"] = args.ws_url
    if args.timeout is not None:
        resolved["timeout"] = args.timeout
    if args.session_token:
        resolved["session_token"] = args.session_token
    if args.csrf_token:
        resolved["csrf_token"] = args.csrf_token
    if args.default_workspace:
        resolved["workspace"] = args.default_workspace
    if args.default_backend:
        resolved["backend"] = args.default_backend
    if args.default_session_mode:
        resolved["session_mode"] = args.default_session_mode
    return resolved


def _resolved_task(base_defaults: JSONDict, raw_task: JSONDict, create_only: bool) -> JSONDict:
    task = dict(base_defaults)
    task.update(raw_task)
    task.setdefault("type", "acp")
    task.setdefault("backend", "claude")
    task.setdefault("workspace", "")
    task.setdefault("session_mode", DEFAULT_SESSION_MODE)
    task.setdefault("ws_url", DEFAULT_WS_URL)
    task.setdefault("timeout", DEFAULT_TIMEOUT)
    task.setdefault("files", [])

    if not isinstance(task["files"], list):
        raise AionUIError("Task field 'files' must be a JSON array when provided.")

    if task["type"] == "aionrs" and not task.get("model"):
        raise AionUIError("aionrs tasks require a 'model' object.")

    if not create_only and not task.get("message"):
        raise AionUIError("Each task requires 'message' unless --create-only is set.")

    return task


def _run_task(task_index: int, task: JSONDict, create_only: bool) -> JSONDict:
    manager = AionUISessionManager(
        ws_url=str(task.get("ws_url", DEFAULT_WS_URL)),
        timeout=int(task.get("timeout", DEFAULT_TIMEOUT)),
        session_token=task.get("session_token"),
        csrf_token=task.get("csrf_token"),
    )

    result: JSONDict = {
        "task_index": task_index,
        "name": task.get("name"),
        "requested_id": task.get("id"),
        "created": False,
        "sent": False,
        "status": "ok",
    }

    try:
        manager.connect()

        conversation_id = task.get("id")
        if conversation_id:
            result["conversation_id"] = conversation_id
        else:
            create_response = manager.create_conversation(
                name=str(task["name"]),
                conv_type=str(task.get("type", "acp")),
                backend=str(task.get("backend", "claude")),
                workspace=str(task.get("workspace", "")),
                session_mode=str(task.get("session_mode", DEFAULT_SESSION_MODE)),
                model=task.get("model"),
            )
            result["create_response"] = create_response
            result["created"] = True
            conversation_id = extract_conversation_id(create_response, expected_name=task.get("name"))
            result["conversation_id"] = conversation_id

            if not conversation_id and not create_only:
                raise AionUIError(
                    "Conversation created but id could not be extracted from callback payload."
                )

        if not create_only:
            send_response = manager.send_message(
                conversation_id=str(conversation_id),
                message=str(task["message"]),
                files=task.get("files"),
            )
            result["send_response"] = send_response
            result["sent"] = True

        return result
    except AionUIError as exc:
        result["status"] = "error"
        result["error"] = str(exc)
        return result
    finally:
        manager.disconnect()


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Dispatch many AionUI session tasks in parallel")
    parser.add_argument("--plan", help="Path to a batch plan JSON file")
    parser.add_argument("--plan-json", help="Inline batch plan JSON string")
    parser.add_argument("--max-workers", type=int, default=4, help="Maximum parallel workers")
    parser.add_argument("--create-only", action="store_true", help="Create sessions without sending")
    parser.add_argument("--dry-run", action="store_true", help="Print resolved plan without executing")

    parser.add_argument(
        "--ws-url",
        default=os.getenv("AIONUI_WS_URL"),
        help="Override ws_url for every task",
    )
    parser.add_argument(
        "--timeout",
        type=int,
        default=int(os.getenv("AIONUI_TIMEOUT")) if os.getenv("AIONUI_TIMEOUT") else None,
        help="Override timeout for every task",
    )
    parser.add_argument(
        "--session-token",
        default=os.getenv("AIONUI_SESSION_TOKEN"),
        help="Override session token for every task",
    )
    parser.add_argument(
        "--csrf-token",
        default=os.getenv("AIONUI_CSRF_TOKEN"),
        help="Override CSRF token for every task",
    )
    parser.add_argument("--default-workspace", help="Override workspace for every task")
    parser.add_argument(
        "--default-backend",
        choices=["claude", "codex", "gemini", "opencode"],
        help="Override backend for every task",
    )
    parser.add_argument(
        "--default-session-mode",
        choices=["default", "bypassPermissions", "yolo"],
        help="Override session mode for every task",
    )
    return parser


def main(argv: Optional[Iterable[str]] = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(list(argv) if argv is not None else None)

    try:
        plan = _load_plan(args.plan, args.plan_json)
        defaults = _resolve_defaults(plan["defaults"], args)
        resolved_tasks = [
            _resolved_task(defaults, task, args.create_only) for task in plan["tasks"]
        ]

        if args.dry_run:
            _emit_json(
                {
                    "mode": "dry-run",
                    "max_workers": max(1, min(args.max_workers, len(resolved_tasks))),
                    "tasks": resolved_tasks,
                }
            )
            return 0

        results = [None] * len(resolved_tasks)
        max_workers = max(1, min(args.max_workers, len(resolved_tasks)))

        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            future_map = {
                executor.submit(_run_task, index, task, args.create_only): index
                for index, task in enumerate(resolved_tasks)
            }
            for future in as_completed(future_map):
                index = future_map[future]
                results[index] = future.result()

        completed = [item for item in results if item is not None]
        summary = {
            "total": len(completed),
            "succeeded": sum(1 for item in completed if item["status"] == "ok"),
            "failed": sum(1 for item in completed if item["status"] == "error"),
            "created": sum(1 for item in completed if item["created"]),
            "sent": sum(1 for item in completed if item["sent"]),
        }

        _emit_json({"summary": summary, "results": completed})
        return 0 if summary["failed"] == 0 else 1
    except (AionUIError, json.JSONDecodeError) as exc:
        _emit_json({"error": str(exc)}, stream=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
