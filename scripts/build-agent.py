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
COMPOSE_SCRIPT = SCRIPT_DIR / "compose-agent.py"
SUPPORTED_HARNESSES = {"claude", "codex", "opencode"}
COMPOSER_ONLY_KEYS = {
    "agent_base_extends",
    "golden_prompt_extends",
    "model_standards",
    "requires",
}
HARNESS_OVERRIDE_KEYS = {"claude", "codex", "opencode"}
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


class BuildAgentError(Exception):
    """Raised when a unified agent source cannot be built."""


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


def frontmatter_for_harness(frontmatter: dict[str, Any], harness: str) -> dict[str, Any]:
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


def render_source_for_harness(source: Path, harness: str) -> tuple[dict[str, Any], str]:
    """Render a unified source into target-specific Markdown source text."""
    text = source.read_text(encoding="utf-8")
    frontmatter, body = parse_frontmatter(text)
    target_frontmatter = frontmatter_for_harness(frontmatter, harness)
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
        "",
    ]
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
) -> list[Path]:
    """Build requested harness-native artifacts and return written paths."""
    compose_module = _load_compose_module()
    output_dir.mkdir(parents=True, exist_ok=True)
    written: list[Path] = []

    for harness in harnesses:
        frontmatter, rendered = render_source_for_harness(source, harness)
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
    args = parser.parse_args(argv)

    try:
        written = build_agent(
            source=args.source,
            output_dir=args.output_dir,
            harnesses=_parse_harness_arg(args.harness),
            agent_bases_dir=args.agent_bases_dir,
            model_standards_dir=args.model_standards_dir,
        )
    except (BuildAgentError, OSError, yaml.YAMLError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    for path in written:
        print(path)
    return 0


if __name__ == "__main__":
    sys.exit(main())
