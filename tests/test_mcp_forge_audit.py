from __future__ import annotations

import importlib.util
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPT = REPO_ROOT / "skills" / "mcp-forge" / "scripts" / "audit_mcp_v1.py"


def _load_script():
    spec = importlib.util.spec_from_file_location("audit_mcp_v1", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_audit_reports_migration_signals_and_skips_agent_projections(
    tmp_path: Path,
) -> None:
    module = _load_script()
    (tmp_path / "server.py").write_text(
        "from mcp.server.fastmcp import FastMCP\nmethod = 'logging/setLevel'\n"
    )
    ignored = tmp_path / ".agents" / "skills"
    ignored.mkdir(parents=True)
    (ignored / "fixture.py").write_text("FastMCP\n")

    result = module.audit(tmp_path)

    assert result["status"] == "ok"
    assert result["data"]["files_scanned"] == 1
    assert result["data"]["matches"] == [
        {"path": "server.py", "line": 1, "signal": "fastmcp"},
        {"path": "server.py", "line": 1, "signal": "fastmcp-module"},
        {"path": "server.py", "line": 2, "signal": "logging-set-level"},
    ]
    assert set(result) == {
        "status",
        "summary",
        "data",
        "errors",
        "next_steps",
        "open_items",
        "meta",
    }


def test_audit_rejects_a_missing_root(tmp_path: Path) -> None:
    module = _load_script()

    result = module.audit(tmp_path / "missing")

    assert result["status"] == "error"
    assert result["errors"][0]["code"] == "invalid-root"
    assert result["meta"]["contract_version"] == "1"


def test_main_emits_an_error_envelope_without_transport_failure(
    tmp_path: Path, capsys
) -> None:
    module = _load_script()

    exit_code = module.main([str(tmp_path / "missing")])

    assert exit_code == 0
    assert '"status": "error"' in capsys.readouterr().out


def test_audit_uses_token_boundaries_for_short_method_names(tmp_path: Path) -> None:
    module = _load_script()
    (tmp_path / "names.py").write_text(
        "mapping = typing = scoping = 1\nmethod = 'ping'\ncall = 'initialize'\n"
    )

    result = module.audit(tmp_path)

    assert [match["signal"] for match in result["data"]["matches"]] == [
        "ping-method",
        "initialize-method",
    ]


def test_audit_covers_python_v1_migration_identifiers(tmp_path: Path) -> None:
    module = _load_script()
    (tmp_path / "server.py").write_text(
        "\n".join(
            [
                "from mcp.server.fastmcp import FastMCP",
                "from mcp import McpError",
                "from mcp.shared.version import SUPPORTED_PROTOCOL_VERSIONS",
                "from mcp.client.streamable_http import streamablehttp_client",
                "from mcp.server.fastmcp.experimental.tasks import TaskContext",
                "from httpx import AsyncClient",
                "server = FastMCP('name', None, 'instructions')",
                "context = mcp.get_context()",
                "legacy = ctx.fastmcp",
                "ctx.session.send_resource_updated(uri)",
                "dependency = 'mcp[cli]>=1.9.0'",
            ]
        )
    )

    result = module.audit(tmp_path)
    signals = {match["signal"] for match in result["data"]["matches"]}

    assert {
        "fastmcp",
        "fastmcp-module",
        "mcp-error",
        "shared-version",
        "streamable-http-client",
        "experimental-tasks",
        "direct-httpx",
        "get-context",
        "context-fastmcp",
        "resource-updated",
        "mcp-cli-dependency",
    } <= signals


def test_audit_skips_generated_and_vendored_directories(tmp_path: Path) -> None:
    module = _load_script()
    for directory in ("venv", "env", "site-packages", "build", "dist", ".tox", ".beads"):
        target = tmp_path / directory
        target.mkdir()
        (target / "server.py").write_text("FastMCP\n")
    (tmp_path / "application.py").write_text("McpError\n")

    result = module.audit(tmp_path)

    assert result["data"]["matches"] == [
        {"path": "application.py", "line": 1, "signal": "mcp-error"}
    ]


def test_audit_warns_when_no_supported_files_are_scanned(tmp_path: Path) -> None:
    module = _load_script()

    result = module.audit(tmp_path)

    assert result["status"] == "warning"
    assert result["errors"][0]["code"] == "no-files-scanned"


def test_audit_reports_read_errors_with_continue_guidance(
    tmp_path: Path, monkeypatch
) -> None:
    module = _load_script()
    target = tmp_path / "server.py"
    target.write_text("FastMCP\n")
    original_read_text = module.Path.read_text

    def fail_target(path, *args, **kwargs):
        if path == target:
            raise OSError("unreadable fixture")
        return original_read_text(path, *args, **kwargs)

    monkeypatch.setattr(module.Path, "read_text", fail_target)

    result = module.audit(tmp_path)

    assert result["status"] == "warning"
    assert result["errors"][0]["code"] == "read-failed"
    assert "continue_with" in result["errors"][0]


def test_script_declares_python_310_compatibility() -> None:
    source = SCRIPT.read_text()

    assert '# requires-python = ">=3.10"' in source
