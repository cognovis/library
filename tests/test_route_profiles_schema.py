"""Tests for route_profiles YAML schema and launcher --route-profile support — CL-iye.1.

AC coverage:
  AC1: orchestrator-config supports route_profiles with orchestrator, slots, adapter,
       harness, model, reasoning_effort, and timeout fields
  AC2: bin/cld and bin/cdx accept --route-profile flag
  AC4: fixtures cover cld-default, cdx-default, and cdx-composer
  AC5: resolver returns phase-specific slots without model-name prefix dispatch
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest
import yaml


_USER_GLOBAL_CONFIG = Path.home() / ".agents" / "orchestrator-config.yml"
def _find_cognovis_config() -> Path:
    """Find the cognovis-core config by walking up to the library root."""
    # library-meta is at .../library/meta; cognovis-core is sibling
    # Start from this file and look for the library-meta root
    here = Path(__file__).resolve()
    for parent in here.parents:
        if (parent / "bin" / "cld").exists() and parent.name == "meta":
            return parent.parent / "cognovis-core" / ".agents" / "orchestrator-config.yml"
    return Path("/nonexistent/cognovis-core/.agents/orchestrator-config.yml")


_COGNOVIS_CONFIG = _find_cognovis_config()
_CLD_BIN = Path(__file__).resolve().parents[1] / "bin" / "cld"
_CDX_BIN = Path(__file__).resolve().parents[1] / "bin" / "cdx"

REQUIRED_PROFILES = {"cld-default", "cdx-default", "cdx-composer"}
REQUIRED_FULL_SLOTS = {
    "implementation",
    "regression_fix",
    "verification_fix",
    "verification",
    "adversarial_review",
    "session_close",
}
REQUIRED_QUICK_SLOTS = {"implementation", "fix_loop"}
REQUIRED_SLOT_FIELDS = {"adapter", "harness", "model"}


def _load_config(path: Path) -> dict:
    """Load a YAML config file."""
    if not path.exists():
        pytest.skip(f"Config file not found: {path}")
    raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    return raw


# ── AC1: orchestrator-config supports route_profiles section ──────────────

class TestRouteProfilesSchema:
    """AC1, AC4: route_profiles YAML schema validation."""

    @pytest.fixture(params=["user_global", "cognovis_core"])
    def config(self, request):
        """Parametrized fixture loading both config files."""
        if request.param == "user_global":
            return _load_config(_USER_GLOBAL_CONFIG)
        else:
            return _load_config(_COGNOVIS_CONFIG)

    def test_route_profiles_section_exists(self, config: dict) -> None:
        assert "route_profiles" in config, "orchestrator-config must have a route_profiles section"

    def test_required_profiles_present(self, config: dict) -> None:
        profiles = config["route_profiles"]
        for name in REQUIRED_PROFILES:
            assert name in profiles, f"Profile {name!r} must be present"

    def test_each_profile_has_orchestrator_field(self, config: dict) -> None:
        profiles = config["route_profiles"]
        for name in REQUIRED_PROFILES:
            profile = profiles[name]
            assert "orchestrator" in profile, f"Profile {name!r} must have 'orchestrator' field"

    def test_each_profile_has_slots_section(self, config: dict) -> None:
        profiles = config["route_profiles"]
        for name in REQUIRED_PROFILES:
            profile = profiles[name]
            assert "slots" in profile, f"Profile {name!r} must have 'slots' section"

    def test_cld_default_full_slots_complete(self, config: dict) -> None:
        slots = config["route_profiles"]["cld-default"]["slots"]["full"]
        for slot_name in REQUIRED_FULL_SLOTS:
            assert slot_name in slots, f"cld-default full must have slot {slot_name!r}"

    def test_cld_default_quick_slots_complete(self, config: dict) -> None:
        slots = config["route_profiles"]["cld-default"]["slots"]["quick"]
        for slot_name in REQUIRED_QUICK_SLOTS:
            assert slot_name in slots, f"cld-default quick must have slot {slot_name!r}"

    def test_each_slot_has_required_fields(self, config: dict) -> None:
        profiles = config["route_profiles"]
        for profile_name in REQUIRED_PROFILES:
            for workflow_name, workflow_slots in profiles[profile_name]["slots"].items():
                for slot_name, slot_data in workflow_slots.items():
                    for field in REQUIRED_SLOT_FIELDS:
                        assert field in slot_data, (
                            f"Profile {profile_name!r}/{workflow_name}/{slot_name} "
                            f"must have field {field!r}"
                        )

    def test_cdx_composer_implementation_uses_cursor_adapter(self, config: dict) -> None:
        """AC5: cdx-composer uses cursor-composer adapter — no model-prefix dispatch."""
        impl = config["route_profiles"]["cdx-composer"]["slots"]["full"]["implementation"]
        assert impl["adapter"] == "cursor-composer"
        assert impl["harness"] == "cursor"

    def test_cursor_adapter_model_not_claude_or_gpt_prefix(self, config: dict) -> None:
        """AC5: cursor-composer slot model does not start with claude- or gpt-."""
        impl = config["route_profiles"]["cdx-composer"]["slots"]["full"]["implementation"]
        model = impl.get("model", "")
        assert not model.startswith("claude-"), (
            "cursor-composer should NOT use a claude-* model — that would be prefix dispatch"
        )
        assert not model.startswith("gpt-"), (
            "cursor-composer should NOT use a gpt-* model — that would be prefix dispatch"
        )

    def test_cld_default_orchestrator_is_cld(self, config: dict) -> None:
        assert config["route_profiles"]["cld-default"]["orchestrator"] == "cld"

    def test_cdx_default_orchestrator_is_cdx(self, config: dict) -> None:
        assert config["route_profiles"]["cdx-default"]["orchestrator"] == "cdx"

    def test_cdx_composer_orchestrator_is_cdx(self, config: dict) -> None:
        assert config["route_profiles"]["cdx-composer"]["orchestrator"] == "cdx"

    # ── AC4: built-in profiles bind the expected adapter/model values ─────

    def test_cld_default_full_implementation_values(self, config: dict) -> None:
        impl = config["route_profiles"]["cld-default"]["slots"]["full"]["implementation"]
        assert impl["adapter"] == "codex-impl"
        assert impl["model"] == "gpt-5.5"
        assert impl["harness"] == "codex"

    def test_cld_default_quick_implementation_values(self, config: dict) -> None:
        impl = config["route_profiles"]["cld-default"]["slots"]["quick"]["implementation"]
        assert impl["adapter"] == "codex-impl"
        assert impl["model"] == "gpt-5.4-mini"
        assert impl["harness"] == "codex"

    def test_cdx_default_full_implementation_values(self, config: dict) -> None:
        impl = config["route_profiles"]["cdx-default"]["slots"]["full"]["implementation"]
        assert impl["adapter"] == "claude-agent"
        assert impl["model"] == "claude-opus-4-7"
        assert impl["harness"] == "claude"

    def test_cdx_default_quick_implementation_values(self, config: dict) -> None:
        impl = config["route_profiles"]["cdx-default"]["slots"]["quick"]["implementation"]
        assert impl["adapter"] == "claude-agent"
        assert impl["model"] == "claude-haiku-4-5"
        assert impl["harness"] == "claude"

    def test_cdx_composer_quick_implementation_values(self, config: dict) -> None:
        impl = config["route_profiles"]["cdx-composer"]["slots"]["quick"]["implementation"]
        assert impl["adapter"] == "cursor-composer"
        assert impl["harness"] == "cursor"
        assert impl["model"] == "composer-2.5"

    def test_cdx_composer_cursor_slots_use_available_cursor_model(self, config: dict) -> None:
        """Cursor Composer slots must use a cursor-agent model ID, not a placeholder."""
        cursor_slots = []
        for workflow_slots in config["route_profiles"]["cdx-composer"]["slots"].values():
            for slot in workflow_slots.values():
                if slot["adapter"] == "cursor-composer":
                    cursor_slots.append(slot)

        assert cursor_slots, "cdx-composer must define at least one cursor-composer slot"
        assert {slot["model"] for slot in cursor_slots} == {"composer-2.5"}


# ── AC2: bin/cld and bin/cdx accept --route-profile flag ─────────────────

class TestLauncherRouteProfileFlag:
    """AC2: Launcher flag --route-profile is declared and handled."""

    def test_cld_help_mentions_route_profile(self) -> None:
        assert _CLD_BIN.exists(), f"bin/cld not found at {_CLD_BIN}"
        content = _CLD_BIN.read_text(encoding="utf-8")
        assert "--route-profile" in content, "bin/cld must declare --route-profile flag"

    def test_cdx_help_mentions_route_profile(self) -> None:
        assert _CDX_BIN.exists(), f"bin/cdx not found at {_CDX_BIN}"
        content = _CDX_BIN.read_text(encoding="utf-8")
        assert "--route-profile" in content, "bin/cdx must declare --route-profile flag"

    def test_cld_exports_cld_route_profile(self) -> None:
        content = _CLD_BIN.read_text(encoding="utf-8")
        assert "CLD_ROUTE_PROFILE" in content, "bin/cld must export CLD_ROUTE_PROFILE"

    def test_cdx_exports_cld_route_profile(self) -> None:
        content = _CDX_BIN.read_text(encoding="utf-8")
        assert "CLD_ROUTE_PROFILE" in content, "bin/cdx must export CLD_ROUTE_PROFILE"

    def test_cld_route_profile_parsing_pattern_present(self) -> None:
        """bin/cld must have a case statement handling --route-profile."""
        content = _CLD_BIN.read_text(encoding="utf-8")
        assert "route_profile=" in content, "bin/cld must set route_profile variable"

    def test_cdx_route_profile_parsing_pattern_present(self) -> None:
        content = _CDX_BIN.read_text(encoding="utf-8")
        assert "route_profile=" in content, "bin/cdx must set route_profile variable"

    def test_cdx_uses_compact_bead_context_helper(self) -> None:
        content = _CDX_BIN.read_text(encoding="utf-8")
        assert "compact-bead-context.py" in content
        assert '"${BD_BIN}" show "${bead_id}" --json' in content

    def test_cdx_bq_cdx_composer_uses_inline_cursor_dispatch(self, tmp_path: Path) -> None:
        """Regression: cdx-composer quick path must not fall back to generic Codex prompt dispatch."""
        called = tmp_path / "codex-called"
        codex_mock = tmp_path / "codex-mock"
        codex_mock.write_text(
            "#!/bin/sh\n"
            "touch \"$CODEX_CALLED_FILE\"\n"
            "printf 'CODEX_CALLED\\n'\n",
            encoding="utf-8",
        )
        codex_mock.chmod(0o755)
        dispatch_mock = tmp_path / "dispatch-mock.py"
        dispatch_mock.write_text(
            "import os, sys\n"
            "stdin = sys.stdin.read()\n"
            "print('DISPATCH_CALLED=1')\n"
            "print(f'DISPATCH_ARGV={sys.argv[1:]}')\n"
            "print(f'DISPATCH_CLD_ROUTE_PROFILE={os.environ.get(\"CLD_ROUTE_PROFILE\", \"\")}')\n"
            "print(f'DISPATCH_CLD_COMPACT_OUTPUT={os.environ.get(\"CLD_COMPACT_OUTPUT\", \"\")}')\n"
            "print(f'DISPATCH_STDIN_HAS_CONTEXT={\"mock bead context\" in stdin}')\n",
            encoding="utf-8",
        )

        bd_mock = tmp_path / "bd-mock"
        bd_mock.write_text(
            "#!/bin/sh\n"
            "if [ \"$1\" = show ]; then\n"
            "  printf 'mock bead context for %s\\n' \"$2\"\n"
            "  exit 0\n"
            "fi\n"
            "exit 1\n",
            encoding="utf-8",
        )
        bd_mock.chmod(0o755)

        env = dict(os.environ)
        env["CODEX_BIN"] = str(codex_mock)
        env["CODEX_CALLED_FILE"] = str(called)
        env["BD_BIN"] = str(bd_mock)
        env["CDX_QUICK_CURSOR_DISPATCH_SCRIPT"] = str(dispatch_mock)

        result = subprocess.run(
            [str(_CDX_BIN), "-bq", "CL-smoke", "--route-profile", "cdx-composer"],
            capture_output=True,
            text=True,
            check=False,
            env=env,
        )

        assert result.returncode == 0
        assert not called.exists()
        assert "DISPATCH_CALLED=1" in result.stdout
        assert "DISPATCH_CLD_ROUTE_PROFILE=cdx-composer" in result.stdout
        assert "DISPATCH_CLD_COMPACT_OUTPUT=1" in result.stdout
        assert "CL-smoke" in result.stdout
        assert "--route-profile" in result.stdout
        assert "cdx-composer" in result.stdout
        assert "DISPATCH_STDIN_HAS_CONTEXT=True" in result.stdout

    def test_cdx_b_route_profile_can_use_python_workflow_mode(self, tmp_path: Path) -> None:
        """Full cdx -b can route through the deterministic helper when explicitly requested."""
        codex_mock = tmp_path / "codex-mock"
        codex_mock.write_text(
            "#!/bin/sh\n"
            "touch \"$CODEX_CALLED_FILE\"\n"
            "printf 'CODEX_CALLED\\n'\n",
            encoding="utf-8",
        )
        codex_mock.chmod(0o755)
        codex_called = tmp_path / "codex-called.txt"

        workflow_mock = tmp_path / "workflow-mock"
        workflow_mock.write_text(
            "import os, sys\n"
            "stdin = sys.stdin.read()\n"
            "print('WORKFLOW_CALLED=1')\n"
            "print(f\"WORKFLOW_CLD_ROUTE_PROFILE={os.environ.get('CLD_ROUTE_PROFILE', '')}\")\n"
            "print(f\"WORKFLOW_CLD_COMPACT_OUTPUT={os.environ.get('CLD_COMPACT_OUTPUT', '')}\")\n"
            "print('WORKFLOW_ARGS=' + ' '.join(sys.argv[1:]))\n"
            "if 'mock bead context' in stdin:\n"
            "    print('WORKFLOW_STDIN_HAS_CONTEXT=True')\n",
            encoding="utf-8",
        )
        workflow_mock.chmod(0o755)

        bd_mock = tmp_path / "bd-mock"
        bd_mock.write_text(
            "#!/bin/sh\n"
            "if [ \"$1\" = show ]; then\n"
            "  printf 'mock bead context for %s\\n' \"$2\"\n"
            "  exit 0\n"
            "fi\n"
            "exit 1\n",
            encoding="utf-8",
        )
        bd_mock.chmod(0o755)

        env = dict(os.environ)
        env["CODEX_BIN"] = str(codex_mock)
        env["CODEX_CALLED_FILE"] = str(codex_called)
        env["BD_BIN"] = str(bd_mock)
        env["CDX_BEAD_WORKFLOW_SCRIPT"] = str(workflow_mock)
        env["CDX_BEAD_WORKFLOW"] = "python"

        result = subprocess.run(
            [str(_CDX_BIN), "-b", "CL-smoke", "--route-profile", "cdx-composer"],
            capture_output=True,
            text=True,
            check=False,
            env=env,
        )

        assert result.returncode == 0
        assert not codex_called.exists()
        assert "WORKFLOW_CALLED=1" in result.stdout
        assert "WORKFLOW_CLD_ROUTE_PROFILE=cdx-composer" in result.stdout
        assert "WORKFLOW_CLD_COMPACT_OUTPUT=1" in result.stdout
        assert "CL-smoke" in result.stdout
        assert "--route-profile cdx-composer" in result.stdout
        assert "WORKFLOW_STDIN_HAS_CONTEXT=True" in result.stdout

    def test_cdx_b_defaults_to_codex_orchestrator_with_composer_profile(self, tmp_path: Path) -> None:
        """Default full cdx -b starts Codex as the top-level bead orchestrator."""
        workflow_mock = tmp_path / "workflow-mock"
        workflow_mock.write_text(
            "#!/bin/sh\n"
            "touch \"$WORKFLOW_CALLED_FILE\"\n"
            "printf 'WORKFLOW_SHOULD_NOT_RUN\\n'\n",
            encoding="utf-8",
        )
        workflow_mock.chmod(0o755)
        workflow_called = tmp_path / "workflow-called.txt"

        bd_mock = tmp_path / "bd-mock"
        bd_mock.write_text(
            "#!/bin/sh\n"
            "if [ \"$1\" = show ]; then\n"
            "  printf 'mock bead context for %s\\n' \"$2\"\n"
            "  exit 0\n"
            "fi\n"
            "exit 1\n",
            encoding="utf-8",
        )
        bd_mock.chmod(0o755)

        codex_mock = tmp_path / "codex-mock"
        codex_args = tmp_path / "codex-args.txt"
        codex_prompt = tmp_path / "codex-prompt.txt"
        codex_mock.write_text(
            "#!/bin/sh\n"
            "touch \"$CODEX_CALLED_FILE\"\n"
            "printf 'CODEX_CLD_ROUTE_PROFILE=%s\\n' \"$CLD_ROUTE_PROFILE\"\n"
            "printf 'CODEX_CLD_COMPACT_OUTPUT=%s\\n' \"$CLD_COMPACT_OUTPUT\"\n"
            "printf '%s\\n' \"$*\" > \"$CODEX_ARGS_FILE\"\n"
            "last=''\n"
            "for arg in \"$@\"; do last=\"$arg\"; done\n"
            "printf '%s' \"$last\" > \"$CODEX_PROMPT_FILE\"\n",
            encoding="utf-8",
        )
        codex_mock.chmod(0o755)
        codex_called = tmp_path / "codex-called.txt"

        env = dict(os.environ)
        env["BD_BIN"] = str(bd_mock)
        env["CODEX_BIN"] = str(codex_mock)
        env["CODEX_ARGS_FILE"] = str(codex_args)
        env["CODEX_CALLED_FILE"] = str(codex_called)
        env["CODEX_PROMPT_FILE"] = str(codex_prompt)
        env["CDX_BEAD_WORKFLOW_SCRIPT"] = str(workflow_mock)
        env["WORKFLOW_CALLED_FILE"] = str(workflow_called)
        env["CLD_COMPACT_OUTPUT"] = "0"

        result = subprocess.run(
            [str(_CDX_BIN), "-b", "CL-smoke"],
            capture_output=True,
            text=True,
            check=False,
            env=env,
        )

        assert result.returncode == 0
        assert codex_called.exists()
        assert not workflow_called.exists()
        assert "CODEX_CLD_ROUTE_PROFILE=cdx-composer" in result.stdout
        assert "CODEX_CLD_COMPACT_OUTPUT=0" in result.stdout
        assert "exec --dangerously-bypass-approvals-and-sandbox" in codex_args.read_text(
            encoding="utf-8"
        )
        prompt = codex_prompt.read_text(encoding="utf-8")
        assert "implement bead CL-smoke with the bead-orchestrator agent/workflow" in prompt
        assert "mock bead context for CL-smoke" in prompt
        assert "Route profile: cdx-composer" in prompt
        assert "BEAD_REVIEWER_REFRESH_REQUIRED" in prompt
        assert "Cursor/Composer" in prompt

    def test_cld_b_still_uses_agent_orchestrator_path(self) -> None:
        """cld -b remains on the existing Claude agent path."""
        cld_source = _CLD_BIN.read_text(encoding="utf-8")
        assert 'claude_args+=("--agent" "bead-orchestrator")' in cld_source
        assert "cdx-bead-workflow.py" not in cld_source


class TestLauncherMissingBeadGuard:
    """Regression: bead launchers must not start agents for non-local beads."""

    @staticmethod
    def _write_executable(path: Path, content: str) -> Path:
        path.write_text(content, encoding="utf-8")
        path.chmod(0o755)
        return path

    @pytest.mark.parametrize("flag", ["-b", "-bq"])
    def test_cld_bead_modes_abort_when_bead_is_missing(self, tmp_path: Path, flag: str) -> None:
        called = tmp_path / "claude-called"
        claude_mock = self._write_executable(
            tmp_path / "claude-mock",
            "#!/bin/sh\n"
            "touch \"$CALLED_FILE\"\n"
            "printf 'CLAUDE_CALLED\\n'\n",
        )
        bd_mock = self._write_executable(
            tmp_path / "bd-mock",
            "#!/bin/sh\n"
            "if [ \"$1\" = config ] && [ \"$2\" = get ] && [ \"$3\" = issue_prefix ]; then\n"
            "  printf 'mira\\n'\n"
            "  exit 0\n"
            "fi\n"
            "if [ \"$1\" = show ]; then\n"
            "  printf 'Error fetching %s: no issue found\\n' \"$2\" >&2\n"
            "  exit 1\n"
            "fi\n"
            "exit 1\n",
        )

        env = dict(os.environ)
        env["CLAUDE_BIN"] = str(claude_mock)
        env["BD_BIN"] = str(bd_mock)
        env["CALLED_FILE"] = str(called)

        result = subprocess.run(
            [str(_CLD_BIN), flag, "polaris-nxcc"],
            capture_output=True,
            text=True,
            check=False,
            env=env,
        )

        assert result.returncode == 2
        assert not called.exists()
        assert "polaris-nxcc was not found in this repository" in result.stderr
        assert "Aborting before launching Claude" in result.stderr

    @pytest.mark.parametrize("flag", ["-b", "-bq"])
    def test_cdx_bead_modes_abort_when_bead_is_missing(self, tmp_path: Path, flag: str) -> None:
        called = tmp_path / "codex-called"
        codex_mock = self._write_executable(
            tmp_path / "codex-mock",
            "#!/bin/sh\n"
            "touch \"$CALLED_FILE\"\n"
            "printf 'CODEX_CALLED\\n'\n",
        )
        bd_mock = self._write_executable(
            tmp_path / "bd-mock",
            "#!/bin/sh\n"
            "if [ \"$1\" = show ]; then\n"
            "  printf 'Error fetching %s: no issue found\\n' \"$2\" >&2\n"
            "  exit 1\n"
            "fi\n"
            "exit 1\n",
        )

        env = dict(os.environ)
        env["CODEX_BIN"] = str(codex_mock)
        env["BD_BIN"] = str(bd_mock)
        env["CALLED_FILE"] = str(called)

        result = subprocess.run(
            [str(_CDX_BIN), flag, "polaris-nxcc"],
            capture_output=True,
            text=True,
            check=False,
            env=env,
        )

        assert result.returncode == 2
        assert not called.exists()
        assert "Bead polaris-nxcc was not found in this repository" in result.stderr
        assert "Aborting before launching Codex" in result.stderr
