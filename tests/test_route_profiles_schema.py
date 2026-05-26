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

    def test_cdx_bq_route_profile_reaches_quick_fix_prompt(self, tmp_path: Path) -> None:
        """Regression: cdx -bq must propagate --route-profile to quick-fix."""
        codex_mock = tmp_path / "codex-mock"
        codex_mock.write_text(
            "#!/bin/sh\n"
            "printf 'CLD_ROUTE_PROFILE=%s\\n' \"${CLD_ROUTE_PROFILE-}\"\n"
            "i=0\n"
            "for arg in \"$@\"; do\n"
            "  i=$((i+1))\n"
            "  printf 'ARG_%s=%s\\n' \"$i\" \"$arg\"\n"
            "done\n",
            encoding="utf-8",
        )
        codex_mock.chmod(0o755)

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
        env["BD_BIN"] = str(bd_mock)

        result = subprocess.run(
            [str(_CDX_BIN), "-bq", "CL-smoke", "--route-profile", "cdx-composer"],
            capture_output=True,
            text=True,
            check=False,
            env=env,
        )

        assert result.returncode == 0
        assert "CLD_ROUTE_PROFILE=cdx-composer" in result.stdout
        assert "Route profile: cdx-composer" in result.stdout
