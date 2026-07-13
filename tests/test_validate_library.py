#!/usr/bin/env python3
"""
test_validate_library.py — Acceptance tests for validate-library.py (CL-49a)

Tests:
  M2: Schema accepts new optional fields: globs, always_apply, compatibility, metadata
  M3: Validator enforces agentskills.io name/description rules

Run with:
    python3 -m pytest tests/test_validate_library.py -v
"""

import json
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parent.parent
VALIDATE_PY = REPO_ROOT / "scripts" / "validate-library.py"
SCHEMA_PATH = REPO_ROOT / "docs" / "schema" / "library.schema.json"


def _run_validator(yaml_content: str, *extra_args: str) -> subprocess.CompletedProcess:
    """Write yaml_content to a temp file and run validate-library.py against it."""
    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".yaml", delete=False
    ) as f:
        f.write(yaml_content)
        tmp_path = f.name
    try:
        result = subprocess.run(
            [
                sys.executable,
                str(VALIDATE_PY),
                "--yaml",
                tmp_path,
                "--schema",
                str(SCHEMA_PATH),
                *extra_args,
            ],
            capture_output=True,
            text=True,
        )
    finally:
        Path(tmp_path).unlink(missing_ok=True)
    return result


def _make_library_yaml(skill_entry: dict) -> str:
    """Wrap a skill entry dict into a minimal valid library.yaml string."""
    data = {
        "default_dirs": {
            "skills": [{"claude": "~/.claude/skills"}],
        },
        "library": {
            "skills": [skill_entry],
        },
    }
    return yaml.dump(data, default_flow_style=False)


def _make_library_yaml_with_standard(standard_entry: dict) -> str:
    """Wrap a standard entry dict into a minimal valid library.yaml string."""
    data = {
        "default_dirs": {
            "skills": [{"claude": "~/.claude/skills"}],
        },
        "library": {
            "standards": [standard_entry],
        },
    }
    return yaml.dump(data, default_flow_style=False)


def _make_library_yaml_with_entries(entries_by_section: dict[str, list[dict]]) -> str:
    """Wrap primitive section entries into a minimal valid library.yaml string."""
    data = {
        "default_dirs": {
            "skills": [{"claude": "~/.claude/skills"}],
        },
        "library": entries_by_section,
    }
    return yaml.dump(data, default_flow_style=False)


def _make_library_yaml_with_agent(agent_entry: dict) -> str:
    """Wrap an agent entry dict into a minimal valid library.yaml string."""
    data = {
        "default_dirs": {
            "agents": [{"default": ".claude/agents/"}],
        },
        "library": {
            "agents": [agent_entry],
        },
    }
    return yaml.dump(data, default_flow_style=False)


def _base_skill_entry() -> dict:
    """Return a minimal valid skill entry."""
    return {
        "name": "my-skill",
        "description": "A valid skill.",
        "source": "https://github.com/example/repo/blob/main/skills/my-skill/SKILL.md",
    }


# ---------------------------------------------------------------------------
# M2: Schema accepts new optional fields
# ---------------------------------------------------------------------------


def test_m2_schema_accepts_new_fields():
    """Skill entry using all four new fields (globs, always_apply, compatibility, metadata)
    must validate successfully (exit 0)."""
    entry = _base_skill_entry()
    entry["globs"] = ["**/*.py", "**/*.ts"]
    entry["always_apply"] = True
    entry["compatibility"] = "claude_code>=4.0"
    entry["metadata"] = {"author": "test", "tier": "beta"}

    yaml_str = _make_library_yaml(entry)
    result = _run_validator(yaml_str)
    assert result.returncode == 0, (
        f"Expected exit 0 for skill entry with new fields, got {result.returncode}.\n"
        f"stdout: {result.stdout}\nstderr: {result.stderr}"
    )


def test_schema_declares_agent_handlers_field():
    """Agent entries expose handlers as an array of relative path strings."""
    schema = json.loads(SCHEMA_PATH.read_text())
    agent_props = schema["$defs"]["agent_entry"]["allOf"][2]["properties"]

    assert "handlers" in agent_props
    assert agent_props["handlers"]["type"] == "array"
    assert agent_props["handlers"]["items"]["type"] == "string"


def test_schema_accepts_agent_handlers_field():
    """Agent entries with declared private handlers validate successfully."""
    agent_entry = {
        "name": "handler-agent",
        "description": "Agent with private handler assets.",
        "source": "https://github.com/example/repo/blob/main/agents/handler-agent.md",
        "handlers": ["handlers/fixture-handler.sh"],
    }

    result = _run_validator(_make_library_yaml_with_agent(agent_entry))

    assert result.returncode == 0, (
        f"Expected exit 0 for agent entry with handlers, got {result.returncode}.\n"
        f"stdout: {result.stdout}\nstderr: {result.stderr}"
    )


# ---------------------------------------------------------------------------
# M3: Validator enforces agentskills.io name/description rules
# ---------------------------------------------------------------------------


def test_m3_name_invalid_consecutive_hyphens():
    """Skill with name 'bad--name' (consecutive hyphens) must fail (exit 1) and mention 'name'."""
    entry = _base_skill_entry()
    entry["name"] = "bad--name"

    yaml_str = _make_library_yaml(entry)
    result = _run_validator(yaml_str)
    assert result.returncode == 1, (
        f"Expected exit 1 for name with consecutive hyphens, got {result.returncode}.\n"
        f"stdout: {result.stdout}\nstderr: {result.stderr}"
    )
    output = result.stdout + result.stderr
    assert "name" in output.lower(), (
        f"Expected error output to mention 'name', got:\n{output}"
    )


def test_m3_name_too_long():
    """Skill with name exceeding 64 chars must fail (exit 1)."""
    entry = _base_skill_entry()
    entry["name"] = "a" * 65

    yaml_str = _make_library_yaml(entry)
    result = _run_validator(yaml_str)
    assert result.returncode == 1, (
        f"Expected exit 1 for name >64 chars, got {result.returncode}.\n"
        f"stdout: {result.stdout}\nstderr: {result.stderr}"
    )


def test_m3_name_with_invalid_chars():
    """Skill with name containing invalid chars ('bad name!') must fail (exit 1)."""
    entry = _base_skill_entry()
    entry["name"] = "bad name!"

    yaml_str = _make_library_yaml(entry)
    result = _run_validator(yaml_str)
    assert result.returncode == 1, (
        f"Expected exit 1 for name with invalid chars, got {result.returncode}.\n"
        f"stdout: {result.stdout}\nstderr: {result.stderr}"
    )


def test_m3_description_too_long():
    """Skill with description exceeding 1024 chars must fail (exit 1)."""
    entry = _base_skill_entry()
    entry["description"] = "x" * 1025

    yaml_str = _make_library_yaml(entry)
    result = _run_validator(yaml_str)
    assert result.returncode == 1, (
        f"Expected exit 1 for description >1024 chars, got {result.returncode}.\n"
        f"stdout: {result.stdout}\nstderr: {result.stderr}"
    )


def test_m3_valid_entry_passes():
    """Skill with valid name and description must pass (exit 0)."""
    entry = {
        "name": "my-skill",
        "description": "A valid skill.",
        "source": "https://github.com/example/repo/blob/main/skills/my-skill/SKILL.md",
    }

    yaml_str = _make_library_yaml(entry)
    result = _run_validator(yaml_str)
    assert result.returncode == 0, (
        f"Expected exit 0 for valid entry, got {result.returncode}.\n"
        f"stdout: {result.stdout}\nstderr: {result.stderr}"
    )


def test_m3_name_with_trailing_hyphen():
    """Skill with name 'bad-name-' (trailing hyphen) must fail (exit 1) and mention 'trailing hyphen'."""
    entry = _base_skill_entry()
    entry["name"] = "bad-name-"

    yaml_str = _make_library_yaml(entry)
    result = _run_validator(yaml_str)
    assert result.returncode == 1, (
        f"Expected exit 1 for name with trailing hyphen, got {result.returncode}.\n"
        f"stdout: {result.stdout}\nstderr: {result.stderr}"
    )
    output = result.stdout + result.stderr
    assert "trailing hyphen" in output.lower(), (
        f"Expected error output to mention 'trailing hyphen', got:\n{output}"
    )


def test_m2_standard_entry_with_globs_and_always_apply():
    """Standard entry with globs and always_apply fields must validate successfully (exit 0)."""
    entry = {
        "name": "my-standard",
        "description": "A valid standard.",
        "source": "https://github.com/example/repo/blob/main/standards/my-standard.md",
        "globs": ["*.md"],
        "always_apply": False,
    }

    yaml_str = _make_library_yaml_with_standard(entry)
    result = _run_validator(yaml_str)
    assert result.returncode == 0, (
        f"Expected exit 0 for standard entry with globs and always_apply, got {result.returncode}.\n"
        f"stdout: {result.stdout}\nstderr: {result.stderr}"
    )


def test_schema_accepts_harness_support_and_runtime_requirements():
    """Common entry metadata accepts harness and runtime requirement blocks."""
    entry = _base_skill_entry()
    entry["metadata"] = {
        "library": {
            "harness_support": {
                "claude_code": "supported",
                "codex": "not-supported",
            }
        }
    }
    entry["runtime_requirements"] = {
        "binaries": ["rg", "shellcheck"],
    }

    result = _run_validator(_make_library_yaml(entry))

    assert result.returncode == 0, (
        f"Expected exit 0 for harness/runtime metadata, got {result.returncode}.\n"
        f"stdout: {result.stdout}\nstderr: {result.stderr}"
    )


def test_schema_accepts_runtime_requirements_on_installable_primitive_shapes():
    """CL-iye.7 AK4: supported installable primitive shapes accept runtime requirements."""
    runtime_requirements = {"binaries": ["__nonexistent_binary_xyz__"]}
    data = {
        "default_dirs": {
            "skills": [{"claude": "~/.claude/skills"}],
        },
        "library": {
            "skills": [
                {
                    **_base_skill_entry(),
                    "runtime_requirements": runtime_requirements,
                }
            ],
            "agents": [
                {
                    "name": "runtime-agent",
                    "description": "Agent with runtime requirements.",
                    "source": "https://github.com/example/repo/blob/main/agents/runtime-agent.md",
                    "runtime_requirements": runtime_requirements,
                }
            ],
            "prompts": [
                {
                    "name": "runtime-prompt",
                    "description": "Prompt with runtime requirements.",
                    "source": "https://github.com/example/repo/blob/main/prompts/runtime-prompt.md",
                    "runtime_requirements": runtime_requirements,
                }
            ],
            "scripts": [
                {
                    "name": "runtime-script",
                    "description": "Script with runtime requirements.",
                    "source": "https://github.com/example/repo/blob/main/scripts/runtime-script.py",
                    "language": "python",
                    "runtime_requirements": runtime_requirements,
                }
            ],
            "standards": [
                {
                    "name": "runtime-standard",
                    "description": "Standard with runtime requirements.",
                    "source": "https://github.com/example/repo/blob/main/standards/runtime-standard.md",
                    "runtime_requirements": runtime_requirements,
                }
            ],
            "model_standards": [
                {
                    "name": "runtime-model-standard",
                    "description": "Model standard with runtime requirements.",
                    "source": "https://github.com/example/repo/blob/main/model-standards/runtime-model-standard.md",
                    "runtime_requirements": runtime_requirements,
                }
            ],
            "agent_bases": [
                {
                    "name": "runtime-agent-base",
                    "description": "Agent base with runtime requirements.",
                    "source": "https://github.com/example/repo/blob/main/agent-bases/runtime-agent-base.md",
                    "runtime_requirements": runtime_requirements,
                }
            ],
            "guardrails": [
                {
                    "name": "runtime-guardrail",
                    "description": "Guardrail with runtime requirements.",
                    "kind": "hooks-manifest",
                    "source": "https://github.com/example/repo/blob/main/hooks/runtime.json",
                    "runtime_requirements": runtime_requirements,
                }
            ],
            "mcp_servers": [
                {
                    "name": "runtime-mcp",
                    "description": "MCP server with runtime requirements.",
                    "runtime_requirements": runtime_requirements,
                }
            ],
        },
    }

    result = _run_validator(yaml.dump(data, default_flow_style=False))

    assert result.returncode == 0, result.stdout + result.stderr


def test_schema_accepts_closed_harness_support_registry():
    """Harness support accepts the closed set of known harness identifiers."""
    entry = _base_skill_entry()
    entry["metadata"] = {
        "library": {
            "harness_support": {
                "claude_code": "supported",
                "codex": "not-supported",
                "cursor": "planned",
                "opencode": "supported",
                "gemini": "planned",
            }
        }
    }

    result = _run_validator(_make_library_yaml(entry))

    assert result.returncode == 0, result.stdout + result.stderr


def test_schema_rejects_unknown_harness_support_id():
    """Harness support is a closed enum of known harness identifiers."""
    entry = _base_skill_entry()
    entry["metadata"] = {
        "library": {
            "harness_support": {
                "pi": "planned",
            }
        }
    }

    result = _run_validator(_make_library_yaml(entry))

    assert result.returncode == 1
    assert "pi" in result.stdout + result.stderr


def test_schema_rejects_invalid_harness_support_status():
    """Harness support values are limited to supported, not-supported, and planned."""
    entry = _base_skill_entry()
    entry["metadata"] = {
        "library": {
            "harness_support": {
                "cursor": "experimental",
            }
        }
    }

    result = _run_validator(_make_library_yaml(entry))

    assert result.returncode == 1
    assert "experimental" in result.stdout + result.stderr


def test_mcp_and_project_tooling_entries_exclude_harness_support_metadata():
    """MCP and tooling planes do not carry metadata.library.harness_support."""
    valid_mcp_entry = {
        "name": "plain-mcp",
        "description": "Plain MCP server.",
    }
    valid_tooling_entry = {
        "name": "plain-tooling",
        "description": "Plain tooling entry.",
        "target_kind": "file",
        "target_path": ".example/config",
        "source": "tooling/example",
    }
    mcp_entry = {
        "name": "example-mcp",
        "description": "Example MCP server.",
        "metadata": {
            "library": {
                "harness_support": {
                    "cursor": "planned",
                }
            }
        },
    }
    tooling_entry = {
        "name": "example-tooling",
        "description": "Example tooling entry.",
        "target_kind": "file",
        "target_path": ".example/config",
        "source": "tooling/example",
        "metadata": {
            "library": {
                "harness_support": {
                    "cursor": "planned",
                }
            }
        },
    }

    valid_mcp_result = _run_validator(
        _make_library_yaml_with_entries({"mcp_servers": [valid_mcp_entry]})
    )
    valid_tooling_result = _run_validator(
        yaml.dump(
            {
                "default_dirs": {
                    "skills": [{"claude": "~/.claude/skills"}],
                },
                "library": {},
                "project_tooling": [valid_tooling_entry],
            },
            default_flow_style=False,
        )
    )
    tooling_result = _run_validator(
        yaml.dump(
            {
                "default_dirs": {
                    "skills": [{"claude": "~/.claude/skills"}],
                },
                "library": {},
                "project_tooling": [tooling_entry],
            },
            default_flow_style=False,
        )
    )
    mcp_result = _run_validator(_make_library_yaml_with_entries({"mcp_servers": [mcp_entry]}))

    assert valid_mcp_result.returncode == 0, valid_mcp_result.stdout + valid_mcp_result.stderr
    assert valid_tooling_result.returncode == 0, (
        valid_tooling_result.stdout + valid_tooling_result.stderr
    )
    assert mcp_result.returncode == 1
    assert tooling_result.returncode == 1
    assert "metadata" in mcp_result.stdout + mcp_result.stderr
    assert "metadata" in tooling_result.stdout + tooling_result.stderr


def test_mcp_server_species_library_tool_surface():
    """library-tool-surface MCP entries accept the four coding harness registration keys."""
    entry = {
        "name": "cognovis-tools",
        "description": "First-party typed Library tool surface.",
        "source": "https://github.com/cognovis/library-core/blob/main/mcp-servers/cognovis-tools/pyproject.toml",
        "species": "library-tool-surface",
        "coding_strategy": "mcp",
        "capabilities": {
            "stateless": False,
            "streaming": True,
            "auth": "none",
        },
        "supervised_local_service": {
            "url": "http://127.0.0.1:8765/mcp",
            "health_url": "http://127.0.0.1:8765/health",
            "install": {"command": "uv", "args": ["run", "cognovis-tools-daemon", "install"]},
            "start": {"command": "uv", "args": ["run", "cognovis-tools-daemon", "start"]},
            "health_check": {"command": "uv", "args": ["run", "cognovis-tools-daemon", "status"]},
            "restart": {"command": "uv", "args": ["run", "cognovis-tools-daemon", "restart"]},
            "stop": {"command": "uv", "args": ["run", "cognovis-tools-daemon", "stop"]},
            "uninstall": {"command": "uv", "args": ["run", "cognovis-tools-daemon", "uninstall"]},
            "stdio_rollback": {
                "type": "stdio",
                "command": "uv",
                "args": ["run", "python", "-m", "server", "--transport", "stdio"],
            },
        },
        "install": {
            "mcp": {
                "claude_code": {
                    "config_path": "~/.claude.json",
                    "snippet": {"type": "http", "url": "http://127.0.0.1:8765/mcp"},
                },
                "codex": {
                    "config_path": "~/.codex/config.toml",
                    "snippet": {"url": "http://127.0.0.1:8765/mcp"},
                },
                "cursor": {
                    "config_path": "~/.cursor/mcp.json",
                    "snippet": {"type": "http", "url": "http://127.0.0.1:8765/mcp"},
                },
            }
        },
    }

    result = _run_validator(_make_library_yaml_with_entries({"mcp_servers": [entry]}))

    assert result.returncode == 0, result.stdout + result.stderr


def test_supervised_local_service_rejects_non_loopback_url():
    entry = {
        "name": "cognovis-tools",
        "description": "Invalid supervised service URL.",
        "supervised_local_service": {
            "url": "http://0.0.0.0:8765/mcp",
            "install": {"command": "uv", "args": ["install"]},
            "start": {"command": "uv", "args": ["start"]},
            "health_check": {"command": "uv", "args": ["status"]},
            "restart": {"command": "uv", "args": ["restart"]},
            "stop": {"command": "uv", "args": ["stop"]},
            "uninstall": {"command": "uv", "args": ["uninstall"]},
            "stdio_rollback": {
                "type": "stdio",
                "command": "uv",
                "args": ["run", "python", "-m", "server", "--transport", "stdio"],
            },
        },
    }

    result = _run_validator(_make_library_yaml_with_entries({"mcp_servers": [entry]}))

    assert result.returncode == 1


@pytest.mark.parametrize("tier_tag", ["tier:domain", "tier:project"])
def test_tier_domain_and_project_entries_require_library_plane(tier_tag: str):
    """Domain and project tier entries must declare metadata.library.plane."""
    entry = _base_skill_entry()
    entry["tags"] = [tier_tag]

    result = _run_validator(_make_library_yaml(entry))

    assert result.returncode == 1
    output = result.stdout + result.stderr
    assert "tier=domain|project entries must declare metadata.library.plane" in output


def test_tier_domain_entry_with_library_plane_passes():
    """Domain tier entries pass when metadata.library.plane is present."""
    entry = _base_skill_entry()
    entry["tags"] = ["tier:domain"]
    entry["metadata"] = {"library": {"plane": "dev"}}

    result = _run_validator(_make_library_yaml(entry))

    assert result.returncode == 0, result.stdout + result.stderr


def test_legacy_primitive_alias_warning_when_canonical_present():
    """Dual canonical+legacy primitive sections warn that legacy entries are ignored."""
    data = {
        "default_dirs": {
            "skills": [{"claude": "~/.claude/skills"}],
        },
        "library": {
            "guardrails": [],
        },
        "guardrails": [
            {
                "name": "legacy-guardrail",
                "description": "A legacy guardrail.",
                "purpose": "pre-tool-veto",
            }
        ],
    }

    result = _run_validator(yaml.dump(data, default_flow_style=False))

    assert result.returncode == 0, result.stdout + result.stderr
    output = result.stdout + result.stderr
    assert "WARN:" in output
    assert "guardrails" in output
    assert "canonical 'library.guardrails' is present" in output
    assert "canonical wins and legacy entries are ignored" in output


def test_legacy_source_alias_warning_when_canonical_present():
    """Dual canonical+legacy source registries warn that root aliases are ignored."""
    data = {
        "default_dirs": {
            "skills": [{"claude": "~/.claude/skills"}],
        },
        "library": {},
        "sources": {
            "catalogs": [],
            "marketplaces": [],
        },
        "catalog": [
            {
                "name": "legacy-catalog",
                "source": "https://github.com/example/catalog",
                "description": "A legacy catalog.",
            }
        ],
        "marketplaces": [
            {
                "name": "legacy-marketplace",
                "source": "https://github.com/example",
                "description": "A legacy marketplace.",
                "type": "git",
            }
        ],
    }

    result = _run_validator(yaml.dump(data, default_flow_style=False))

    assert result.returncode == 0, result.stdout + result.stderr
    output = result.stdout + result.stderr
    assert "WARN:" in output
    assert "catalog" in output
    assert "marketplaces" in output
    assert "canonical 'sources.catalogs' is present" in output
    assert "canonical 'sources.marketplaces' is present" in output
    assert "canonical wins and legacy entries are ignored" in output


def test_legacy_only_alias_warning_mentions_compatibility_fallback():
    """Legacy-only aliases pass in normal mode and explain the compatibility fallback."""
    data = {
        "default_dirs": {
            "skills": [{"claude": "~/.claude/skills"}],
        },
        "library": {},
        "guardrails": [
            {
                "name": "legacy-guardrail",
                "description": "A legacy guardrail.",
                "purpose": "pre-tool-veto",
            }
        ],
    }

    result = _run_validator(yaml.dump(data, default_flow_style=False))

    assert result.returncode == 0, result.stdout + result.stderr
    output = result.stdout + result.stderr
    assert "WARN:" in output
    assert "Deprecated root key 'guardrails' is accepted for compatibility" in output
    assert "use 'library.guardrails' instead" in output


def test_strict_aliases_rejects_legacy_aliases_even_without_canonical():
    """--strict-aliases fails any deprecated root alias during alias sunset."""
    data = {
        "default_dirs": {
            "skills": [{"claude": "~/.claude/skills"}],
        },
        "library": {},
        "guardrails": [
            {
                "name": "legacy-guardrail",
                "description": "A legacy guardrail.",
                "purpose": "pre-tool-veto",
            }
        ],
        "catalog": [
            {
                "name": "legacy-catalog",
                "source": "https://github.com/example/catalog",
                "description": "A legacy catalog.",
            }
        ],
    }

    result = _run_validator(
        yaml.dump(data, default_flow_style=False),
        "--strict-aliases",
    )

    assert result.returncode == 1
    output = result.stdout + result.stderr
    assert "legacy alias error" in output
    assert "--strict-aliases" in output
    assert "library.guardrails" in output
    assert "sources.catalogs" in output


def test_strict_aliases_reports_semantic_errors_in_same_run():
    """Strict alias failures should not hide independent semantic errors."""
    data = {
        "default_dirs": {
            "skills": [{"claude": "~/.claude/skills"}],
        },
        "library": {
            "skills": [
                {
                    "name": "missing-source",
                    "description": "A skill missing a resolvable source.",
                }
            ],
        },
        "guardrails": [
            {
                "name": "legacy-guardrail",
                "description": "A legacy guardrail.",
                "purpose": "pre-tool-veto",
            }
        ],
    }

    result = _run_validator(
        yaml.dump(data, default_flow_style=False),
        "--strict-aliases",
    )

    assert result.returncode == 1
    output = result.stdout + result.stderr
    assert "legacy alias error" in output
    assert "semantic error" in output
    assert "library.guardrails" in output
    assert "Entry has no resolvable source" in output
