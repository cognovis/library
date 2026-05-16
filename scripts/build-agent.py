#!/usr/bin/env python3
"""
build-agent.py - Build harness-native agent artifacts from one Markdown source.

The unified source format is a Markdown file with YAML frontmatter. Shared
frontmatter lives at the top level; per-harness overrides live under keys such
as `claude:` and `codex:`. Body sections may use directive blocks:

    ::: harness claude :::
    Claude-only prose.
    ::: end :::

Everything outside directive blocks is shared. Malformed or nested directive
blocks fail the build.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import os
import re
import sys
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any

try:
    import yaml
except ImportError:
    print("ERROR: PyYAML is required. Run: pip install PyYAML", file=sys.stderr)
    sys.exit(2)


SCRIPT_DIR = Path(__file__).resolve().parent
REPO_ROOT = SCRIPT_DIR.parent
COMPOSE_SCRIPT = SCRIPT_DIR / "compose-agent.py"
DEFAULT_MODELS_REGISTRY = REPO_ROOT / "models.yaml"
DEFAULT_CAPABILITIES_REGISTRY = REPO_ROOT / "capabilities.yaml"
SUPPORTED_HARNESSES = {"claude", "codex", "opencode"}
COMPOSER_ONLY_KEYS = {
    "agent_base",
    "agent_base_extends",
    "golden_prompt_extends",
    "model_standards",
    "requires",
    "capabilities",
}
HARNESS_OVERRIDE_KEYS = {"claude", "codex", "opencode"}
MODEL_HARNESS_KEYS = {"claude", "claude-code", "codex", "opencode"}
HARNESS_REGISTRY_KEYS = {
    "claude": "claude-code",
    "codex": "codex",
    "opencode": "opencode",
}
CODEX_TOML_FIELDS = {
    "name",
    "description",
    "model",
    "model_reasoning_effort",
    "sandbox_mode",
    "approval_policy",
    "nickname_candidates",
}
CODEX_MODEL_MAP = {
    "haiku": "gpt-5.4",
    "sonnet": "gpt-5.4",
    "opus": "gpt-5.5",
    "inherit": "gpt-5.4",
}
CODEX_REASONING_BY_MODEL = {
    "haiku": "medium",
    "sonnet": "high",
    "opus": "high",
    "inherit": "medium",
}
TIER_RANK = {"economy": 0, "standard": 1, "premium": 2, "frontier": 3}
CONTEXT_RANK = {"small": 0, "medium": 1, "large": 2}
REASONING_RANK = {"low": 0, "medium": 1, "high": 2, "max": 3}
CODEX_REASONING_VALUE = {"low": "low", "medium": "medium", "high": "high", "max": "xhigh"}
SANDBOX_RANK = {"read-only": 0, "workspace-write": 1, "danger-full-access": 2}


class BuildAgentError(Exception):
    """Raised when a unified agent source cannot be built."""


def _registry_harness(harness: str) -> str:
    """Return the registry key used for a build harness."""
    return HARNESS_REGISTRY_KEYS.get(harness, harness)


def _load_yaml_mapping(path: Path) -> dict[str, Any]:
    """Load a YAML mapping from disk."""
    if not path.exists():
        raise BuildAgentError(f"Registry file not found: {path}")
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if not isinstance(data, dict):
        raise BuildAgentError(f"Registry file must contain a mapping: {path}")
    return data


def _resolve_registry_path(
    explicit_path: str | Path | None,
    env_var: str,
    default_path: Path,
) -> Path:
    """Resolve a registry path from an explicit value, env var, or repo default."""
    if explicit_path:
        return Path(explicit_path).expanduser()
    env_value = os.environ.get(env_var)
    if env_value:
        return Path(env_value).expanduser()
    return default_path


def load_models_registry(path: str | Path | None = None) -> list[dict[str, Any]]:
    """Load and lightly validate the model registry."""
    registry_path = _resolve_registry_path(path, "AGENT_MODELS_REGISTRY", DEFAULT_MODELS_REGISTRY)
    data = _load_yaml_mapping(registry_path)
    models = data.get("models", [])
    if not isinstance(models, list):
        raise BuildAgentError(f"models registry must declare a models list: {registry_path}")
    return [model for model in models if isinstance(model, dict)]


def load_capabilities_registry(path: str | Path | None = None) -> dict[str, dict[str, Any]]:
    """Load and lightly validate the closed capability registry."""
    registry_path = _resolve_registry_path(
        path,
        "AGENT_CAPABILITIES_REGISTRY",
        DEFAULT_CAPABILITIES_REGISTRY,
    )
    data = _load_yaml_mapping(registry_path)
    capabilities = data.get("capabilities", [])
    if not isinstance(capabilities, list):
        raise BuildAgentError(
            f"capabilities registry must declare a capabilities list: {registry_path}"
        )

    by_name: dict[str, dict[str, Any]] = {}
    for capability in capabilities:
        if not isinstance(capability, dict):
            continue
        name = capability.get("name")
        if not isinstance(name, str) or not name:
            raise BuildAgentError(f"Capability entry missing name in {registry_path}")
        if name in by_name:
            raise BuildAgentError(f"Duplicate capability '{name}' in {registry_path}")
        by_name[name] = capability
    return by_name


def _load_compose_module() -> Any:
    """Load compose-agent.py despite the hyphen in its filename."""
    spec = importlib.util.spec_from_file_location("compose_agent", COMPOSE_SCRIPT)
    if spec is None or spec.loader is None:
        raise BuildAgentError(f"Unable to load composer from {COMPOSE_SCRIPT}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def parse_frontmatter(text: str) -> tuple[dict[str, Any], str]:
    """Parse YAML frontmatter from a Markdown source."""
    lines = text.split("\n")
    if not lines or lines[0].strip() != "---":
        return {}, text
    for i, line in enumerate(lines[1:], start=1):
        if line.strip() == "---":
            frontmatter_text = "\n".join(lines[1:i])
            body = "\n".join(lines[i + 1:])
            return yaml.safe_load(frontmatter_text) or {}, body.lstrip("\n")
    raise BuildAgentError("Missing closing frontmatter delimiter")


def filter_harness_body(body: str, harness: str) -> str:
    """Return body text with non-target harness directive blocks removed."""
    if harness not in SUPPORTED_HARNESSES:
        raise BuildAgentError(f"Unsupported harness: {harness}")

    start_re = re.compile(r"^:::\s*harness\s+([A-Za-z0-9_-]+)\s*:::\s*$")
    end_re = re.compile(r"^:::\s*end\s*:::\s*$")
    output: list[str] = []
    active_harness: str | None = None
    active_line = 0

    for line_number, line in enumerate(body.splitlines(), start=1):
        start_match = start_re.match(line)
        if start_match:
            if active_harness is not None:
                raise BuildAgentError(
                    f"Nested harness directive at line {line_number}; "
                    f"previous block started at line {active_line}"
                )
            block_harness = start_match.group(1)
            if block_harness not in SUPPORTED_HARNESSES:
                raise BuildAgentError(
                    f"Unsupported harness directive '{block_harness}' at line {line_number}"
                )
            active_harness = block_harness
            active_line = line_number
            continue

        if end_re.match(line):
            if active_harness is None:
                raise BuildAgentError(f"Unmatched harness directive end at line {line_number}")
            active_harness = None
            active_line = 0
            continue

        if line.strip().startswith(":::") and (
            "harness" in line or line.strip().startswith("::: end")
        ):
            raise BuildAgentError(f"Malformed harness directive at line {line_number}: {line}")

        if active_harness is None or active_harness == harness:
            output.append(line)

    if active_harness is not None:
        raise BuildAgentError(
            f"Unclosed harness directive for '{active_harness}' starting at line {active_line}"
        )

    return "\n".join(output).strip() + "\n"


def _as_string_list(value: Any) -> list[str]:
    """Normalize a YAML scalar/list field into an ordered string list."""
    if value in (None, ""):
        return []
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    return [item.strip() for item in str(value).split(",") if item.strip()]


def _merge_ordered(existing: Any, additions: list[str]) -> list[str]:
    """Merge string lists while preserving first-seen order."""
    merged: list[str] = []
    seen: set[str] = set()
    for item in [*_as_string_list(existing), *additions]:
        if item not in seen:
            seen.add(item)
            merged.append(item)
    return merged


def _set_tools(frontmatter: dict[str, Any], additions: list[str]) -> None:
    """Merge Claude tools into the comma-string shape used by source agents."""
    merged = _merge_ordered(frontmatter.get("tools"), additions)
    if merged:
        frontmatter["tools"] = ", ".join(merged)


def _set_list_field(frontmatter: dict[str, Any], key: str, additions: list[str]) -> None:
    """Merge a list-like frontmatter field."""
    merged = _merge_ordered(frontmatter.get(key), additions)
    if merged:
        frontmatter[key] = merged


def _merge_sandbox(current: Any, candidate: Any) -> str | None:
    """Return the more permissive Codex sandbox mode."""
    current_value = str(current) if current else ""
    candidate_value = str(candidate) if candidate else ""
    if current_value and current_value not in SANDBOX_RANK:
        raise BuildAgentError(f"Unknown sandbox_mode '{current_value}'")
    if candidate_value and candidate_value not in SANDBOX_RANK:
        raise BuildAgentError(f"Unknown sandbox_mode '{candidate_value}'")
    if not current_value:
        return candidate_value or None
    if not candidate_value:
        return current_value
    return (
        current_value
        if SANDBOX_RANK[current_value] >= SANDBOX_RANK[candidate_value]
        else candidate_value
    )


def _model_requirements_for_harness(
    model_spec: dict[str, Any],
    harness: str,
) -> tuple[str | None, dict[str, Any]]:
    """Return explicit model id or requirement mapping for a target harness."""
    registry_harness = _registry_harness(harness)
    requirements = {
        key: value
        for key, value in model_spec.items()
        if key not in MODEL_HARNESS_KEYS
    }

    override = None
    for key in (harness, registry_harness):
        if key in model_spec:
            override = model_spec[key]
            break

    if isinstance(override, str):
        return override, requirements
    if isinstance(override, dict):
        requirements.update(override)
    elif override is not None:
        raise BuildAgentError(f"model.{harness} must be a string or mapping")

    return None, requirements


def _cost_total(model: dict[str, Any]) -> float:
    """Return total relative cost for sorting candidate models."""
    cost = model.get("cost", {})
    if not isinstance(cost, dict):
        return 0.0
    return float(cost.get("input", 0)) + float(cost.get("output", 0))


def _max_reasoning_rank(model: dict[str, Any]) -> int:
    """Return the highest reasoning rank supported by a model."""
    levels = model.get("reasoning_levels", [])
    if not isinstance(levels, list):
        return -1
    return max((REASONING_RANK.get(str(level), -1) for level in levels), default=-1)


def _model_matches(model: dict[str, Any], harness: str, requirements: dict[str, Any]) -> bool:
    """Return True if a model registry entry satisfies the target requirements."""
    if model.get("harness") != _registry_harness(harness):
        return False

    tier = requirements.get("tier")
    if tier and TIER_RANK.get(str(model.get("tier")), -1) < TIER_RANK.get(str(tier), 99):
        return False

    context = requirements.get("context")
    if context and CONTEXT_RANK.get(str(model.get("context")), -1) < CONTEXT_RANK.get(str(context), 99):
        return False

    reasoning = requirements.get("reasoning")
    if reasoning:
        levels = {str(level) for level in model.get("reasoning_levels", [])}
        if str(reasoning) not in levels:
            return False

    vision = requirements.get("vision")
    if vision is not None and bool(model.get("vision")) is not bool(vision):
        return False

    return True


def _sort_models(
    candidates: list[dict[str, Any]],
    requirements: dict[str, Any],
) -> list[dict[str, Any]]:
    """Sort matching models according to cost_priority."""
    cost_priority = str(requirements.get("cost_priority", "cheapest"))
    required_tier = str(requirements.get("tier", "economy"))
    required_tier_rank = TIER_RANK.get(required_tier, 0)

    if cost_priority == "quality-first":
        return sorted(
            candidates,
            key=lambda model: (
                -TIER_RANK.get(str(model.get("tier")), 0),
                -_max_reasoning_rank(model),
                _cost_total(model),
            ),
        )
    if cost_priority == "balanced":
        return sorted(
            candidates,
            key=lambda model: (
                TIER_RANK.get(str(model.get("tier")), 0) - required_tier_rank,
                _cost_total(model),
            ),
        )
    if cost_priority != "cheapest":
        raise BuildAgentError(
            "model.cost_priority must be one of cheapest, balanced, quality-first"
        )
    return sorted(candidates, key=lambda model: (_cost_total(model), model.get("id", "")))


def resolve_model(
    model_spec: Any,
    harness: str,
    models_registry: list[dict[str, Any]],
) -> tuple[str, str | None] | None:
    """Resolve a model frontmatter block to a concrete model id and reasoning level."""
    if not isinstance(model_spec, dict):
        return None

    explicit_model, requirements = _model_requirements_for_harness(model_spec, harness)
    if explicit_model:
        return explicit_model, requirements.get("reasoning")
    if not requirements:
        return None

    candidates = [
        model
        for model in models_registry
        if _model_matches(model, harness, requirements)
    ]
    if not candidates:
        rendered = ", ".join(f"{key}={value}" for key, value in sorted(requirements.items()))
        raise BuildAgentError(
            f"No model in models.yaml matches harness '{_registry_harness(harness)}' "
            f"with requirements: {rendered}"
        )

    selected = _sort_models(candidates, requirements)[0]
    model_id = selected.get("id")
    if not isinstance(model_id, str) or not model_id:
        raise BuildAgentError("Selected model entry is missing id")
    reasoning = requirements.get("reasoning") or selected.get("default_reasoning")
    return model_id, str(reasoning) if reasoning else None


def apply_model_resolution(
    merged: dict[str, Any],
    shared_frontmatter: dict[str, Any],
    override: dict[str, Any],
    harness: str,
    models_registry: list[dict[str, Any]],
) -> None:
    """Resolve capability-era model declarations into concrete harness fields."""
    shared_model = shared_frontmatter.get("model", "inherit")

    if isinstance(shared_model, dict) and "model" not in override:
        resolved = resolve_model(shared_model, harness, models_registry)
        if resolved:
            model_id, reasoning = resolved
            merged["model"] = model_id
            _set_list_field(merged, "model_standards", [model_id])
            if harness == "codex" and reasoning and "model_reasoning_effort" not in merged:
                merged["model_reasoning_effort"] = CODEX_REASONING_VALUE.get(reasoning, reasoning)
        return

    if "model" in merged and isinstance(merged["model"], str) and shared_model != "inherit":
        _set_list_field(merged, "model_standards", [str(merged["model"])])


def apply_capabilities(
    merged: dict[str, Any],
    harness: str,
    capabilities_registry: dict[str, dict[str, Any]],
) -> None:
    """Project capability names to harness-native tool/MCP/sandbox fields."""
    capabilities = _as_string_list(merged.get("capabilities"))
    if not capabilities:
        return

    registry_harness = _registry_harness(harness)
    for capability_name in capabilities:
        capability = capabilities_registry.get(capability_name)
        if capability is None:
            known = ", ".join(sorted(capabilities_registry))
            raise BuildAgentError(
                f"Unknown capability '{capability_name}'. Register it in capabilities.yaml "
                f"before using it. Known capabilities: {known}"
            )

        binding = capability.get(harness) or capability.get(registry_harness) or {}
        if not isinstance(binding, dict):
            raise BuildAgentError(
                f"Capability '{capability_name}' binding for '{registry_harness}' must be a mapping"
            )

        if harness == "claude":
            _set_tools(merged, _as_string_list(binding.get("tools")))
            _set_list_field(merged, "mcpServers", _as_string_list(binding.get("mcpServers")))
            _set_list_field(merged, "skills", _as_string_list(binding.get("skills")))
        elif harness == "codex":
            sandbox = _merge_sandbox(merged.get("sandbox_mode"), binding.get("sandbox_mode"))
            if sandbox:
                merged["sandbox_mode"] = sandbox
            _set_list_field(merged, "mcp_servers", _as_string_list(binding.get("mcp_servers")))
            _set_list_field(merged, "skills", _as_string_list(binding.get("skills")))


def frontmatter_for_harness(
    frontmatter: dict[str, Any],
    harness: str,
    models_registry: list[dict[str, Any]] | None = None,
    capabilities_registry: dict[str, dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Merge shared frontmatter with target-harness override fields."""
    merged = {
        key: value
        for key, value in frontmatter.items()
        if key not in HARNESS_OVERRIDE_KEYS
    }
    override = frontmatter.get(harness, {})
    if override is None:
        override = {}
    if not isinstance(override, dict):
        raise BuildAgentError(f"Frontmatter key '{harness}' must be a mapping")
    merged.update(override)
    if models_registry is not None:
        apply_model_resolution(merged, frontmatter, override, harness, models_registry)
    if capabilities_registry is not None:
        apply_capabilities(merged, harness, capabilities_registry)
    if harness == "codex":
        apply_codex_defaults(merged, frontmatter, override)
    return merged


def _tool_names(value: Any) -> set[str]:
    """Normalize a tools field into a set of tool names."""
    if isinstance(value, list):
        return {str(item).strip() for item in value if str(item).strip()}
    if not value:
        return set()
    return {item.strip() for item in str(value).split(",") if item.strip()}


def apply_codex_defaults(
    merged: dict[str, Any],
    shared_frontmatter: dict[str, Any],
    override: dict[str, Any],
) -> None:
    """Fill Codex TOML fields when a unified source has no explicit override."""
    shared_model = str(shared_frontmatter.get("model", "inherit"))
    if "model" not in override and shared_model in CODEX_MODEL_MAP:
        merged["model"] = CODEX_MODEL_MAP[shared_model]

    if "model_reasoning_effort" not in merged:
        merged["model_reasoning_effort"] = CODEX_REASONING_BY_MODEL.get(shared_model, "medium")

    if "sandbox_mode" not in merged:
        tools = _tool_names(shared_frontmatter.get("tools"))
        if {"Write", "Edit", "MultiEdit"} & tools:
            merged["sandbox_mode"] = "workspace-write"
        else:
            merged["sandbox_mode"] = "read-only"

    if "nickname_candidates" not in merged and merged.get("name"):
        merged["nickname_candidates"] = [str(merged["name"])]


def render_source_for_harness(
    source: Path,
    harness: str,
    models_registry: list[dict[str, Any]] | None = None,
    capabilities_registry: dict[str, dict[str, Any]] | None = None,
) -> tuple[dict[str, Any], str]:
    """Render a unified source into target-specific Markdown source text."""
    text = source.read_text(encoding="utf-8")
    frontmatter, body = parse_frontmatter(text)
    target_frontmatter = frontmatter_for_harness(
        frontmatter,
        harness,
        models_registry=models_registry,
        capabilities_registry=capabilities_registry,
    )
    target_body = filter_harness_body(body, harness)
    frontmatter_text = yaml.safe_dump(
        target_frontmatter,
        sort_keys=False,
        default_flow_style=False,
    ).strip()
    return target_frontmatter, f"---\n{frontmatter_text}\n---\n\n{target_body}"


def _toml_scalar(value: Any) -> str:
    """Serialize a small TOML scalar or string list."""
    if isinstance(value, list):
        return "[" + ", ".join(json.dumps(str(item), ensure_ascii=False) for item in value) + "]"
    if isinstance(value, bool):
        return "true" if value else "false"
    return json.dumps(str(value), ensure_ascii=False)


def _toml_multiline(value: Any, compose_module: Any) -> str:
    escaped = compose_module.escape_for_toml(str(value))
    return f'"""\n{escaped}\n"""'


def emit_codex_toml(
    frontmatter: dict[str, Any],
    developer_instructions: str,
    source: Path,
    compose_module: Any,
) -> str:
    """Emit a Codex agent TOML document."""
    fields = {
        key: value
        for key, value in frontmatter.items()
        if key in CODEX_TOML_FIELDS and value not in (None, "")
    }
    if "name" not in fields:
        raise BuildAgentError("Codex output requires a name field")
    if "description" not in fields:
        raise BuildAgentError("Codex output requires a description field")

    lines = [
        f"# Generated by scripts/build-agent.py from {source.name}",
        "# Do not edit this artifact directly; edit the unified Markdown source.",
    ]
    mcp_servers = _as_string_list(frontmatter.get("mcp_servers"))
    if mcp_servers:
        lines.extend(
            [
                "# Resolved capability MCP bindings for Codex.",
                "# Codex inherits MCP servers from ~/.codex/config.toml.",
                f"# mcp_servers: {json.dumps(mcp_servers, ensure_ascii=False)}",
            ]
        )
    lines.append("")
    for key, value in fields.items():
        if key == "description":
            lines.append(f"{key} = {_toml_multiline(value, compose_module)}")
        else:
            lines.append(f"{key} = {_toml_scalar(value)}")
    lines.extend([
        "",
        f"developer_instructions = \"\"\"\n{developer_instructions}\n\"\"\"",
        "",
    ])
    return "\n".join(lines)


def build_agent(
    source: Path,
    output_dir: Path,
    harnesses: list[str],
    agent_bases_dir: str | None = None,
    model_standards_dir: str | None = None,
    models_registry_path: str | Path | None = None,
    capabilities_registry_path: str | Path | None = None,
) -> list[Path]:
    """Build requested harness-native artifacts and return written paths."""
    compose_module = _load_compose_module()
    models_registry = load_models_registry(models_registry_path)
    capabilities_registry = load_capabilities_registry(capabilities_registry_path)
    output_dir.mkdir(parents=True, exist_ok=True)
    written: list[Path] = []

    for harness in harnesses:
        frontmatter, rendered = render_source_for_harness(
            source,
            harness,
            models_registry=models_registry,
            capabilities_registry=capabilities_registry,
        )
        name = frontmatter.get("name")
        if not name:
            raise BuildAgentError("Agent source must declare frontmatter name")

        with TemporaryDirectory() as tmp:
            rendered_source = Path(tmp) / f"{name}.md"
            rendered_source.write_text(rendered, encoding="utf-8")
            try:
                composed = compose_module.compose(
                    agent_file=rendered_source,
                    harness=harness,
                    agent_bases_dir=agent_bases_dir,
                    model_standards_dir=model_standards_dir,
                )
            except SystemExit as exc:
                code = exc.code if isinstance(exc.code, int) else 1
                raise BuildAgentError(f"Composition failed for {harness} with exit {code}") from exc

        if harness == "claude":
            target = output_dir / f"{name}.md"
            target.write_text(composed, encoding="utf-8")
        elif harness == "codex":
            target = output_dir / f"{name}.toml"
            toml_text = emit_codex_toml(frontmatter, composed, source, compose_module)
            target.write_text(toml_text, encoding="utf-8")
        else:
            target = output_dir / f"{name}.md"
            target.write_text(composed, encoding="utf-8")
        written.append(target)

    return written


def _parse_harness_arg(value: str) -> list[str]:
    if value == "all":
        return ["claude", "codex"]
    if value in SUPPORTED_HARNESSES:
        return [value]
    raise argparse.ArgumentTypeError(f"Unsupported harness: {value}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Build Claude/Codex agent artifacts from one Markdown source.",
    )
    parser.add_argument("source", type=Path, help="Unified agent Markdown source.")
    parser.add_argument(
        "--harness",
        default="all",
        choices=["all", "claude", "codex", "opencode"],
        help="Harness artifact to build (default: all).",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        required=True,
        help="Directory where built artifacts are written.",
    )
    parser.add_argument(
        "--agent-bases-dir",
        default=None,
        help="Override agent-bases directory for composition.",
    )
    parser.add_argument(
        "--model-standards-dir",
        default=None,
        help="Override model-standards directory for composition.",
    )
    parser.add_argument(
        "--models-registry",
        default=None,
        help="Override models.yaml registry path.",
    )
    parser.add_argument(
        "--capabilities-registry",
        default=None,
        help="Override capabilities.yaml registry path.",
    )
    args = parser.parse_args(argv)

    try:
        written = build_agent(
            source=args.source,
            output_dir=args.output_dir,
            harnesses=_parse_harness_arg(args.harness),
            agent_bases_dir=args.agent_bases_dir,
            model_standards_dir=args.model_standards_dir,
            models_registry_path=args.models_registry,
            capabilities_registry_path=args.capabilities_registry,
        )
    except (BuildAgentError, OSError, yaml.YAMLError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    for path in written:
        print(path)
    return 0


if __name__ == "__main__":
    sys.exit(main())
