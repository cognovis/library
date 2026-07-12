#!/usr/bin/env python3
"""Minimal MCP stdio server for installer rollback handshake tests."""

from __future__ import annotations

import json
import sys
from typing import Any


def _read_message() -> dict[str, Any] | None:
    headers: dict[str, str] = {}
    while True:
        line = sys.stdin.buffer.readline()
        if not line:
            return None
        decoded = line.decode("utf-8").strip()
        if not decoded:
            break
        key, value = decoded.split(":", 1)
        headers[key.strip().lower()] = value.strip()
    length = int(headers.get("content-length", "0"))
    if length <= 0:
        return None
    body = sys.stdin.buffer.read(length)
    return json.loads(body.decode("utf-8"))


def _write_message(payload: dict[str, Any]) -> None:
    body = json.dumps(payload).encode("utf-8")
    sys.stdout.buffer.write(f"Content-Length: {len(body)}\r\n\r\n".encode("utf-8"))
    sys.stdout.buffer.write(body)
    sys.stdout.buffer.flush()


def main() -> None:
    while True:
        message = _read_message()
        if message is None:
            return
        method = message.get("method")
        msg_id = message.get("id")
        if method == "initialize":
            _write_message(
                {
                    "jsonrpc": "2.0",
                    "id": msg_id,
                    "result": {
                        "protocolVersion": "2024-11-05",
                        "capabilities": {"tools": {}},
                        "serverInfo": {"name": "minimal-mcp-stdio", "version": "0.0.1"},
                    },
                }
            )
            continue
        if method == "notifications/initialized":
            continue
        if method == "tools/list":
            _write_message(
                {
                    "jsonrpc": "2.0",
                    "id": msg_id,
                    "result": {
                        "tools": [
                            {
                                "name": "echo",
                                "description": "Echo tool",
                                "inputSchema": {
                                    "type": "object",
                                    "properties": {"value": {"type": "string"}},
                                },
                            }
                        ]
                    },
                }
            )
            continue
        if method == "tools/call":
            params = message.get("params", {})
            value = params.get("arguments", {}).get("value", "")
            _write_message(
                {
                    "jsonrpc": "2.0",
                    "id": msg_id,
                    "result": {
                        "content": [{"type": "text", "text": json.dumps({"echo": value})}],
                        "isError": False,
                    },
                }
            )
            continue
        if msg_id is not None:
            _write_message(
                {
                    "jsonrpc": "2.0",
                    "id": msg_id,
                    "error": {"code": -32601, "message": f"Unknown method: {method}"},
                }
            )


if __name__ == "__main__":
    main()
