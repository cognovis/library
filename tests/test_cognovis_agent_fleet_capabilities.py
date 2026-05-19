#!/usr/bin/env python3
"""Fleet checks for cognovis-core capability-based agent sources."""

from __future__ import annotations

import re
import subprocess
import sys
import tomllib
from pathlib import Path
from typing import Any

import pytest
import yaml


REPO_ROOT = Path(__file__).resolve().parent.parent
COGNOVIS_CORE = REPO_ROOT.parent / "cognovis-core"
AGENTS_DIR = COGNOVIS_CORE / "agents"
AGENT_BASES_DIR = COGNOVIS_CORE / "agent-bases"
MODEL_STANDARDS_DIR = COGNOVIS_CORE / "model-standards"
BUILD_AGENT = REPO_ROOT / "scripts" / "build-agent.py"
LIBRARY_YAML = REPO_ROOT / "library.yaml"

# Minimum length for developer_instructions in a real Codex artifact.
# The smallest catalog agent (ci-monitor) produces ~3 000 chars; a prompt_file
# stub produces 0 chars. 200 is well below any real value and well above any stub.
_MIN_DEV_INSTRUCTIONS_CHARS = 200

# Minimum body length (chars after frontmatter) for a real Claude .md artifact.
# ci-monitor produces ~5 000 chars; 200 guards against empty-body stubs.
_MIN_CLAUDE_BODY_CHARS = 200


# ---------------------------------------------------------------------------
# Quality-check helpers (used both by the fleet test and the regression fixture)
# ---------------------------------------------------------------------------


def _assert_codex_artifact_quality(name: str, parsed: dict[str, Any], toml_text: str) -> None:
    """Raise AssertionError if the Codex .toml artifact looks like a stub."""
    assert parsed.get("prompt_file") is None, (
        f"{name}: Codex artifact has top-level 'prompt_file' key — stub indirection pattern"
    )
    dev_inst = parsed.get("developer_instructions", "")
    assert len(dev_inst) >= _MIN_DEV_INSTRUCTIONS_CHARS, (
        f"{name}: developer_instructions is only {len(dev_inst)} chars "
        f"(threshold: {_MIN_DEV_INSTRUCTIONS_CHARS}) — looks like a stub"
    )
    assert parsed.get("name"), f"{name}: Codex artifact missing 'name' field"


def _assert_claude_artifact_quality(name: str, md_text: str) -> None:
    """Raise AssertionError if the Claude .md artifact looks like a stub."""
    assert md_text.startswith("---\n"), f"{name}: Claude artifact missing frontmatter delimiter"
    parts = md_text.split("---", 2)
    body = parts[2] if len(parts) >= 3 else ""
    assert len(body) >= _MIN_CLAUDE_BODY_CHARS, (
        f"{name}: Claude artifact body is only {len(body)} chars "
        f"(threshold: {_MIN_CLAUDE_BODY_CHARS}) — looks like a stub"
    )


# ---------------------------------------------------------------------------
# Resolver helper (used by fleet checks and resolver unit tests)
# ---------------------------------------------------------------------------


def _resolve_requires_refs(
    refs: list[str], registry: dict[str, Any]
) -> list[tuple[str, str, bool]]:
    """Parse and resolve a list of 'primitive:name' require refs.

    Returns a list of (ref, name, resolved) tuples where *resolved* is True if
    *name* exists in *registry*.

    Raises ValueError for refs that are missing the colon separator or have an
    empty name after the prefix (prefix-without-subagent).
    """
    results: list[tuple[str, str, bool]] = []
    for ref in refs:
        if ":" not in ref:
            raise ValueError(f"Malformed ref (no colon separator): {ref!r}")
        _, name = ref.split(":", 1)
        name = name.strip()
        if not name:
            raise ValueError(
                f"Malformed ref (empty name after prefix): {ref!r}"
            )
        results.append((ref, name, name in registry))
    return results


# ---------------------------------------------------------------------------
# Body-ref helpers: plugin-prefixed subagent_type refs in agent body prose
# ---------------------------------------------------------------------------

# Prose placeholders like subagent_type="..." appear in documentation text and
# are not real runtime refs.
_BODY_REF_PLACEHOLDER_RE = re.compile(r'^\.+$')

_BODY_SUBAGENT_TYPE_RE = re.compile(r'subagent_type=["\']([^"\']+)["\']')


def _extract_body_subagent_type_refs(text: str) -> list[str]:
    """Return all subagent_type="..." values found in *text*, excluding prose placeholders.

    Skips values that look like documentation placeholders (e.g. ``"..."``).
    """
    return [
        m
        for m in _BODY_SUBAGENT_TYPE_RE.findall(text)
        if not _BODY_REF_PLACEHOLDER_RE.match(m)
    ]


def _resolve_plugin_prefixed_body_refs(
    refs: list[str],
    plugin_registry: dict[str, set[str]],
) -> list[tuple[str, str, str, bool]]:
    """Resolve plugin-prefixed subagent_type refs against a registry.

    Plugin-prefixed means the value contains a colon, e.g. ``codex:codex-rescue``.
    Plain refs (no colon) are skipped and not included in the returned list.

    *plugin_registry* maps namespace strings (e.g. ``"codex"``) to sets of known
    agent names within that namespace.

    Returns a list of ``(ref, namespace, name, resolved)`` tuples — one entry per
    plugin-prefixed ref.

    Raises ValueError for malformed prefixed refs (empty namespace or empty name
    after the colon).
    """
    results: list[tuple[str, str, str, bool]] = []
    for ref in refs:
        if ":" not in ref:
            continue  # plain ref — not in scope
        namespace, _, name = ref.partition(":")
        namespace = namespace.strip()
        name = name.strip()
        if not namespace:
            raise ValueError(f"Malformed plugin ref (empty namespace): {ref!r}")
        if not name:
            raise ValueError(f"Malformed plugin ref (empty name after prefix): {ref!r}")
        resolved = name in plugin_registry.get(namespace, set())
        results.append((ref, namespace, name, resolved))
    return results


pytestmark = pytest.mark.skipif(
    not AGENTS_DIR.exists(),
    reason="cognovis-core sibling checkout is not available",
)


def _frontmatter(path: Path) -> dict:
    text = path.read_text()
    assert text.startswith("---\n"), f"{path.name} has no frontmatter"
    return yaml.safe_load(text.split("---", 2)[1]) or {}


def test_cognovis_agents_are_capability_first() -> None:
    """Every first-party agent uses capability declarations after CL-2yp."""
    for path in sorted(AGENTS_DIR.glob("*.md")):
        frontmatter = _frontmatter(path)
        assert frontmatter.get("agent_base") == "auto", f"{path.name} missing agent_base: auto"
        assert "agent_base_extends" not in frontmatter, f"{path.name} still uses agent_base_extends"
        assert "capabilities" in frontmatter, f"{path.name} missing capabilities"
        assert isinstance(frontmatter.get("model"), dict), f"{path.name} model is not a mapping"
        assert "tools" not in frontmatter, f"{path.name} still has tools"
        assert "model_standards" not in frontmatter, f"{path.name} still has model_standards"


def test_cognovis_agents_have_no_stale_codex_subagent_claims() -> None:
    """Migrated Codex prose no longer says subagents are unavailable."""
    stale_patterns = [
        "no subagent spawning is available in Codex",
        "no subagent spawning",
    ]
    for path in sorted(AGENTS_DIR.glob("*.md")):
        text = path.read_text()
        for pattern in stale_patterns:
            assert pattern not in text, f"{path.name} contains stale Codex claim: {pattern}"


def test_researcher_preserves_searxng_only_tool_contract() -> None:
    """The researcher agent does not receive generic built-in web-search tools."""
    frontmatter = _frontmatter(AGENTS_DIR / "researcher.md")
    assert "search_searxng" in frontmatter["capabilities"]
    assert "search_web" not in frontmatter["capabilities"]


def test_cognovis_agents_build_for_claude_and_codex(tmp_path: Path) -> None:
    """All migrated agents build through the unified agent builder."""
    for source in sorted(AGENTS_DIR.glob("*.md")):
        output_dir = tmp_path / source.stem
        result = subprocess.run(
            [
                sys.executable,
                str(BUILD_AGENT),
                str(source),
                "--harness",
                "all",
                "--output-dir",
                str(output_dir),
                "--agent-bases-dir",
                str(AGENT_BASES_DIR),
                "--model-standards-dir",
                str(MODEL_STANDARDS_DIR),
            ],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0, f"{source.name} failed:\n{result.stderr}"
        assert list(output_dir.glob("*.md")), f"{source.name} emitted no Claude artifact"
        assert list(output_dir.glob("*.toml")), f"{source.name} emitted no Codex artifact"


def test_researcher_build_keeps_claude_builtin_web_tools_blocked(tmp_path: Path) -> None:
    """The generated Claude researcher grants SearXNG, not WebSearch/WebFetch."""
    output_dir = tmp_path / "researcher"
    result = subprocess.run(
        [
            sys.executable,
            str(BUILD_AGENT),
            str(AGENTS_DIR / "researcher.md"),
            "--harness",
            "claude",
            "--output-dir",
            str(output_dir),
            "--agent-bases-dir",
            str(AGENT_BASES_DIR),
            "--model-standards-dir",
            str(MODEL_STANDARDS_DIR),
        ],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr
    artifact = next(output_dir.glob("*.md"))
    built_frontmatter = yaml.safe_load(artifact.read_text().split("---", 2)[1]) or {}
    tools = built_frontmatter.get("tools", "")
    assert "mcp__searxng__searxng_web_search" in tools
    assert "WebSearch" not in tools
    assert "WebFetch" not in tools


def test_catalog_agents_build_with_non_stub_artifacts(tmp_path: Path) -> None:
    """Every catalog-listed agent builds and produces non-stub, schema-valid artifacts."""
    catalog = yaml.safe_load(LIBRARY_YAML.read_text(encoding="utf-8")) or {}
    agents = catalog.get("library", {}).get("agents", [])
    assert agents, "library.yaml must declare at least one agent under library.agents"

    for entry in agents:
        name = entry["name"]
        source = AGENTS_DIR / f"{name}.md"

        assert source.exists(), (
            f"Catalog agent '{name}' has no source file at {source}"
        )

        # Read the declared name from the source frontmatter (may differ from catalog key).
        source_text = source.read_text(encoding="utf-8")
        source_frontmatter = yaml.safe_load(source_text.split("---", 2)[1]) or {}
        declared_name = source_frontmatter.get("name", name)

        output_dir = tmp_path / name
        result = subprocess.run(
            [
                sys.executable,
                str(BUILD_AGENT),
                str(source),
                "--harness",
                "all",
                "--output-dir",
                str(output_dir),
                "--agent-bases-dir",
                str(AGENT_BASES_DIR),
                "--model-standards-dir",
                str(MODEL_STANDARDS_DIR),
            ],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0, f"{name}: builder exited non-zero:\n{result.stderr}"

        # Claude .md artifact checks
        md_files = list(output_dir.glob("*.md"))
        assert md_files, f"{name}: builder emitted no Claude .md artifact"
        md_text = md_files[0].read_text(encoding="utf-8")
        _assert_claude_artifact_quality(name, md_text)
        built_frontmatter = yaml.safe_load(md_text.split("---", 2)[1]) or {}
        assert built_frontmatter.get("name") == declared_name, (
            f"{name}: Claude artifact frontmatter 'name' field is "
            f"{built_frontmatter.get('name')!r}, expected {declared_name!r}"
        )

        # Codex .toml artifact checks
        toml_files = list(output_dir.glob("*.toml"))
        assert toml_files, f"{name}: builder emitted no Codex .toml artifact"
        toml_text = toml_files[0].read_text(encoding="utf-8")
        parsed_toml = tomllib.loads(toml_text)
        _assert_codex_artifact_quality(name, parsed_toml, toml_text)
        assert parsed_toml.get("name") == declared_name, (
            f"{name}: Codex artifact TOML 'name' field is "
            f"{parsed_toml.get('name')!r}, expected {declared_name!r}"
        )


def test_builder_rejects_source_missing_frontmatter(tmp_path: Path) -> None:
    """Builder must fail loudly on a source file with no YAML frontmatter."""
    broken = tmp_path / "broken-agent.md"
    broken.write_text("Just prose, no YAML frontmatter delimiter.\nSecond line.\n")
    output_dir = tmp_path / "out"
    result = subprocess.run(
        [
            sys.executable,
            str(BUILD_AGENT),
            str(broken),
            "--harness",
            "all",
            "--output-dir",
            str(output_dir),
            "--agent-bases-dir",
            str(AGENT_BASES_DIR),
            "--model-standards-dir",
            str(MODEL_STANDARDS_DIR),
        ],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
    )
    assert result.returncode != 0, (
        "Builder should reject a source with no frontmatter, but exited 0"
    )
    assert result.stderr, "Builder should emit a diagnostic on stderr when rejecting bad input"


def test_quality_checks_reject_prompt_file_stub() -> None:
    """Regression fixture: quality helpers reject the original quick-fix.toml stub pattern.

    The original stub was 34 lines with a top-level prompt_file key and no
    developer_instructions. This test confirms the helpers used by
    test_catalog_agents_build_with_non_stub_artifacts would have caught it.
    """
    stub_toml = (
        'name = "quick-fix"\n'
        'description = "Lightweight quick fix orchestrator."\n'
        'model = "gpt-5.4"\n'
        'prompt_file = "agents/quick-fix.md"\n'
    )
    parsed = tomllib.loads(stub_toml)
    # prompt_file stub: helper must raise on the prompt_file key
    with pytest.raises(AssertionError, match="prompt_file"):
        _assert_codex_artifact_quality("quick-fix", parsed, stub_toml)


def test_quality_checks_reject_empty_developer_instructions() -> None:
    """Quality helper rejects a .toml with absent or trivially short developer_instructions."""
    # No developer_instructions at all
    stub_toml = 'name = "thin-agent"\ndescription = "stub"\nmodel = "gpt-5.4"\n'
    with pytest.raises(AssertionError, match="developer_instructions"):
        _assert_codex_artifact_quality("thin-agent", tomllib.loads(stub_toml), stub_toml)

    # Trivially short developer_instructions
    short_toml = (
        'name = "thin-agent"\n'
        'description = "stub"\n'
        'model = "gpt-5.4"\n'
        f'developer_instructions = "{"x" * 10}"\n'
    )
    with pytest.raises(AssertionError, match="developer_instructions"):
        _assert_codex_artifact_quality("thin-agent", tomllib.loads(short_toml), short_toml)


# ---------------------------------------------------------------------------
# Resolver unit tests
# ---------------------------------------------------------------------------


def test_resolver_resolves_known_agent_refs() -> None:
    """Resolver returns resolved=True for refs that exist in the registry."""
    registry = {"review-agent": {}, "session-close": {}}
    results = _resolve_requires_refs(["agent:review-agent", "agent:session-close"], registry)
    assert results == [
        ("agent:review-agent", "review-agent", True),
        ("agent:session-close", "session-close", True),
    ]


def test_resolver_reports_unresolved_refs() -> None:
    """Resolver returns resolved=False for refs not present in the registry."""
    results = _resolve_requires_refs(["agent:nonexistent"], {})
    assert results == [("agent:nonexistent", "nonexistent", False)]


def test_resolver_rejects_prefix_without_subagent() -> None:
    """Resolver raises ValueError for a ref with an empty name after the colon."""
    with pytest.raises(ValueError, match="empty name after prefix"):
        _resolve_requires_refs(["agent:"], {})

    with pytest.raises(ValueError, match="empty name after prefix"):
        _resolve_requires_refs(["agent:   "], {})  # whitespace-only name


def test_resolver_rejects_ref_without_colon() -> None:
    """Resolver raises ValueError for a ref that has no colon separator."""
    with pytest.raises(ValueError, match="no colon separator"):
        _resolve_requires_refs(["agent"], {})


def test_catalog_agent_requires_refs_resolve() -> None:
    """Every requires: agent:* ref in cognovis-core agent sources resolves to a catalog entry."""
    catalog = yaml.safe_load(LIBRARY_YAML.read_text(encoding="utf-8")) or {}
    catalog_agents = {a["name"]: a for a in catalog.get("library", {}).get("agents", [])}

    for agent_file in sorted(AGENTS_DIR.glob("*.md")):
        fm = _frontmatter(agent_file)
        agent_refs = [
            r for r in fm.get("requires", [])
            if isinstance(r, str) and r.startswith("agent:")
        ]
        if not agent_refs:
            continue
        results = _resolve_requires_refs(agent_refs, catalog_agents)
        for ref, name, resolved in results:
            assert resolved, (
                f"{agent_file.name}: requires: {ref!r} — "
                f"'{name}' is not listed in the library.yaml catalog"
            )


# ---------------------------------------------------------------------------
# Plugin-prefixed body ref unit tests
# ---------------------------------------------------------------------------


def test_body_ref_extractor_finds_plugin_prefixed_refs() -> None:
    """Extractor returns plugin-prefixed refs and skips prose placeholders."""
    text = (
        'Agent(subagent_type="codex:codex-rescue", prompt="...")\n'
        'Agent(subagent_type="general-purpose", prompt="do the thing")\n'
        '- **Claude**: Uses `Agent(subagent_type="...", prompt="...")` for docs.\n'
    )
    refs = _extract_body_subagent_type_refs(text)
    assert "codex:codex-rescue" in refs
    assert "general-purpose" in refs
    assert "..." not in refs


def test_plugin_ref_resolver_resolves_known_ref() -> None:
    """Resolver returns resolved=True when the agent name is in the namespace registry."""
    registry = {"codex": {"codex-rescue", "other-agent"}}
    results = _resolve_plugin_prefixed_body_refs(["codex:codex-rescue"], registry)
    assert results == [("codex:codex-rescue", "codex", "codex-rescue", True)]


def test_plugin_ref_resolver_reports_unresolved_ref() -> None:
    """Resolver returns resolved=False for a name absent from the registry."""
    results = _resolve_plugin_prefixed_body_refs(["codex:missing-agent"], {"codex": set()})
    assert results == [("codex:missing-agent", "codex", "missing-agent", False)]


def test_plugin_ref_resolver_skips_plain_refs() -> None:
    """Resolver ignores non-prefixed refs — they are not plugin-prefixed body refs."""
    results = _resolve_plugin_prefixed_body_refs(["general-purpose", "review-agent"], {})
    assert results == []


def test_plugin_ref_resolver_rejects_empty_name_after_prefix() -> None:
    """Resolver raises ValueError for a ref with an empty name after the namespace colon."""
    with pytest.raises(ValueError, match="empty name after prefix"):
        _resolve_plugin_prefixed_body_refs(["codex:"], {})

    with pytest.raises(ValueError, match="empty name after prefix"):
        _resolve_plugin_prefixed_body_refs(["codex:   "], {})


def _composed_layer_sources() -> list[Path]:
    """Return every .md file that the builder composes into the final artifact.

    Covers all three layers that the builder reads:
      - cognovis-core/agents/*.md         (agent source bodies)
      - cognovis-core/agent-bases/*.md    (Claude/Codex agent-base layers)
      - cognovis-core/model-standards/*.md (model-standard prose layers)

    A subagent_type ref appearing in any of these ends up in the composed
    .toml's developer_instructions string at runtime.
    """
    sources: list[Path] = []
    for layer_dir in (AGENTS_DIR, AGENT_BASES_DIR, MODEL_STANDARDS_DIR):
        if layer_dir.exists():
            sources.extend(sorted(layer_dir.glob("*.md")))
    return sources


def test_body_ref_extractor_catches_malformed_ref_in_any_layer(tmp_path: Path) -> None:
    """Regression: a malformed subagent_type ref in any composed layer is caught.

    Closes finding B from third-pass review (.md only, kein .toml): the fleet
    well-formedness check must scan every layer the builder composes, not just
    the agent source bodies. This fixture writes a synthetic agent-base file
    containing a malformed plugin-prefixed ref and confirms the extractor +
    resolver pair would flag it via ValueError.
    """
    malformed_layer = tmp_path / "broken-base.md"
    malformed_layer.write_text(
        'Some base prose.\n'
        '\n'
        '    Agent(subagent_type="codex:", prompt="oops empty name")\n'
    )
    refs = _extract_body_subagent_type_refs(malformed_layer.read_text())
    assert "codex:" in refs, "Extractor must surface the malformed ref for downstream validation"
    with pytest.raises(ValueError, match="empty name after prefix"):
        _resolve_plugin_prefixed_body_refs(refs, {})


def test_catalog_agent_body_plugin_refs_are_well_formed() -> None:
    """All plugin-prefixed subagent_type refs across composed layers are syntactically valid.

    This is the always-run tier: it only checks well-formedness (non-empty namespace
    and name). Resolution against an installed registry is handled by the optional
    integration-tier test below.

    Scans every layer that contributes to the composed Codex .toml output
    (agents, agent-bases, model-standards) — not just the agent source bodies —
    so that a subagent_type ref injected via a base or standard layer cannot
    silently bypass well-formedness checks.
    """
    for layer_file in _composed_layer_sources():
        refs = _extract_body_subagent_type_refs(layer_file.read_text())
        try:
            _resolve_plugin_prefixed_body_refs(refs, {})
        except ValueError as exc:
            raise AssertionError(
                f"{layer_file.relative_to(COGNOVIS_CORE)}: {exc}"
            ) from exc


_INSTALLED_CODEX_AGENTS = Path.home() / ".codex" / "agents"

# Codex-native runtime agents that are NOT managed by the library installer.
# These either ship with the Codex CLI itself or live in a marketplace plugin
# cache (e.g. ~/.claude/plugins/marketplaces/openai-codex/plugins/codex/agents/)
# rather than at ~/.codex/agents/<name>.toml. The integration test below only
# scans the top-level ~/.codex/agents/ directory by design — extending it to
# walk marketplace caches would add registry-builder complexity for little gain.
# When a new codex:* body ref is added that lives in a marketplace cache (not
# installed via `library use sync-codex-agents`), append the name here.
# Documented as intentional in docs/audit/library-go-live-2026-05-15.md.
_CODEX_RUNTIME_BUILTINS: frozenset[str] = frozenset({
    "codex-rescue",  # canonical Codex escape-hatch agent; invoked via codex: prefix
})


@pytest.mark.skipif(
    not _INSTALLED_CODEX_AGENTS.exists()
    or not list(_INSTALLED_CODEX_AGENTS.glob("*.toml")),
    reason="no installed Codex agents found at ~/.codex/agents/ — integration tier skipped",
)
def test_installed_codex_plugin_refs_resolve_against_local_agents() -> None:
    """Integration tier: non-builtin codex:* body refs resolve to ~/.codex/agents/<name>.toml.

    Skipped when no Codex agents are installed locally. Agents in
    _CODEX_RUNTIME_BUILTINS are Codex-native (or marketplace-cache-only) and
    are not checked for installation in the top-level ~/.codex/agents/ directory.
    """
    installed_names = {p.stem for p in _INSTALLED_CODEX_AGENTS.glob("*.toml")}
    plugin_registry = {"codex": installed_names}

    for layer_file in _composed_layer_sources():
        refs = _extract_body_subagent_type_refs(layer_file.read_text())
        results = _resolve_plugin_prefixed_body_refs(refs, plugin_registry)
        for ref, namespace, name, resolved in results:
            if namespace == "codex" and name not in _CODEX_RUNTIME_BUILTINS:
                rel = layer_file.relative_to(COGNOVIS_CORE)
                assert resolved, (
                    f"{rel}: body ref {ref!r} not found at "
                    f"~/.codex/agents/{name}.toml. Resolution paths:\n"
                    f"  (a) install via `library use {name}` (top-level scope), or\n"
                    f"  (b) add {name!r} to _CODEX_RUNTIME_BUILTINS if it lives in a "
                    f"marketplace plugin cache (e.g. "
                    f"~/.claude/plugins/marketplaces/openai-codex/plugins/codex/agents/) "
                    f"or is a Codex CLI built-in."
                )
