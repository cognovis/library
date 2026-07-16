"""Compatibility tests for the legacy route profile schema and launcher boundary.

AC coverage:
  AC1: orchestrator-config supports route_profiles with orchestrator, slots, adapter,
       harness, model, reasoning_effort, and timeout fields
  Launcher boundary: bin/cld and bin/cdx do not consume legacy routing policy
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


def _write_cdx_bd_mock(tmp_path: Path) -> Path:
    bd_mock = tmp_path / "bd-mock"
    bd_mock.write_text(
        "#!/bin/sh\n"
        "if [ \"$1\" = show ]; then\n"
        "  if [ \"$3\" = --json ]; then\n"
        "    printf '[{\"id\":\"%s\",\"status\":\"open\",\"title\":\"Smoke bead\",\"description\":\"mock bead context for %s\"}]\\n' \"$2\" \"$2\"\n"
        "  else\n"
        "    printf 'mock bead context for %s\\n' \"$2\"\n"
        "  fi\n"
        "  exit 0\n"
        "fi\n"
        "exit 1\n",
        encoding="utf-8",
    )
    bd_mock.chmod(0o755)
    return bd_mock


def _write_cdx_compact_context_script(tmp_path: Path) -> Path:
    """Renderer stand-in that emits a valid cdx.bead_context envelope.

    The launcher independently validates the envelope contract before trusting
    renderer output, so this fixture emits the real contract shape and embeds
    the bead id in a field value (existing assertions match ``compact context
    for <id>``).
    """
    compact_context_script = tmp_path / "compact-context.py"
    compact_context_script.write_text(
        "import json, sys\n"
        "payload = json.load(sys.stdin)\n"
        "bead = payload[0] if isinstance(payload, list) else payload\n"
        "envelope = {\n"
        "    'contract_version': '1',\n"
        "    'kind': 'cdx.bead_context',\n"
        "    'classification': 'untrusted',\n"
        "    'data': {\n"
        "        'fields': {\n"
        "            'summary': {\n"
        "                'source': 'bead.summary',\n"
        "                'trust': 'untrusted',\n"
        "                'untrusted': True,\n"
        "                'content_type': 'text/plain',\n"
        "                'value': f\"compact context for {bead['id']}\",\n"
        "            }\n"
        "        }\n"
        "    },\n"
        "    'meta': {'producer': 'route-profile-test-fixture', 'source': 'bd show --json'},\n"
        "}\n"
        "print(json.dumps(envelope, indent=2, sort_keys=True))\n",
        encoding="utf-8",
    )
    return compact_context_script


def _prepend_cdx_uv_mock(env: dict[str, str], tmp_path: Path) -> None:
    uv_mock = tmp_path / "uv"
    uv_mock.write_text(
        f"#!{sys.executable}\n"
        "import subprocess, sys\n"
        "args = sys.argv[1:]\n"
        "if not args or args[0] != 'run':\n"
        "    raise SystemExit(64)\n"
        "args = args[1:]\n"
        "while len(args) >= 2 and args[0] == '--with':\n"
        "    args = args[2:]\n"
        "if not args or args[0] != 'python':\n"
        "    raise SystemExit(65)\n"
        "raise SystemExit(subprocess.call([sys.executable, *args[1:]]))\n",
        encoding="utf-8",
    )
    uv_mock.chmod(0o755)
    env["PATH"] = f"{tmp_path}{os.pathsep}{env['PATH']}"


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
        assert impl["model"] == "gpt-5.5"
        assert impl["reasoning_effort"] == "medium"
        assert impl["harness"] == "codex"

    def test_cld_default_quick_slot_values(self, config: dict) -> None:
        slots = config["route_profiles"]["cld-default"]["slots"]["quick"]
        assert slots["implementation"]["model"] == "gpt-5.5"
        assert slots["implementation"]["reasoning_effort"] == "medium"
        assert slots["fix_loop"]["model"] == "gpt-5.5"
        assert slots["fix_loop"]["reasoning_effort"] == "high"
        assert slots["review"]["model"] == "claude-opus-4-8"
        assert slots["review"]["harness"] == "claude"
        assert slots["session_close"]["model"] == "sonnet"

    def test_cdx_default_full_implementation_values(self, config: dict) -> None:
        impl = config["route_profiles"]["cdx-default"]["slots"]["full"]["implementation"]
        assert impl["adapter"] == "claude-agent"
        assert impl["model"] == "opus"
        assert impl["harness"] == "claude"

    def test_cdx_default_quick_implementation_values(self, config: dict) -> None:
        impl = config["route_profiles"]["cdx-default"]["slots"]["quick"]["implementation"]
        assert impl["adapter"] == "claude-agent"
        assert impl["model"] == "haiku"
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


# ── Legacy configuration is not launcher authority ───────────────────────

class TestLauncherImplementationLoopBoundary:
    """Legacy configuration remains readable but does not control bead launchers."""

    @pytest.mark.parametrize("launcher", [_CLD_BIN, _CDX_BIN])
    def test_launcher_has_no_legacy_route_authority(self, launcher: Path) -> None:
        content = launcher.read_text(encoding="utf-8")

        for banned in (
            "route_profile",
            "phase0-claim.py",
            "resolve_slot_dispatch.py",
            "codex-impl.py",
            "codex-exec.py",
            "claude-impl.py",
            "cursor-impl.py",
        ):
            assert banned not in content

    @pytest.mark.parametrize("launcher", [_CLD_BIN, _CDX_BIN])
    def test_launcher_names_shared_loop_and_session_close(self, launcher: Path) -> None:
        content = launcher.read_text(encoding="utf-8")

        assert "bead-implementation-loop" in content
        assert "execution_mode=" in content
        assert "canonical Session Close" in content

    def test_cdx_b_default_mode_is_tui_and_documented(self) -> None:
        content = _CDX_BIN.read_text(encoding="utf-8")

        assert 'codex_bead_mode="${CDX_BEAD_CODEX_MODE:-tui}"' in content
        assert "force interactive Codex TUI mode (default)" in content
        assert "Full cdx -b defaults to TUI mode" in content
        assert "pass --exec for non-interactive" in content

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
