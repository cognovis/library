#!/usr/bin/env python3
"""
test_runtime_config_compose.py — Compose / deploy / audit tests for runtime-config.

Bead: CL-7ipt

Covers the acceptance criteria:
  AC1: deploy regenerates the target reproducibly (idempotent) — no hand-copy.
  AC2: global-only sections (bead_claim/effort_classifier) preserved via overlay.
  AC3: composed config carries opus routing (no sonnet routing in gsd/session_close).
  AC4: audit detects when the deployed file diverges from the composed source.
  AC5: adapter drift reconciled to active-context (base source value wins).

All tests are hermetic: sources are local fixture files and the lockfile/deploy
target live under tmp_path — the live ~/.agents/orchestrator-config.yml and the
real global lockfile are never touched.
"""

import sys
from pathlib import Path

import pytest

yaml = pytest.importorskip("yaml")

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "scripts"))

from lib.runtime_config import (  # noqa: E402
    audit_runtime_config,
    compose_runtime_config,
    install_runtime_config,
    resolve_target_path,
)


BASE_YAML = """# routing baseline
model_tiers:
  known_models:
    - opus
    - sonnet
  gsd:
    reviewer_model: opus  # sonnet retired from routing
perspective_policy:
  cld:
    tier_impl_override:
      gsd: opus     # standard cross-model implementer
route_profiles:
  cld-default:
    slots:
      full:
        session_close:
          adapter: claude-agent
          model: opus
        verification:
          adapter: active-context
          model: opus
"""

OVERLAY_YAML = """# global-only overlay
bead_claim:
  # global-only server role
  effort_classifier:
    adapter: codex-exec
    provider: codex
    model: gpt-5.4-mini
    reasoning_effort: medium
    timeout_sec: 120
"""


def _iter_scalars(node, path=""):
    if isinstance(node, dict):
        for k, v in node.items():
            yield from _iter_scalars(v, f"{path}/{k}")
    elif isinstance(node, list):
        for i, v in enumerate(node):
            yield from _iter_scalars(v, f"{path}[{i}]")
    else:
        yield path, node


def _routing_sonnet_hits(data: dict) -> list[str]:
    """Return paths where 'sonnet' is used as a routing VALUE (not the allowlist)."""
    hits = []
    for path, value in _iter_scalars(data, ""):
        if value == "sonnet" and "known_models" not in path:
            hits.append(path)
    return hits


@pytest.fixture
def sources(tmp_path):
    base = tmp_path / "orchestrator-config.base.yml"
    overlay = tmp_path / "orchestrator-config.global-overlay.yml"
    base.write_text(BASE_YAML, encoding="utf-8")
    overlay.write_text(OVERLAY_YAML, encoding="utf-8")
    return base, overlay


@pytest.fixture
def catalog(tmp_path, sources):
    base, overlay = sources
    return {
        "default_dirs": {
            "runtime_configs": [
                {"default": ".agents/"},
                {"global": "~/.agents/"},
            ],
        },
        "library": {
            "runtime_configs": [
                {
                    "name": "orchestrator-config",
                    "description": "Composed global orchestrator-config.",
                    "base": str(base),
                    "global_overlay": str(overlay),
                    "deploy_filename": "orchestrator-config.yml",
                }
            ]
        },
    }


# --------------------------------------------------------------------------
# compose (pure function)
# --------------------------------------------------------------------------

def test_compose_preserves_overlay_sections():
    """AC2: overlay's global-only sections land in the composed output."""
    out = compose_runtime_config(BASE_YAML, OVERLAY_YAML)
    data = yaml.safe_load(out)
    assert "bead_claim" in data
    assert data["bead_claim"]["effort_classifier"]["adapter"] == "codex-exec"
    # base sections still present
    assert "route_profiles" in data
    assert "model_tiers" in data


def test_compose_preserves_base_comments():
    """Section-level merge keeps base + overlay comments (readability contract)."""
    out = compose_runtime_config(BASE_YAML, OVERLAY_YAML)
    assert "# routing baseline" in out
    assert "# global-only overlay" in out or "# global-only server role" in out


def test_compose_carries_opus_no_sonnet_routing():
    """AC3: opus routing present; no sonnet used as a routing value."""
    out = compose_runtime_config(BASE_YAML, OVERLAY_YAML)
    data = yaml.safe_load(out)
    assert data["perspective_policy"]["cld"]["tier_impl_override"]["gsd"] == "opus"
    assert (
        data["route_profiles"]["cld-default"]["slots"]["full"]["session_close"]["model"]
        == "opus"
    )
    assert _routing_sonnet_hits(data) == []


def test_compose_is_idempotent():
    """AC1: composing the same inputs is deterministic (identical bytes).

    True idempotency of `library sync` = same base + overlay -> same deployed
    file every run (also exercised end-to-end by test_deploy_and_idempotent_resync).
    We do NOT re-feed the composed output as a new base: the overlay's global-only
    sections would then collide with the (now merged) base, which compose rejects
    by design (see test_compose_rejects_base_overlay_section_collision).
    """
    out1 = compose_runtime_config(BASE_YAML, OVERLAY_YAML)
    out2 = compose_runtime_config(BASE_YAML, OVERLAY_YAML)
    assert out1 == out2


def test_compose_empty_overlay_is_base_only():
    out = compose_runtime_config(BASE_YAML, "")
    data = yaml.safe_load(out)
    assert "bead_claim" not in data
    assert "model_tiers" in data


def test_compose_reconciles_adapter_to_active_context():
    """AC5: the base's active-context adapter is what the composed output carries."""
    out = compose_runtime_config(BASE_YAML, OVERLAY_YAML)
    assert "adapter: active-context" in out
    assert "mcp-smoke" not in out


def test_compose_rejects_base_overlay_section_collision():
    """AC2: an overlay that shares a top-level section with the base is rejected.

    The overlay must carry only global-only sections. A colliding section (here
    'route_profiles', which also exists in the base) would silently clobber the
    routing baseline, so compose must raise a clear error instead of merging it.
    """
    from lib.errors import InstallError

    colliding_overlay = OVERLAY_YAML + "\nroute_profiles:\n  rogue:\n    slots: {}\n"
    with pytest.raises(InstallError) as exc:
        compose_runtime_config(BASE_YAML, colliding_overlay)
    assert "route_profiles" in str(exc.value)


# --------------------------------------------------------------------------
# deploy + audit (project scope, tmp_path isolation)
# --------------------------------------------------------------------------

def test_deploy_and_idempotent_resync(catalog, tmp_path):
    """AC1: deploy writes the composed file; a second deploy is byte-identical."""
    target = tmp_path / "deployed.yml"
    r1 = install_runtime_config(
        catalog, "orchestrator-config", repo_root=tmp_path,
        scope="project", target_override=target,
    )
    assert r1["status"] == "ok"
    first = target.read_text()
    sha1 = r1["data"]["content_sha256"]

    r2 = install_runtime_config(
        catalog, "orchestrator-config", repo_root=tmp_path,
        scope="project", target_override=target,
    )
    assert target.read_text() == first
    assert r2["data"]["content_sha256"] == sha1


def test_deploy_preserves_bead_claim(catalog, tmp_path):
    """AC2: deployed global config keeps bead_claim/effort_classifier."""
    target = tmp_path / "deployed.yml"
    install_runtime_config(
        catalog, "orchestrator-config", repo_root=tmp_path,
        scope="project", target_override=target,
    )
    data = yaml.safe_load(target.read_text())
    assert data["bead_claim"]["effort_classifier"]["model"] == "gpt-5.4-mini"


def test_audit_clean_after_deploy(catalog, tmp_path):
    target = tmp_path / "deployed.yml"
    install_runtime_config(
        catalog, "orchestrator-config", repo_root=tmp_path,
        scope="project", target_override=target,
    )
    result = audit_runtime_config(
        catalog, "orchestrator-config", repo_root=tmp_path,
        scope="project", target_override=target,
    )
    assert result["status"] == "clean"
    assert result["drift"] is False


def test_audit_detects_hand_edit(catalog, tmp_path):
    """AC4: a hand-edited deployed file is reported as drift."""
    target = tmp_path / "deployed.yml"
    install_runtime_config(
        catalog, "orchestrator-config", repo_root=tmp_path,
        scope="project", target_override=target,
    )
    target.write_text(target.read_text() + "\nrogue_key: true\n")
    result = audit_runtime_config(
        catalog, "orchestrator-config", repo_root=tmp_path,
        scope="project", target_override=target,
    )
    assert result["drift"] is True
    assert result["status"] == "drift"


def test_audit_reports_missing_target(catalog, tmp_path):
    target = tmp_path / "never-deployed.yml"
    result = audit_runtime_config(
        catalog, "orchestrator-config", repo_root=tmp_path,
        scope="project", target_override=target,
    )
    assert result["drift"] is True
    assert result["status"] == "missing"


def test_audit_detects_source_change(catalog, tmp_path, sources):
    """AC4: audit re-composes from source, so a source change without re-sync drifts."""
    base, _overlay = sources
    target = tmp_path / "deployed.yml"
    install_runtime_config(
        catalog, "orchestrator-config", repo_root=tmp_path,
        scope="project", target_override=target,
    )
    # Change the base source but do NOT re-deploy.
    base.write_text(BASE_YAML + "\nnew_section:\n  added: true\n", encoding="utf-8")
    result = audit_runtime_config(
        catalog, "orchestrator-config", repo_root=tmp_path,
        scope="project", target_override=target,
    )
    assert result["drift"] is True
    assert result["status"] == "drift"


def test_generic_sync_reinstall_dispatches_runtime_config(catalog, tmp_path):
    """`library sync` reinstall path handles runtime-config lockfile entries."""
    from lib.sync_audit import reinstall_entry

    target = tmp_path / "deployed.yml"
    install_runtime_config(
        catalog, "orchestrator-config", repo_root=tmp_path,
        scope="project", target_override=target,
    )
    # The deployed default target (no override) — reinstall_entry uses the entry's
    # install_target from the lockfile via install_runtime_config's resolver, so we
    # deploy to the resolved default and confirm no exception + file present.
    entry = {"name": "orchestrator-config", "type": "runtime-config", "install_mode": "vendor"}
    reinstall_entry(catalog, entry, repo_root=tmp_path, scope="project", harness="all")
    resolved = tmp_path / ".agents" / "orchestrator-config.yml"
    assert resolved.is_file()
    assert "bead_claim" in resolved.read_text()


# --------------------------------------------------------------------------
# markdown format (verbatim passthrough) — AGENTS.md distribution (clc-e1t2)
# --------------------------------------------------------------------------

from lib.errors import InstallError  # noqa: E402

AGENTS_MD = """# Always-on Cross-Harness Agent Rules

- Rule one: worktrees below ~/code/.worktrees.
- Rule two: english-only source.

## A YAML-looking block that must survive verbatim

```yaml
model_tiers:
  known_models: [opus, sonnet]
```
"""


@pytest.fixture
def md_source(tmp_path):
    src = tmp_path / "AGENTS.md"
    src.write_text(AGENTS_MD, encoding="utf-8")
    return src


@pytest.fixture
def md_catalog(tmp_path, md_source):
    return {
        "default_dirs": {
            "runtime_configs": [
                {"default": ".agents/"},
                {"global": "~/.agents/"},
            ],
        },
        "library": {
            "runtime_configs": [
                {
                    "name": "agents-md",
                    "description": "Global cross-harness AGENTS.md.",
                    "base": str(md_source),
                    "format": "markdown",
                    "deploy_filename": "AGENTS.md",
                }
            ]
        },
    }


def test_markdown_deploys_verbatim(md_catalog, md_source, tmp_path):
    """AC1: format=markdown deploys the base source byte-identical (no YAML round-trip)."""
    target = tmp_path / "deployed-AGENTS.md"
    r = install_runtime_config(
        md_catalog, "agents-md", repo_root=tmp_path,
        scope="project", target_override=target,
    )
    assert r["status"] == "ok"
    assert target.read_text() == md_source.read_text()


def test_markdown_idempotent_resync(md_catalog, tmp_path):
    target = tmp_path / "deployed-AGENTS.md"
    r1 = install_runtime_config(
        md_catalog, "agents-md", repo_root=tmp_path,
        scope="project", target_override=target,
    )
    first = target.read_text()
    r2 = install_runtime_config(
        md_catalog, "agents-md", repo_root=tmp_path,
        scope="project", target_override=target,
    )
    assert target.read_text() == first
    assert r2["data"]["content_sha256"] == r1["data"]["content_sha256"]


def test_markdown_rejects_overlay(tmp_path, md_source):
    """A markdown entry with a global_overlay is rejected with a clear error."""
    catalog = {
        "default_dirs": {"runtime_configs": [{"default": ".agents/"}, {"global": "~/.agents/"}]},
        "library": {"runtime_configs": [{
            "name": "agents-md",
            "description": "invalid: markdown with overlay",
            "base": str(md_source),
            "format": "markdown",
            "global_overlay": str(md_source),
            "deploy_filename": "AGENTS.md",
        }]},
    }
    target = tmp_path / "deployed-AGENTS.md"
    with pytest.raises(InstallError, match="does not support"):
        install_runtime_config(
            catalog, "agents-md", repo_root=tmp_path,
            scope="project", target_override=target,
        )


def test_markdown_audit_clean_then_drift(md_catalog, tmp_path):
    target = tmp_path / "deployed-AGENTS.md"
    install_runtime_config(
        md_catalog, "agents-md", repo_root=tmp_path,
        scope="project", target_override=target,
    )
    clean = audit_runtime_config(
        md_catalog, "agents-md", repo_root=tmp_path,
        scope="project", target_override=target,
    )
    assert clean["status"] == "clean"
    assert clean["drift"] is False

    target.write_text(target.read_text() + "\n- rogue rule\n")
    drift = audit_runtime_config(
        md_catalog, "agents-md", repo_root=tmp_path,
        scope="project", target_override=target,
    )
    assert drift["drift"] is True
    assert drift["status"] == "drift"


def test_markdown_format_is_case_insensitive(tmp_path, md_source):
    """`format: MARKDOWN` is normalized and still deploys verbatim (no YAML parse)."""
    catalog = {
        "default_dirs": {"runtime_configs": [{"default": ".agents/"}, {"global": "~/.agents/"}]},
        "library": {"runtime_configs": [{
            "name": "agents-md",
            "description": "uppercase format",
            "base": str(md_source),
            "format": "MARKDOWN",
            "deploy_filename": "AGENTS.md",
        }]},
    }
    target = tmp_path / "deployed-AGENTS.md"
    r = install_runtime_config(
        catalog, "agents-md", repo_root=tmp_path,
        scope="project", target_override=target,
    )
    assert r["status"] == "ok"
    assert target.read_text() == md_source.read_text()


def test_unknown_format_is_rejected(tmp_path, md_source):
    """An unknown format value fails loudly instead of silently falling to YAML."""
    catalog = {
        "default_dirs": {"runtime_configs": [{"default": ".agents/"}, {"global": "~/.agents/"}]},
        "library": {"runtime_configs": [{
            "name": "agents-md",
            "description": "bogus format",
            "base": str(md_source),
            "format": "bogus",
            "deploy_filename": "AGENTS.md",
        }]},
    }
    target = tmp_path / "deployed-AGENTS.md"
    with pytest.raises(InstallError, match="unknown format"):
        install_runtime_config(
            catalog, "agents-md", repo_root=tmp_path,
            scope="project", target_override=target,
        )


def test_markdown_whitespace_overlay_treated_as_absent(tmp_path, md_source):
    """A whitespace-only global_overlay is treated as absent (not a rejected overlay)."""
    catalog = {
        "default_dirs": {"runtime_configs": [{"default": ".agents/"}, {"global": "~/.agents/"}]},
        "library": {"runtime_configs": [{
            "name": "agents-md",
            "description": "whitespace overlay",
            "base": str(md_source),
            "format": "markdown",
            "global_overlay": "   ",
            "deploy_filename": "AGENTS.md",
        }]},
    }
    target = tmp_path / "deployed-AGENTS.md"
    r = install_runtime_config(
        catalog, "agents-md", repo_root=tmp_path,
        scope="project", target_override=target,
    )
    assert r["status"] == "ok"
    assert target.read_text() == md_source.read_text()


# --------------------------------------------------------------------------
# deploy_dir override — CLAUDE.md distribution to ~/.claude/ (clc-cywc)
# --------------------------------------------------------------------------

def _claude_md_entry():
    return {
        "name": "claude-md-global",
        "description": "Global CLAUDE.md",
        "base": "unused-in-path-resolution",
        "format": "markdown",
        "deploy_filename": "CLAUDE.md",
        "deploy_dir": [{"default": ".claude/"}, {"global": "~/.claude/"}],
    }


def test_deploy_dir_override_global_targets_home_claude(tmp_path):
    """deploy_dir global mapping resolves to ~/.claude/, not the ~/.agents/ default."""
    entry = _claude_md_entry()
    catalog = {
        "default_dirs": {"runtime_configs": [{"default": ".agents/"}, {"global": "~/.agents/"}]},
        "library": {"runtime_configs": [entry]},
    }
    target = resolve_target_path(catalog, entry, scope="global", repo_root=tmp_path)
    assert target == Path.home() / ".claude" / "CLAUDE.md"


def test_deploy_dir_override_project_is_repo_relative(tmp_path):
    """deploy_dir default (project) mapping resolves relative to the repo root."""
    entry = _claude_md_entry()
    catalog = {
        "default_dirs": {"runtime_configs": [{"default": ".agents/"}, {"global": "~/.agents/"}]},
        "library": {"runtime_configs": [entry]},
    }
    target = resolve_target_path(catalog, entry, scope="project", repo_root=tmp_path)
    assert target == tmp_path / ".claude" / "CLAUDE.md"


def test_deploy_dir_missing_scope_raises(tmp_path):
    """A deploy_dir without the active scope's key fails loudly."""
    entry = {
        "name": "claude-md-global",
        "deploy_filename": "CLAUDE.md",
        "deploy_dir": [{"default": ".claude/"}],  # no 'global'
    }
    catalog = {"default_dirs": {"runtime_configs": []}, "library": {"runtime_configs": [entry]}}
    with pytest.raises(InstallError, match="no 'global'"):
        resolve_target_path(catalog, entry, scope="global", repo_root=tmp_path)


def test_no_deploy_dir_still_uses_default_dirs(tmp_path):
    """An entry without deploy_dir resolves via default_dirs.runtime_configs (unchanged)."""
    entry = {"name": "agents-md", "deploy_filename": "AGENTS.md"}
    catalog = {
        "default_dirs": {"runtime_configs": [{"default": ".agents/"}, {"global": "~/.agents/"}]},
        "library": {"runtime_configs": [entry]},
    }
    target = resolve_target_path(catalog, entry, scope="global", repo_root=tmp_path)
    assert target == Path.home() / ".agents" / "AGENTS.md"


def test_deploy_dir_end_to_end_install(tmp_path, md_source):
    """install via deploy_dir (no target_override) writes to the resolved dir verbatim.

    Uses project scope with an absolute deploy_dir so both the lockfile and the
    deploy target stay under tmp_path (hermetic — never touches real global state).
    """
    fake_claude = tmp_path / "fake" / ".claude"
    entry = {
        "name": "claude-md-global",
        "description": "Global CLAUDE.md",
        "base": str(md_source),
        "format": "markdown",
        "deploy_filename": "CLAUDE.md",
        "deploy_dir": [{"default": str(fake_claude)}],
    }
    catalog = {
        "default_dirs": {"runtime_configs": [{"default": ".agents/"}, {"global": "~/.agents/"}]},
        "library": {"runtime_configs": [entry]},
    }
    r = install_runtime_config(catalog, "claude-md-global", repo_root=tmp_path, scope="project")
    assert r["status"] == "ok"
    deployed = fake_claude / "CLAUDE.md"
    assert deployed.read_text() == md_source.read_text()
    audit = audit_runtime_config(catalog, "claude-md-global", repo_root=tmp_path, scope="project")
    assert audit["status"] == "clean"
