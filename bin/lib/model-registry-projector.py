#!/usr/bin/env python3
"""Project Library models.yaml into the cognovis-tools runtime registry format."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import yaml


def project_registry(source: dict[str, Any]) -> dict[str, Any]:
    models = []
    for item in source["models"]:
        models.append({
            "id": item["id"],
            "family": item["family"],
            "provider": item["provider"],
            "adapter": item["adapter"],
            "model": item["runtime_model"],
            "reasoning_efforts": item["reasoning_levels"],
            "default_reasoning_effort": item.get("default_reasoning", ""),
            "capabilities": item["suitability_capabilities"],
            "quality_rank": item["quality_rank"],
            "cost_rank": item["cost_rank"],
        })
    return {
        "schema_version": 1,
        "registry_version": source["runtime_registry_version"],
        "models": models,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    source = yaml.safe_load(args.source.read_text(encoding="utf-8"))
    rendered = json.dumps(project_registry(source), indent=2, sort_keys=True) + "\n"
    if args.output:
        args.output.write_text(rendered, encoding="utf-8")
    else:
        print(rendered, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
