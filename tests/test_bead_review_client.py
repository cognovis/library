"""Behavioral tests for the ID-only, capability-routed bead review client."""

from __future__ import annotations

import asyncio
import importlib.util
import json
import sys
from pathlib import Path
from typing import Any

import pytest


ROOT = Path(__file__).resolve().parents[1]
CLIENT_PATH = ROOT / "bin" / "lib" / "bead-review-client.py"
SPEC = importlib.util.spec_from_file_location("bead_review_client", CLIENT_PATH)
assert SPEC is not None and SPEC.loader is not None
client = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = client
SPEC.loader.exec_module(client)


def _ok(data: dict[str, Any]) -> dict[str, Any]:
    return {"status": "ok", "summary": "ok", "data": data, "errors": []}


def _partial(data: dict[str, Any]) -> dict[str, Any]:
    return {"status": "partial", "summary": "started", "data": data, "errors": []}


def _result(*, bead_id: str = "CL-safe", profile: str = "full") -> str:
    return json.dumps({
        "bead_id": bead_id,
        "profile": profile,
        "reviewed_digest": "a" * 64,
        "outcome": "clean",
        "criteria": [
            {"criterion": name, "status": "ran", "reason": None}
            for name in ("formal", "semantic", "repository", "related-beads")
        ],
        "findings": [],
    })


def test_execute_review_dispatches_id_only_opposite_family_request(tmp_path: Path) -> None:
    calls: list[tuple[str, dict[str, Any]]] = []

    async def call_tool(name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        calls.append((name, arguments))
        if name == "agent_session_start":
            return _partial({"handle": "ags_review", "status": "created"})
        if name == "agent_session_status":
            return _ok({
                "status": "completed",
                "last_result": {"result": _result(), "status": "completed"},
            })
        raise AssertionError(name)

    request = client.ReviewRequest(
        bead_id="CL-safe",
        repo_dir=tmp_path,
        lead_family="claude",
    )
    result = asyncio.run(client.execute_review(request, call_tool))

    assert result["outcome"] == "clean"
    dispatch = calls[0][1]
    assert dispatch["role"] == "reviewer"
    assert dispatch["adapter"] == dispatch["provider"] == ""
    assert dispatch["different_from_lead"] is True
    assert dispatch["lead_family"] == "claude"
    assert dispatch["required_model_capabilities"] == ["repository-analysis", "spec-review"]
    assert dispatch["preferred_model_capabilities"] == ["long-context"]
    assert dispatch["reasoning_effort"] == "high"
    assert dispatch["network_access"] is False
    assert dispatch["workspace_dir"] == str(tmp_path.resolve())
    assert "CL-safe" in dispatch["prompt"]
    for copied_field in ("description", "acceptance_criteria", "metadata", "notes"):
        assert copied_field not in dispatch["prompt"]
    assert "model" not in dispatch


@pytest.mark.parametrize(
    "agent_result",
    [
        "not-json",
        json.dumps({"bead_id": "wrong"}),
        json.dumps({
            "bead_id": "CL-safe",
            "profile": "full",
            "reviewed_digest": "short",
            "outcome": "clean",
            "criteria": [],
            "findings": [],
        }),
    ],
)
def test_invalid_result_fails_closed(tmp_path: Path, agent_result: str) -> None:
    async def call_tool(name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        assert name == "agent_session_start"
        return _ok({"handle": "ags_review", "status": "completed", "result": agent_result})

    request = client.ReviewRequest(
        bead_id="CL-safe", repo_dir=tmp_path, lead_family="openai"
    )
    with pytest.raises(client.ReviewClientError):
        asyncio.run(client.execute_review(request, call_tool))


def test_terminal_provider_error_is_propagated(tmp_path: Path) -> None:
    async def call_tool(name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        if name == "agent_session_start":
            return _partial({"handle": "ags_review", "status": "created"})
        return _ok({"status": "error", "last_error": {"message": "provider failed"}})

    request = client.ReviewRequest(
        bead_id="CL-safe", repo_dir=tmp_path, lead_family="claude"
    )
    with pytest.raises(client.ReviewClientError, match="provider failed"):
        asyncio.run(client.execute_review(request, call_tool))


def test_orphaned_session_is_canceled(tmp_path: Path) -> None:
    calls: list[str] = []

    async def call_tool(name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        calls.append(name)
        if name == "agent_session_start":
            return _partial({"handle": "ags_review", "status": "created"})
        if name == "agent_session_status":
            return _ok({"status": "orphaned"})
        return _ok({"status": "canceled"})

    request = client.ReviewRequest(
        bead_id="CL-safe", repo_dir=tmp_path, lead_family="claude"
    )
    with pytest.raises(client.ReviewClientError, match="orphaned and canceled"):
        asyncio.run(client.execute_review(request, call_tool))
    assert calls == ["agent_session_start", "agent_session_status", "agent_session_cancel"]


def test_request_rejects_missing_repo_and_invalid_profile(tmp_path: Path) -> None:
    async def unused(name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        raise AssertionError("provider dispatch must not run")

    missing = client.ReviewRequest(
        bead_id="CL-safe", repo_dir=tmp_path / "missing", lead_family="claude"
    )
    with pytest.raises(client.ReviewClientError, match="does not exist"):
        asyncio.run(client.execute_review(missing, unused))

    invalid = client.ReviewRequest(
        bead_id="CL-safe", repo_dir=tmp_path, lead_family="claude", profile="unknown"
    )
    with pytest.raises(client.ReviewClientError, match="unsupported review profile"):
        asyncio.run(client.execute_review(invalid, unused))


def test_cli_has_no_provider_adapter_or_model_selection() -> None:
    parser = client._parser()
    option_strings = {option for action in parser._actions for option in action.option_strings}

    assert "--lead-family" in option_strings
    assert "--profile" in option_strings
    assert "--provider" not in option_strings
    assert "--adapter" not in option_strings
    assert "--model" not in option_strings
    assert "--reasoning-effort" not in option_strings


@pytest.mark.parametrize(
    "url",
    [
        "https://127.0.0.1:8765/mcp",
        "http://example.com:8765/mcp",
        "http://127.0.0.1:8765/other",
    ],
)
def test_non_loopback_or_wrong_path_urls_are_rejected(url: str) -> None:
    with pytest.raises(client.ReviewClientError):
        client._validate_url(url)
