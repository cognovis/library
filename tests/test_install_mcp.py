#!/usr/bin/env python3
"""test_install_mcp.py — Tests for CL-l0c Deliverable D (install-mcp.py).

Bead: CL-l0c
Tests:
  AK D1: install-mcp.py exists and accepts --dry-run + --harness
  AK D2: claude_code harness writes snippet to mcpServers map under _origin tag
  AK D3: opencode harness writes snippet to mcp map under _origin tag
  AK D4: codex harness writes snippet to mcp_servers TOML table under _origin tag
  AK D5: re-install is idempotent (action=no_change or refresh, no duplicate keys)
  AK D6: --remove drops library-managed entries; leaves manual entries alone
  AK D7: --harness=<unknown> for an entry that doesn't declare it emits WARN
  AK D8: claude_ai / claude_ios emit install URL (no programmatic install)

Run with:
    python3 -m pytest tests/test_install_mcp.py -v
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
INSTALL_MCP = REPO_ROOT / "scripts" / "install-mcp.py"
sys.path.insert(0, str(REPO_ROOT / "scripts"))


def run_install_mcp(*args: str, env_overrides: dict[str, str] | None = None) -> subprocess.CompletedProcess:
    """Invoke install-mcp.py with optional env overrides."""
    env = os.environ.copy()
    if env_overrides:
        env.update(env_overrides)
    return subprocess.run(
        ["python3", str(INSTALL_MCP), *args],
        capture_output=True,
        text=True,
        env=env,
    )


class TestInstallMcp(unittest.TestCase):
    """Tests for scripts/install-mcp.py."""

    def setUp(self) -> None:
        self.tmp = tempfile.mkdtemp(prefix="install-mcp-test-")
        self.claude_settings = Path(self.tmp) / "claude" / "settings.json"
        self.codex_config = Path(self.tmp) / "codex" / "config.toml"
        self.opencode_config = Path(self.tmp) / "opencode" / "opencode.json"
        self.gemini_settings = Path(self.tmp) / "gemini" / "settings.json"
        self.cursor_config = Path(self.tmp) / "cursor" / "mcp.json"
        self.env = {
            "CLAUDE_SETTINGS_FILE": str(self.claude_settings),
            "CODEX_CONFIG_FILE": str(self.codex_config),
            "OPENCODE_CONFIG_FILE": str(self.opencode_config),
            "GEMINI_SETTINGS_FILE": str(self.gemini_settings),
            "CURSOR_MCP_FILE": str(self.cursor_config),
        }

    def tearDown(self) -> None:
        import shutil
        shutil.rmtree(self.tmp, ignore_errors=True)

    # --- AK D1: tool exists + flag parsing ---

    def test_d1_install_mcp_exists(self):
        self.assertTrue(INSTALL_MCP.is_file(), f"missing: {INSTALL_MCP}")
        self.assertTrue(os.access(INSTALL_MCP, os.X_OK), "not executable")

    def test_d1_help_lists_harness_flag(self):
        result = run_install_mcp("--help")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("--harness", result.stdout)
        self.assertIn("--dry-run", result.stdout)
        self.assertIn("--remove", result.stdout)

    # --- AK D2: claude_code writes to mcpServers map ---

    def test_d2_claude_code_install_writes_mcpservers(self):
        result = run_install_mcp(
            "open-brain", "--harness", "claude_code", env_overrides=self.env
        )
        self.assertEqual(result.returncode, 0, f"stderr: {result.stderr}")
        self.assertTrue(self.claude_settings.is_file())
        data = json.loads(self.claude_settings.read_text())
        self.assertIn("mcpServers", data)
        self.assertIn("open-brain", data["mcpServers"])
        entry = data["mcpServers"]["open-brain"]
        self.assertEqual(entry.get("_origin"), "library:mcp:open-brain")
        self.assertEqual(entry.get("type"), "http")
        self.assertEqual(entry.get("url"), "https://open-brain.sussdorff.org/mcp")
        self.assertNotIn("token=", entry.get("url", ""))

    # --- AK D3: opencode writes to mcp map ---

    def test_d3_opencode_install_writes_mcp(self):
        result = run_install_mcp(
            "open-brain", "--harness", "opencode", env_overrides=self.env
        )
        self.assertEqual(result.returncode, 0, f"stderr: {result.stderr}")
        self.assertTrue(self.opencode_config.is_file())
        data = json.loads(self.opencode_config.read_text())
        self.assertIn("mcp", data)
        self.assertIn("open-brain", data["mcp"])
        self.assertEqual(data["mcp"]["open-brain"]["_origin"], "library:mcp:open-brain")
        self.assertEqual(data["mcp"]["open-brain"]["type"], "remote")
        self.assertEqual(
            data["mcp"]["open-brain"]["url"],
            "https://open-brain.sussdorff.org/mcp",
        )

    # --- AK D4: codex writes TOML table with _origin tag ---

    def test_d4_codex_install_writes_toml_table(self):
        result = run_install_mcp(
            "open-brain", "--harness", "codex", env_overrides=self.env
        )
        self.assertEqual(result.returncode, 0, f"stderr: {result.stderr}")
        self.assertTrue(self.codex_config.is_file())
        try:
            import tomllib
        except ImportError:
            self.skipTest("tomllib required (Python 3.11+)")
        with self.codex_config.open("rb") as f:
            data = tomllib.load(f)
        self.assertIn("mcp_servers", data)
        self.assertIn("open-brain", data["mcp_servers"])
        self.assertEqual(
            data["mcp_servers"]["open-brain"]["_origin"], "library:mcp:open-brain"
        )
        self.assertEqual(
            data["mcp_servers"]["open-brain"]["url"],
            "https://open-brain.sussdorff.org/mcp",
        )
        self.assertNotIn("token=", data["mcp_servers"]["open-brain"]["url"])

    # --- AK D5: idempotent re-install ---

    def test_d5_reinstall_is_idempotent_claude(self):
        # First install
        r1 = run_install_mcp("open-brain", "--harness", "claude_code", env_overrides=self.env)
        self.assertEqual(r1.returncode, 0)
        first_content = self.claude_settings.read_text()
        # Second install — should report no_change, content unchanged
        r2 = run_install_mcp("open-brain", "--harness", "claude_code", env_overrides=self.env)
        self.assertEqual(r2.returncode, 0)
        self.assertIn("no change", r2.stdout)
        # backup file may differ; verify mcpServers map identical
        self.assertEqual(json.loads(first_content), json.loads(self.claude_settings.read_text()))

    # --- AK D6: --remove drops library-managed; leaves manual ---

    def test_d6_remove_drops_library_managed(self):
        # Install first
        run_install_mcp("open-brain", "--harness", "claude_code", env_overrides=self.env)
        # Then remove
        result = run_install_mcp(
            "open-brain", "--harness", "claude_code", "--remove", env_overrides=self.env
        )
        self.assertEqual(result.returncode, 0)
        # mcpServers.open-brain should be gone
        data = json.loads(self.claude_settings.read_text())
        self.assertNotIn("open-brain", data.get("mcpServers", {}))

    def test_d6_remove_leaves_manual_entries_alone(self):
        # Seed config with a manually-installed entry (no _origin tag)
        self.claude_settings.parent.mkdir(parents=True, exist_ok=True)
        self.claude_settings.write_text(json.dumps({
            "mcpServers": {
                "open-brain": {"command": "user-custom-bin", "type": "stdio"}
            }
        }))
        # Attempt remove — should refuse + warn, leaving entry intact
        result = run_install_mcp(
            "open-brain", "--harness", "claude_code", "--remove", env_overrides=self.env
        )
        self.assertEqual(result.returncode, 0)
        data = json.loads(self.claude_settings.read_text())
        self.assertIn("open-brain", data["mcpServers"])
        self.assertEqual(data["mcpServers"]["open-brain"]["command"], "user-custom-bin")

    def test_d6_install_refuses_to_overwrite_manual(self):
        # Seed manual entry
        self.claude_settings.parent.mkdir(parents=True, exist_ok=True)
        self.claude_settings.write_text(json.dumps({
            "mcpServers": {
                "open-brain": {"command": "user-custom-bin"}
            }
        }))
        result = run_install_mcp(
            "open-brain", "--harness", "claude_code", env_overrides=self.env
        )
        # Exit code 1: refused
        self.assertEqual(result.returncode, 1)
        self.assertIn("refusing to overwrite", result.stderr)
        data = json.loads(self.claude_settings.read_text())
        self.assertEqual(data["mcpServers"]["open-brain"]["command"], "user-custom-bin")

    # --- AK D7: --harness not declared by entry emits WARN ---

    def test_d7_undeclared_harness_warns(self):
        # 'playwright' only declares codex per library.yaml
        result = run_install_mcp(
            "playwright", "--harness", "claude_code", env_overrides=self.env
        )
        self.assertEqual(result.returncode, 0)
        self.assertIn("not declared", result.stderr)

    # --- AK D8: claude_ai / claude_ios emit URL ---

    def test_d8_claude_ai_emits_install_url(self):
        result = run_install_mcp(
            "open-brain", "--harness", "claude_ai", env_overrides=self.env
        )
        self.assertEqual(result.returncode, 0)
        self.assertIn("manual install required", result.stdout)
        self.assertIn("https://claude.ai/add-mcp/open-brain", result.stdout)

    def test_d8_claude_ios_emits_install_url(self):
        result = run_install_mcp(
            "open-brain", "--harness", "claude_ios", env_overrides=self.env
        )
        self.assertEqual(result.returncode, 0)
        self.assertIn("manual install required", result.stdout)

    # --- CL-qdtc: cognovis-tools supervised HTTP catalog + installer coverage ---

    def test_cognovis_tools_catalog_declares_http_snippets(self):
        import yaml

        library = yaml.safe_load((REPO_ROOT / "library.yaml").read_text())
        entry = next(
            item
            for item in library["library"]["mcp_servers"]
            if item["name"] == "cognovis-tools"
        )
        url = "http://127.0.0.1:8765/mcp"
        snippets = entry["install"]["mcp"]
        self.assertEqual(snippets["claude_code"]["snippet"], {"type": "http", "url": url})
        self.assertEqual(snippets["codex"]["snippet"], {"url": url})
        self.assertEqual(snippets["antigravity"]["snippet"], {"type": "http", "url": url})
        self.assertEqual(snippets["cursor"]["snippet"], {"type": "http", "url": url})
        self.assertIn("supervised_local_service", entry)

    # --- CL-oo82: corrected default config paths per harness ---

    def test_default_config_paths_are_harness_correct(self):
        """claude_code -> ~/.claude.json; antigravity -> ~/.gemini/config/mcp_config.json.

        Claude Code reads user-scoped MCP from ~/.claude.json (NOT
        ~/.claude/settings.json); Antigravity (agy) reads ~/.gemini/config/mcp_config.json
        (NOT ~/.config/gemini/settings.json).
        """
        from lib.installers.mcp_installer import _mcp_config_path

        # Clear any env overrides so we observe the real defaults.
        saved = {k: os.environ.pop(k, None)
                 for k in ("CLAUDE_SETTINGS_FILE", "GEMINI_SETTINGS_FILE", "CURSOR_MCP_FILE")}
        try:
            self.assertEqual(_mcp_config_path("claude_code"), Path.home() / ".claude.json")
            self.assertEqual(
                _mcp_config_path("antigravity"),
                Path.home() / ".gemini" / "config" / "mcp_config.json",
            )
            self.assertEqual(_mcp_config_path("cursor"), Path.home() / ".cursor" / "mcp.json")
            self.assertEqual(
                _mcp_config_path("codex"), Path.home() / ".codex" / "config.toml"
            )
        finally:
            for k, v in saved.items():
                if v is not None:
                    os.environ[k] = v

    def test_install_into_empty_config_file(self):
        """An existing but empty JSON config file must not crash."""
        self.claude_settings.parent.mkdir(parents=True, exist_ok=True)
        self.claude_settings.write_text("")
        result = run_install_mcp(
            "open-brain", "--harness", "claude_code", env_overrides=self.env
        )
        self.assertEqual(result.returncode, 0, f"stderr: {result.stderr}")
        data = json.loads(self.claude_settings.read_text())
        self.assertIn("open-brain", data.get("mcpServers", {}))

    # --- bonus: --dry-run on a fresh env shouldn't write files ---

    def test_dry_run_does_not_write(self):
        result = run_install_mcp(
            "open-brain", "--harness", "claude_code", "--dry-run", env_overrides=self.env
        )
        self.assertEqual(result.returncode, 0)
        self.assertFalse(self.claude_settings.is_file())


if __name__ == "__main__":
    unittest.main(verbosity=2)
