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
        {"path": "server.py", "line": 1, "signal": "FastMCP"},
        {"path": "server.py", "line": 1, "signal": "mcp.server.fastmcp"},
        {"path": "server.py", "line": 2, "signal": "logging/setLevel"},
    ]


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
