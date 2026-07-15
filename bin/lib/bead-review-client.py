#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = ["mcp>=1.27.1,<2"]
# ///
"""Start an opposite-family, read-only live bead review through cognovis-tools."""

from __future__ import annotations

import argparse
import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import timedelta
import json
from pathlib import Path
import re
import sys
from typing import Any
from urllib.parse import urlparse
from uuid import uuid4

DEFAULT_MCP_URL = "http://127.0.0.1:8765/mcp"
POLL_INTERVAL_SEC = 0.25
ACTIVE_SESSION_STATUSES = frozenset({"created", "running"})
PROFILES = frozenset({"formal", "semantic", "repository", "related-beads", "full"})
OUTCOMES = frozenset({"clean", "warnings", "blocked"})
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")

ToolCaller = Callable[[str, dict[str, Any]], Awaitable[dict[str, Any]]]


class ReviewClientError(RuntimeError):
    """A fail-closed review client contract violation."""


@dataclass(frozen=True)
class ReviewRequest:
    bead_id: str
    repo_dir: Path
    lead_family: str
    profile: str = "full"
    timeout_sec: int = 900


def _require_ok(tool_name: str, envelope: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(envelope, dict):
        raise ReviewClientError(f"{tool_name} returned a non-object response")
    if envelope.get("status") != "ok":
        errors = envelope.get("errors")
        detail = ""
        if isinstance(errors, list) and errors and isinstance(errors[0], dict):
            detail = str(errors[0].get("message") or "")
        raise ReviewClientError(detail or str(envelope.get("summary") or "tool call failed"))
    data = envelope.get("data")
    if not isinstance(data, dict):
        raise ReviewClientError(f"{tool_name} returned invalid data")
    return data


def _require_started(envelope: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(envelope, dict) or envelope.get("status") not in {"ok", "partial"}:
        return _require_ok("agent_session_start", envelope)
    data = envelope.get("data")
    if not isinstance(data, dict):
        raise ReviewClientError("agent_session_start returned invalid data")
    handle = data.get("handle")
    if not isinstance(handle, str) or not handle.startswith("ags_"):
        raise ReviewClientError("agent_session_start returned no pollable handle")
    return data


async def _poll_terminal_result(
    call_tool: ToolCaller, *, handle: str, workspace_dir: str, timeout_sec: int
) -> dict[str, Any]:
    deadline = asyncio.get_running_loop().time() + timeout_sec + 30
    while True:
        status_data = _require_ok(
            "agent_session_status",
            await call_tool(
                "agent_session_status",
                {"handle": handle, "workspace_dir": workspace_dir},
            ),
        )
        status = str(status_data.get("status") or "")
        if status == "completed":
            result = status_data.get("last_result")
            if not isinstance(result, dict):
                raise ReviewClientError("review session returned no persisted terminal result")
            return result
        if status == "orphaned":
            _require_ok(
                "agent_session_cancel",
                await call_tool(
                    "agent_session_cancel",
                    {"handle": handle, "workspace_dir": workspace_dir},
                ),
            )
            raise ReviewClientError("reviewer session was orphaned and canceled")
        if status not in ACTIVE_SESSION_STATUSES:
            error = status_data.get("last_error")
            detail = str(error.get("message") or "") if isinstance(error, dict) else ""
            raise ReviewClientError(f"reviewer session ended as {status or 'unknown'}: {detail}")
        if asyncio.get_running_loop().time() >= deadline:
            _require_ok(
                "agent_session_cancel",
                await call_tool(
                    "agent_session_cancel",
                    {"handle": handle, "workspace_dir": workspace_dir},
                ),
            )
            raise ReviewClientError("reviewer session timed out and was canceled")
        await asyncio.sleep(POLL_INTERVAL_SEC)


def _build_prompt(bead_id: str, profile: str) -> str:
    return (
        f"Review live bead {bead_id} with the installed bead-reviewer skill using "
        f"profile {profile}. Load the authoritative artifact by ID in the assigned "
        "repository. Do not mutate bead, file, Git, cache, or external state. Return "
        "only the typed revision-bound JSON result."
    )


def _parse_result(result: str, request: ReviewRequest) -> dict[str, Any]:
    try:
        payload = json.loads(result)
    except json.JSONDecodeError as exc:
        raise ReviewClientError("reviewer returned invalid JSON") from exc
    if not isinstance(payload, dict):
        raise ReviewClientError("reviewer result must be an object")
    if payload.get("bead_id") != request.bead_id:
        raise ReviewClientError("reviewer result bead_id mismatch")
    if payload.get("profile") != request.profile:
        raise ReviewClientError("reviewer result profile mismatch")
    if not isinstance(payload.get("reviewed_digest"), str) or not SHA256_RE.fullmatch(
        payload["reviewed_digest"]
    ):
        raise ReviewClientError("reviewer result has no valid content digest")
    if payload.get("outcome") not in OUTCOMES:
        raise ReviewClientError("reviewer result outcome is invalid")
    if not isinstance(payload.get("criteria"), list) or not isinstance(payload.get("findings"), list):
        raise ReviewClientError("reviewer result criteria and findings must be lists")
    for finding in payload["findings"]:
        if not isinstance(finding, dict) or not all(
            finding.get(field) for field in ("finding_id", "criterion", "severity", "message", "evidence", "recommended_change")
        ):
            raise ReviewClientError("reviewer finding violates the typed contract")
    return payload


async def execute_review(request: ReviewRequest, call_tool: ToolCaller) -> dict[str, Any]:
    repo_dir = request.repo_dir.expanduser().resolve()
    if not repo_dir.is_dir():
        raise ReviewClientError(f"repository directory does not exist: {repo_dir}")
    if request.lead_family not in {"claude", "openai"}:
        raise ReviewClientError("lead_family must be claude or openai")
    if request.profile not in PROFILES:
        raise ReviewClientError(f"unsupported review profile: {request.profile}")
    session_args: dict[str, Any] = {
        "role": "reviewer",
        "adapter": "",
        "provider": "",
        "prompt": _build_prompt(request.bead_id, request.profile),
        "workspace_dir": str(repo_dir),
        "run_id": str(uuid4()),
        "bead_id": request.bead_id,
        "slot": "spec_review",
        "timeout_sec": request.timeout_sec,
        "network_access": False,
        "execution_mode": "background",
        "different_from_lead": True,
        "lead_family": request.lead_family,
        "required_model_capabilities": ["repository-analysis", "spec-review"],
        "preferred_model_capabilities": ["long-context"],
        "reasoning_effort": "high",
        "selection_preference": "quality",
    }
    session_data = _require_started(await call_tool("agent_session_start", session_args))
    if session_data.get("status") != "completed" or not session_data.get("result"):
        session_data = await _poll_terminal_result(
            call_tool,
            handle=str(session_data["handle"]),
            workspace_dir=str(repo_dir),
            timeout_sec=request.timeout_sec,
        )
    result = session_data.get("result")
    if not isinstance(result, str) or not result.strip():
        raise ReviewClientError("reviewer returned no inline result")
    return _parse_result(result, request)


def _validate_url(url: str) -> None:
    parsed = urlparse(url)
    if parsed.scheme != "http" or parsed.hostname not in {"127.0.0.1", "localhost", "::1"}:
        raise ReviewClientError("cognovis-tools URL must be loopback HTTP")
    if parsed.path != "/mcp":
        raise ReviewClientError("cognovis-tools URL must target the /mcp endpoint")


async def _run_mcp(request: ReviewRequest, url: str) -> dict[str, Any]:
    from mcp import ClientSession
    from mcp.client.streamable_http import streamable_http_client

    _validate_url(url)
    async with streamable_http_client(url) as (read, write, _):
        async with ClientSession(
            read,
            write,
            read_timeout_seconds=timedelta(seconds=request.timeout_sec + 30),
        ) as session:
            await session.initialize()

            async def call_tool(name: str, arguments: dict[str, Any]) -> dict[str, Any]:
                result = await session.call_tool(name, arguments=arguments)
                structured = getattr(result, "structuredContent", None)
                if isinstance(structured, dict):
                    return structured
                for item in getattr(result, "content", []):
                    text = getattr(item, "text", None)
                    if isinstance(text, str):
                        try:
                            parsed = json.loads(text)
                        except json.JSONDecodeError:
                            continue
                        if isinstance(parsed, dict):
                            return parsed
                raise ReviewClientError(f"{name} returned no structured envelope")

            return await execute_review(request, call_tool)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bead-id", required=True)
    parser.add_argument("--repo-dir", type=Path, required=True)
    parser.add_argument("--lead-family", choices=("claude", "openai"), required=True)
    parser.add_argument("--profile", choices=sorted(PROFILES), default="full")
    parser.add_argument("--timeout-sec", type=int, default=900)
    parser.add_argument("--mcp-url", default=DEFAULT_MCP_URL)
    return parser


def main() -> int:
    args = _parser().parse_args()
    request = ReviewRequest(
        bead_id=args.bead_id,
        repo_dir=args.repo_dir,
        lead_family=args.lead_family,
        profile=args.profile,
        timeout_sec=args.timeout_sec,
    )
    try:
        result = asyncio.run(_run_mcp(request, args.mcp_url))
    except Exception as exc:
        current: BaseException = exc
        while isinstance(current, BaseExceptionGroup) and len(current.exceptions) == 1:
            current = current.exceptions[0]
        print(f"ERROR: bead review failed: {current}", file=sys.stderr)
        return 1
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
