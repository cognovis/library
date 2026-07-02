"""Tests for slot-based adapter dispatch -- CL-iye.4.

AC coverage:
  AC3: Dispatch is based on slot.adapter, not model-name prefix matching
  AC4: Backward compatibility: legacy route_decision.impl_model fallback when execution_plan absent
  AC5: cdx-composer fixture proves Phase 5 and repair/fix slots both route to cursor-impl
  AC6: cld-default and cdx-default fixtures preserve current behavior
  AC7: Phase Progress marker format remains compatible with wave-monitor
"""

from __future__ import annotations

import importlib.util
import re
from pathlib import Path

import pytest
import yaml


def _find_library_root() -> Path:
    here = Path(__file__).resolve()
    for parent in here.parents:
        if parent.name == "meta" and (parent / "bin" / "cld").exists():
            return parent.parent
    return Path("/nonexistent/library")


_LIBRARY_ROOT = _find_library_root()
_RESOLVE_SCRIPT = (
    _LIBRARY_ROOT / "cognovis-core" / "skills" / "beads" / "scripts" / "resolve_slot_dispatch.py"
)
_USER_GLOBAL_CONFIG = Path.home() / ".agents" / "orchestrator-config.yml"
_COGNOVIS_CONFIG = _LIBRARY_ROOT / "cognovis-core" / ".agents" / "orchestrator-config.yml"
_COGNOVIS_ROOT = _LIBRARY_ROOT / "cognovis-core"
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

    def test_cld_default_implementation_adapter_is_codex_impl(self) -> None:
        mod = _load_resolve_module()
        config = _load_config(_USER_GLOBAL_CONFIG)
        ep = _make_execution_plan("cld-default", config)
        dispatch = mod.resolve_impl_dispatch(
            ep, "full", "implementation", fallback_impl_model="gpt-5.5"
        )
        assert dispatch["adapter"] == "codex-impl"
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
            None, "full", "implementation", fallback_impl_model="gpt-5.5"
        )
        assert dispatch["adapter"] == "codex-impl"
        assert dispatch["source"] == "legacy"

    def test_legacy_claude_maps_to_claude_agent(self) -> None:
        mod = _load_resolve_module()
        dispatch = mod.resolve_impl_dispatch(
            None, "full", "implementation", fallback_impl_model="claude-opus-4-8"
        )
        assert dispatch["adapter"] == "claude-agent"
        assert dispatch["source"] == "legacy"

    def test_legacy_gpt_maps_to_codex_impl(self) -> None:
        mod = _load_resolve_module()
        dispatch = mod.resolve_impl_dispatch(
            None, "quick", "implementation", fallback_impl_model="gpt-5.4-mini"
        )
        assert dispatch["adapter"] == "codex-impl"
        assert dispatch["source"] == "legacy"

    def test_legacy_codex_maps_to_codex_impl(self) -> None:
        mod = _load_resolve_module()
        dispatch = mod.resolve_impl_dispatch(
            None, "full", "implementation", fallback_impl_model="codex"
        )
        assert dispatch["adapter"] == "codex-impl"
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
    """AC6: cld-default and cdx-default fixture values unchanged."""

    @pytest.fixture(params=["user_global", "cognovis_core"])
    def config(self, request):
        if request.param == "user_global":
            return _load_config(_USER_GLOBAL_CONFIG)
        return _load_config(_COGNOVIS_CONFIG)

    def test_cld_default_full_implementation_is_codex_impl(self, config: dict) -> None:
        impl = config["route_profiles"]["cld-default"]["slots"]["full"]["implementation"]
        assert impl["adapter"] == "codex-impl"
        assert impl["harness"] == "codex"
        assert impl["model"] == "gpt-5.5"

    def test_cld_default_quick_implementation_is_codex_impl(self, config: dict) -> None:
        impl = config["route_profiles"]["cld-default"]["slots"]["quick"]["implementation"]
        assert impl["adapter"] == "codex-impl"
        assert impl["harness"] == "codex"
        assert impl["model"] == "gpt-5.4-mini"

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


class TestPhaseProgressMarkerFormat:
    """AC7: Phase Progress markers unchanged and parseable by wave-monitor."""

    _MARKER_RE = re.compile(
        r"^phase: \d+ \| name: \w+ \| status: \w+",
        re.MULTILINE,
    )

    def test_bead_orchestrator_contains_phase_progress_header(self) -> None:
        if not _BEAD_ORCH_PATH.exists():
            pytest.skip(f"bead-orchestrator.md not found at {_BEAD_ORCH_PATH}")
        content = _BEAD_ORCH_PATH.read_text(encoding="utf-8")
        assert "### Phase Progress" in content

    def test_bead_orchestrator_phase_progress_marker_format_valid(self) -> None:
        if not _BEAD_ORCH_PATH.exists():
            pytest.skip(f"bead-orchestrator.md not found at {_BEAD_ORCH_PATH}")
        content = _BEAD_ORCH_PATH.read_text(encoding="utf-8")
        markers = self._MARKER_RE.findall(content)
        assert len(markers) > 0, "bead-orchestrator.md must contain Phase Progress markers"

    def test_phase_progress_p5_impl_marker_present(self) -> None:
        if not _BEAD_ORCH_PATH.exists():
            pytest.skip(f"bead-orchestrator.md not found at {_BEAD_ORCH_PATH}")
        content = _BEAD_ORCH_PATH.read_text(encoding="utf-8")
        assert "phase: 5 | name: p5_impl | status: in_progress | iteration:" in content

    def test_phase_progress_p5_review_marker_present(self) -> None:
        if not _BEAD_ORCH_PATH.exists():
            pytest.skip(f"bead-orchestrator.md not found at {_BEAD_ORCH_PATH}")
        content = _BEAD_ORCH_PATH.read_text(encoding="utf-8")
        assert "phase: 5 | name: p5_review | status: in_progress | iteration:" in content

    def test_phase_progress_route_decision_format_unchanged(self) -> None:
        if not _BEAD_ORCH_PATH.exists():
            pytest.skip(f"bead-orchestrator.md not found at {_BEAD_ORCH_PATH}")
        content = _BEAD_ORCH_PATH.read_text(encoding="utf-8")
        assert "phase: 0 | name: route_decision | status: complete | route:" in content

    def test_no_new_phase_progress_marker_formats_introduced(self) -> None:
        """Marker format must stay: 'phase: N | name: X | status: Y'.

        Template lines (containing angle brackets like '<N>') are skipped since
        they are documentation examples, not live emitted markers.
        """
        if not _BEAD_ORCH_PATH.exists():
            pytest.skip(f"bead-orchestrator.md not found at {_BEAD_ORCH_PATH}")
        content = _BEAD_ORCH_PATH.read_text(encoding="utf-8")
        # Check lines immediately after ### Phase Progress markers.
        # Skip template lines (those containing angle brackets — they are examples).
        lines = content.splitlines()
        checked = 0
        for i, line in enumerate(lines):
            if line.strip() == "### Phase Progress" and i + 1 < len(lines):
                next_line = lines[i + 1].strip()
                if next_line and "<" not in next_line and ">" not in next_line:
                    assert re.match(r"^phase: \d+ \|", next_line), (
                        f"Phase Progress line at {i + 2} has non-canonical format: {next_line!r}"
                    )
                    checked += 1
        # Ensure we actually checked at least some real markers (not all were templates)
        assert checked > 0, "No non-template Phase Progress markers found"


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
        dispatch = mod.resolve_impl_dispatch(None, "full", "implementation", fallback_impl_model="gpt-5.5")
        assert dispatch["source"] == "legacy"
        assert dispatch["adapter"] == "codex-impl"

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
        """AC4: bead-orchestrator call sites do not suppress resolve_slot_dispatch errors when EXECUTION_PLAN is set."""
        if not _BEAD_ORCH_PATH.exists():
            pytest.skip(f"bead-orchestrator.md not found at {_BEAD_ORCH_PATH}")
        content = _BEAD_ORCH_PATH.read_text(encoding="utf-8")
        lines = content.splitlines()
        for i, line in enumerate(lines):
            if "resolve_slot_dispatch.py" in line and "EXECUTION_PLAN=" in line:
                assert "2>/dev/null" not in line, (
                    f"Line {i + 1} in bead-orchestrator.md blanket-suppresses stderr on "
                    f"resolve_slot_dispatch.py call with EXECUTION_PLAN: {line.strip()!r}"
                )

    def test_no_blanket_stderr_suppression_in_quick_fix(self) -> None:
        """AC4: quick-fix call sites do not suppress resolve_slot_dispatch errors when EXECUTION_PLAN is set."""
        _QF_PATH = _COGNOVIS_ROOT / "agents" / "quick-fix.md"
        if not _QF_PATH.exists():
            pytest.skip(f"quick-fix.md not found at {_QF_PATH}")
        content = _QF_PATH.read_text(encoding="utf-8")
        lines = content.splitlines()
        for i, line in enumerate(lines):
            if "resolve_slot_dispatch.py" in line and "EXECUTION_PLAN=" in line:
                assert "2>/dev/null" not in line, (
                    f"Line {i + 1} in quick-fix.md blanket-suppresses stderr on "
                    f"resolve_slot_dispatch.py call with EXECUTION_PLAN: {line.strip()!r}"
                )

    def test_quick_fix_cursor_dispatch_emits_leaf_marker(self) -> None:
        """Cursor Composer quick dispatch must be visible in noisy harness output."""
        _QF_PATH = _COGNOVIS_ROOT / "agents" / "quick-fix.md"
        if not _QF_PATH.exists():
            pytest.skip(f"quick-fix.md not found at {_QF_PATH}")
        content = _QF_PATH.read_text(encoding="utf-8")
        assert "## LEAF_DISPATCH workflow=quick slot=implementation" in content
        assert "adapter=$IMPL_SLOT_ADAPTER" in content
        assert "harness=${IMPL_SLOT_HARNESS:-cursor}" in content
        assert "model=$IMPL_SLOT_MODEL" in content
        assert "source=${IMPL_SLOT_SOURCE:-slot}" in content
        assert "## LEAF_DISPATCH workflow=quick slot=fix_loop" in content
        assert "adapter=$FIXLOOP_ADAPTER" in content
        assert "harness=${FIXLOOP_HARNESS:-cursor}" in content
        assert "model=$FIXLOOP_MODEL" in content
        assert "source=${FIXLOOP_SOURCE:-slot}" in content
