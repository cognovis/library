"""Tests for slot-based adapter dispatch -- CL-iye.4.

AC coverage:
  AC3: Dispatch is based on slot.adapter, not model-name prefix matching
  AC4: Backward compatibility: legacy route_decision.impl_model fallback when execution_plan absent
  AC5: cdx-composer fixture proves Phase 5 and repair/fix slots both route to cursor-impl
  AC6: cld-default and cdx-default fixtures preserve current behavior
  CL-e7dg: legacy agent names delegate lifecycle ownership to the native loop
"""

from __future__ import annotations

import importlib.util
import os
from pathlib import Path

import pytest
import yaml


_REPO_ROOT = Path(__file__).resolve().parent.parent
_COGNOVIS_ROOT = (
    Path(os.environ["COGNOVIS_CORE"]).expanduser()
    if os.environ.get("COGNOVIS_CORE")
    else _REPO_ROOT.parent / "cognovis-core"
)
_RESOLVE_SCRIPT = (
    _COGNOVIS_ROOT / "skills" / "cognovis-beads" / "scripts" / "resolve_slot_dispatch.py"
)
_USER_GLOBAL_CONFIG = Path.home() / ".agents" / "orchestrator-config.yml"
_COGNOVIS_CONFIG = _COGNOVIS_ROOT / ".agents" / "orchestrator-config.yml"
_BEAD_ORCH_PATH = _COGNOVIS_ROOT / "agents" / "bead-orchestrator.md"


def _load_resolve_module():
    if not _RESOLVE_SCRIPT.exists():
        pytest.skip(f"resolve_slot_dispatch.py not found at {_RESOLVE_SCRIPT}")
    spec = importlib.util.spec_from_file_location("resolve_slot_dispatch", _RESOLVE_SCRIPT)
    assert spec is not None
    assert spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _load_config(path: Path) -> dict:
    if not path.exists():
        pytest.skip(f"Config not found: {path}")
    return yaml.safe_load(path.read_text(encoding="utf-8")) or {}


def _make_execution_plan(profile_name: str, config: dict) -> dict:
    """Build an execution_plan dict from the config for testing."""
    profiles = config.get("route_profiles", {})
    profile = profiles.get(profile_name, {})
    return {
        "profile": profile_name,
        "workflow": "full",
        "slots": profile.get("slots", {}),
    }


class TestAdapterDispatch:
    """AC3: slot.adapter drives dispatch, not impl_model prefix."""

    def test_resolve_slot_returns_adapter_not_model(self) -> None:
        mod = _load_resolve_module()
        config = _load_config(_USER_GLOBAL_CONFIG)
        ep = _make_execution_plan("cld-default", config)
        slot = mod.resolve_slot(ep, "full", "implementation")
        assert slot is not None
        assert "adapter" in slot
        assert slot["adapter"] in mod.VALID_ADAPTERS

    def test_cld_default_implementation_adapter_is_codex_exec(self) -> None:
        mod = _load_resolve_module()
        config = _load_config(_USER_GLOBAL_CONFIG)
        ep = _make_execution_plan("cld-default", config)
        dispatch = mod.resolve_impl_dispatch(
            ep, "full", "implementation", fallback_impl_model="gpt-5.6-sol"
        )
        # CL-3gdz retired codex-impl; cld-default now routes codex slots via codex-exec.
        assert dispatch["adapter"] == "codex-exec"
        assert dispatch["source"] == "slot"

    def test_cdx_default_implementation_adapter_is_claude_agent(self) -> None:
        mod = _load_resolve_module()
        config = _load_config(_USER_GLOBAL_CONFIG)
        ep = _make_execution_plan("cdx-default", config)
        dispatch = mod.resolve_impl_dispatch(
            ep, "full", "implementation", fallback_impl_model="claude-opus-4-8"
        )
        assert dispatch["adapter"] == "claude-agent"
        assert dispatch["source"] == "slot"

    def test_cdx_composer_implementation_adapter_is_cursor_composer(self) -> None:
        mod = _load_resolve_module()
        config = _load_config(_USER_GLOBAL_CONFIG)
        ep = _make_execution_plan("cdx-composer", config)
        dispatch = mod.resolve_impl_dispatch(ep, "full", "implementation")
        assert dispatch["adapter"] == "cursor-composer"
        assert dispatch["source"] == "slot"

    def test_dispatch_source_is_slot_when_execution_plan_present(self) -> None:
        mod = _load_resolve_module()
        config = _load_config(_USER_GLOBAL_CONFIG)
        ep = _make_execution_plan("cld-default", config)
        dispatch = mod.resolve_impl_dispatch(
            ep, "full", "implementation", fallback_impl_model="gpt-5.5"
        )
        assert dispatch["source"] == "slot"


class TestLegacyFallback:
    """AC4: legacy route_decision.impl_model fallback when execution_plan absent."""

    def test_resolve_slot_returns_none_when_execution_plan_absent(self) -> None:
        mod = _load_resolve_module()
        result = mod.resolve_slot(None, "full", "implementation")
        assert result is None

    def test_dispatch_uses_legacy_when_execution_plan_none(self) -> None:
        mod = _load_resolve_module()
        dispatch = mod.resolve_impl_dispatch(
            None, "full", "implementation", fallback_impl_model="gpt-5.6-sol"
        )
        # CL-3gdz: legacy codex/gpt impl_models normalize to codex-exec.
        assert dispatch["adapter"] == "codex-exec"
        assert dispatch["source"] == "legacy"

    def test_legacy_claude_maps_to_claude_agent(self) -> None:
        mod = _load_resolve_module()
        dispatch = mod.resolve_impl_dispatch(
            None, "full", "implementation", fallback_impl_model="claude-opus-4-8"
        )
        assert dispatch["adapter"] == "claude-agent"
        assert dispatch["source"] == "legacy"

    def test_legacy_gpt_maps_to_codex_exec(self) -> None:
        mod = _load_resolve_module()
        dispatch = mod.resolve_impl_dispatch(
            None, "quick", "implementation", fallback_impl_model="gpt-5.4-mini"
        )
        # CL-3gdz: gpt-family legacy impl_models normalize to codex-exec.
        assert dispatch["adapter"] == "codex-exec"
        assert dispatch["source"] == "legacy"

    def test_legacy_codex_maps_to_codex_exec(self) -> None:
        mod = _load_resolve_module()
        dispatch = mod.resolve_impl_dispatch(
            None, "full", "implementation", fallback_impl_model="codex"
        )
        # CL-3gdz: the "codex" legacy impl_model normalizes to codex-exec.
        assert dispatch["adapter"] == "codex-exec"
        assert dispatch["source"] == "legacy"

    def test_legacy_unknown_model_raises(self) -> None:
        mod = _load_resolve_module()
        with pytest.raises(mod.SlotDispatchError):
            mod.resolve_impl_dispatch(
                None, "full", "implementation", fallback_impl_model="gemini-pro"
            )

    def test_no_execution_plan_and_no_fallback_raises(self) -> None:
        mod = _load_resolve_module()
        with pytest.raises(mod.SlotDispatchError):
            mod.resolve_impl_dispatch(None, "full", "implementation")


class TestCdxComposerFixSlots:
    """AC5: cdx-composer fixture routes Phase 5 and repair/fix slots to cursor-impl."""

    @pytest.fixture(params=["user_global", "cognovis_core"])
    def config(self, request):
        if request.param == "user_global":
            return _load_config(_USER_GLOBAL_CONFIG)
        return _load_config(_COGNOVIS_CONFIG)

    def test_cdx_composer_full_implementation_is_cursor(self, config: dict) -> None:
        impl = config["route_profiles"]["cdx-composer"]["slots"]["full"]["implementation"]
        assert impl["adapter"] == "cursor-composer", "Phase 5 must use cursor-composer"
        assert impl["harness"] == "cursor"

    def test_cdx_composer_full_regression_fix_is_cursor(self, config: dict) -> None:
        regfix = config["route_profiles"]["cdx-composer"]["slots"]["full"]["regression_fix"]
        assert regfix["adapter"] == "cursor-composer"
        assert regfix["harness"] == "cursor"

    def test_cdx_composer_full_verification_fix_is_cursor(self, config: dict) -> None:
        verfix = config["route_profiles"]["cdx-composer"]["slots"]["full"]["verification_fix"]
        assert verfix["adapter"] == "cursor-composer"
        assert verfix["harness"] == "cursor"

    def test_cdx_composer_quick_fix_loop_is_cursor(self, config: dict) -> None:
        fix_loop = config["route_profiles"]["cdx-composer"]["slots"]["quick"]["fix_loop"]
        assert fix_loop["adapter"] == "cursor-composer"
        assert fix_loop["harness"] == "cursor"

    def test_cdx_composer_repair_slots_not_codex_impl(self, config: dict) -> None:
        full = config["route_profiles"]["cdx-composer"]["slots"]["full"]
        for slot_name in ("regression_fix", "verification_fix"):
            assert full[slot_name]["adapter"] != "codex-impl"

    def test_cdx_composer_repair_slots_not_claude_agent(self, config: dict) -> None:
        full = config["route_profiles"]["cdx-composer"]["slots"]["full"]
        for slot_name in ("regression_fix", "verification_fix"):
            assert full[slot_name]["adapter"] != "claude-agent"


class TestCurrentBehaviorPreserved:
    """AC6: cld-default and cdx-default fixture values remain explicit."""

    @pytest.fixture(params=["user_global", "cognovis_core"])
    def config(self, request):
        if request.param == "user_global":
            return _load_config(_USER_GLOBAL_CONFIG)
        return _load_config(_COGNOVIS_CONFIG)

    def test_cld_default_full_implementation_is_codex_exec(self, config: dict) -> None:
        # CL-3gdz retired codex-impl -> codex-exec (gpt-5.6-sol) for cld-default.
        impl = config["route_profiles"]["cld-default"]["slots"]["full"]["implementation"]
        assert impl["adapter"] == "codex-exec"
        assert impl["harness"] == "codex"
        assert impl["model"] == "gpt-5.6-sol"

    def test_cld_default_quick_implementation_is_codex_exec(self, config: dict) -> None:
        # CL-3gdz retired codex-impl -> codex-exec (gpt-5.6-sol) for cld-default.
        impl = config["route_profiles"]["cld-default"]["slots"]["quick"]["implementation"]
        assert impl["adapter"] == "codex-exec"
        assert impl["harness"] == "codex"
        assert impl["model"] == "gpt-5.6-sol"
        assert impl["reasoning_effort"] == "medium"

    def test_cld_default_regression_fix_is_claude_agent(self, config: dict) -> None:
        regfix = config["route_profiles"]["cld-default"]["slots"]["full"]["regression_fix"]
        assert regfix["adapter"] == "claude-agent"
        assert regfix["harness"] == "claude"

    def test_cdx_default_full_implementation_is_claude_agent(self, config: dict) -> None:
        impl = config["route_profiles"]["cdx-default"]["slots"]["full"]["implementation"]
        assert impl["adapter"] == "claude-agent"
        assert impl["harness"] == "claude"
        assert impl["model"] == "opus"

    def test_cdx_default_quick_implementation_is_claude_agent(self, config: dict) -> None:
        impl = config["route_profiles"]["cdx-default"]["slots"]["quick"]["implementation"]
        assert impl["adapter"] == "claude-agent"
        assert impl["harness"] == "claude"
        assert impl["model"] == "haiku"


class TestNativeLoopCompatibilityRedirects:
    """CL-e7dg: legacy agent names delegate lifecycle ownership to the native loop."""

    @staticmethod
    def _source(name: str) -> tuple[dict, str]:
        path = _COGNOVIS_ROOT / "agents" / f"{name}.md"
        if not path.exists():
            pytest.skip(f"{name}.md not found at {path}")
        content = path.read_text(encoding="utf-8")
        frontmatter = yaml.safe_load(content.split("---", 2)[1]) or {}
        return frontmatter, content

    def test_regression_bead_orchestrator_delegates_to_native_loop(self) -> None:
        frontmatter, content = self._source("bead-orchestrator")
        assert frontmatter.get("requires") == ["skill:bead-implementation-loop"]
        assert "STATUS: DEPRECATED COMPATIBILITY REDIRECT" in content
        assert "Invoke `bead-implementation-loop` exactly once" in content
        assert "### Phase Progress" not in content
        assert "resolve_slot_dispatch.py" not in content

    def test_regression_quick_fix_delegates_quick_mode_to_native_loop(self) -> None:
        frontmatter, content = self._source("quick-fix")
        assert frontmatter.get("requires") == ["skill:bead-implementation-loop"]
        assert "STATUS: DEPRECATED COMPATIBILITY REDIRECT" in content
        assert "Invoke `bead-implementation-loop` exactly once" in content
        assert "the bead ID and `quick` mode" in content
        assert "Spawn `bead-orchestrator` once" not in content
        assert "resolve_slot_dispatch.py" not in content


class TestSlotDispatchErrorPropagation:
    """CL-iye.9: present execution_plan missing required slots fails loudly."""

    def test_full_workflow_missing_slot_raises(self) -> None:
        """AC1: present execution_plan missing full.implementation raises SlotDispatchError."""
        mod = _load_resolve_module()
        # Plan with only quick slots — full slot is absent
        ep = {
            "profile": "cld-default",
            "workflow": "quick",
            "slots": {
                "quick": {
                    "implementation": {"adapter": "codex-impl", "harness": "codex", "model": "gpt-5.4-mini"}
                }
            },
        }
        with pytest.raises(mod.SlotDispatchError, match="full.implementation"):
            mod.resolve_slot(ep, "full", "implementation")

    def test_quick_workflow_missing_slot_raises(self) -> None:
        """AC2: present execution_plan missing quick.implementation raises SlotDispatchError."""
        mod = _load_resolve_module()
        # Plan with only full slots — quick slot is absent
        ep = {
            "profile": "cld-default",
            "workflow": "full",
            "slots": {
                "full": {
                    "implementation": {"adapter": "codex-impl", "harness": "codex", "model": "gpt-5.5"}
                }
            },
        }
        with pytest.raises(mod.SlotDispatchError, match="quick.implementation"):
            mod.resolve_slot(ep, "quick", "implementation")

    def test_absent_execution_plan_uses_legacy_fallback(self) -> None:
        """AC3: no execution_plan => legacy fallback, no SlotDispatchError."""
        mod = _load_resolve_module()
        dispatch = mod.resolve_impl_dispatch(None, "full", "implementation", fallback_impl_model="gpt-5.6-sol")
        assert dispatch["source"] == "legacy"
        # CL-3gdz: legacy codex/gpt fallback normalizes to codex-exec.
        assert dispatch["adapter"] == "codex-exec"

    def test_slot_dispatch_error_contains_slot_name(self) -> None:
        """AC5: SlotDispatchError message identifies the missing slot name."""
        mod = _load_resolve_module()
        ep = {
            "profile": "test-profile",
            "workflow": "full",
            "slots": {"full": {}},  # empty — no slots defined
        }
        with pytest.raises(mod.SlotDispatchError) as exc_info:
            mod.resolve_slot(ep, "full", "implementation")
        assert "implementation" in str(exc_info.value)
        assert "full" in str(exc_info.value)

    def test_no_blanket_stderr_suppression_in_bead_orchestrator(self) -> None:
        """The compatibility redirect does not retain legacy slot dispatch calls."""
        if not _BEAD_ORCH_PATH.exists():
            pytest.skip(f"bead-orchestrator.md not found at {_BEAD_ORCH_PATH}")
        content = _BEAD_ORCH_PATH.read_text(encoding="utf-8")
        assert "resolve_slot_dispatch.py" not in content
