#!/usr/bin/env python3
"""
Scaffold a first-class Library Python script primitive.

Creates:
  scripts/<name>/<name>.py
  scripts/<name>/tests/test_<name_as_snake>.py

The generated script uses a JSON envelope by default and the generated test
executes it through subprocess so kebab-case script filenames remain valid.
"""

from __future__ import annotations

import argparse
import re
import sys
import textwrap
from pathlib import Path


VALID_ROLES = {
    "helper",
    "entrypoint",
    "command",
    "doctor",
    "validator",
    "exporter",
    "formula-step",
}


def validate_script_name(name: str) -> tuple[bool, str]:
    """Validate a kebab-case Library script name."""
    if not name:
        return False, "Script name cannot be empty"
    if name != name.lower():
        return False, "Script name must be lowercase"
    if "_" in name:
        return False, "Use hyphens instead of underscores"
    if " " in name:
        return False, "Use hyphens instead of spaces"
    if name.startswith("-") or name.endswith("-"):
        return False, "Script name cannot start or end with a hyphen"
    if "--" in name:
        return False, "Script name cannot contain consecutive hyphens"
    if not re.fullmatch(r"[a-z][a-z0-9-]*", name):
        return False, "Use kebab-case with lowercase letters, numbers, and hyphens"
    return True, ""


def snake_name(name: str) -> str:
    """Return a Python-safe identifier fragment for test filenames."""
    return name.replace("-", "_")


def script_template(name: str, description: str, output_contract: str) -> str:
    """Return the generated script body."""
    summary = description.rstrip(".") if description else f"Run {name}"
    if output_contract == "json-envelope":
        output_block = (
            "print(json.dumps({\n"
            '    "status": "ok",\n'
            '    "summary": args.summary,\n'
            '    "data": {},\n'
            '    "errors": [],\n'
            '    "next_steps": [],\n'
            "}, indent=2))\n"
        )
        failure_argument = ""
    elif output_contract == "bare-value":
        output_block = "print(args.summary)\n"
        failure_argument = ""
    else:
        output_block = (
            "if args.fail:\n"
            "    if args.summary:\n"
            "        print(args.summary, file=sys.stderr)\n"
            "    return 1\n"
            "if args.summary:\n"
            "    print(args.summary)\n"
        )
        failure_argument = (
            "    parser.add_argument(\n"
            '        "--fail",\n'
            "        action=\"store_true\",\n"
            "        help=\"Exit non-zero to exercise the exit-code failure path.\",\n"
            "    )\n"
        )

    return (
        "#!/usr/bin/env python3\n"
        '"""\n'
        f"{summary}.\n"
        '"""\n'
        "\n"
        "from __future__ import annotations\n"
        "\n"
        "import argparse\n"
        "import json\n"
        "import sys\n"
        "\n\n"
        "def build_parser() -> argparse.ArgumentParser:\n"
        '    """Build the command line parser."""\n'
        f'    parser = argparse.ArgumentParser(description="{summary}.")\n'
        "    parser.add_argument(\n"
        '        "--summary",\n'
        f'        default="{summary}.",\n'
        '        help="Summary text to emit in the output contract.",\n'
        "    )\n"
        f"{failure_argument}"
        "    return parser\n"
        "\n\n"
        "def main(argv: list[str] | None = None) -> int:\n"
        '    """Run the script."""\n'
        "    parser = build_parser()\n"
        "    args = parser.parse_args(argv)\n"
        f"{textwrap.indent(output_block.rstrip(), '    ')}\n"
        "    return 0\n"
        "\n\n"
        'if __name__ == "__main__":\n'
        "    sys.exit(main())\n"
    )


def test_template(name: str, output_contract: str) -> str:
    """Return the generated pytest skeleton."""
    if output_contract == "json-envelope":
        assertion = (
            "data = json.loads(result.stdout)\n"
            'assert data["status"] == "ok"\n'
            'assert "summary" in data\n'
        )
    else:
        assertion = 'assert result.stdout.strip()\n'

    base_test = (
        "import json\n"
        "import subprocess\n"
        "import sys\n"
        "from pathlib import Path\n"
        "\n\n"
        f'SCRIPT = Path(__file__).resolve().parents[1] / "{name}.py"\n'
        "\n\n"
        f"def test_{snake_name(name)}_runs():\n"
        "    result = subprocess.run(\n"
        "        [sys.executable, str(SCRIPT)],\n"
        "        capture_output=True,\n"
        "        text=True,\n"
        "        check=False,\n"
        "    )\n"
        "    assert result.returncode == 0, result.stderr\n"
        f"{textwrap.indent(assertion, '    ')}"
    )

    if output_contract != "exit-code":
        return base_test

    return (
        base_test
        + "\n\n"
        f"def test_{snake_name(name)}_failure_path_returns_nonzero():\n"
        "    result = subprocess.run(\n"
        '        [sys.executable, str(SCRIPT), "--fail"],\n'
        "        capture_output=True,\n"
        "        text=True,\n"
        "        check=False,\n"
        "    )\n"
        "    assert result.returncode != 0\n"
        "    assert result.stderr.strip()\n"
    )


def catalog_stub(name: str, description: str, role: str, output_contract: str) -> str:
    """Return a Library catalog stub for the generated script."""
    summary = description or f"Deterministically run {name}."
    target = {
        "command": "command",
        "doctor": "doctor",
        "formula-step": "formula",
    }.get(role, "script")
    gascity_target = "asset" if target == "script" else target
    return textwrap.dedent(
        f"""\
        - name: {name}
          description: >-
            {summary}
          source: https://github.com/cognovis/library-core/blob/main/scripts/{name}/{name}.py
          language: python
          entrypoint: {name}.py
          output_contract: {output_contract}
          gascity_targets:
            - {gascity_target}
          metadata:
            library:
              gascity:
                exportable: false
                target: {target}
                # TODO: choose the correct Gas City pack and scope before committing.
                pack: cognovis-base
                scope: global
                session_class: none
                provider_neutral: true
                requires:
                  binaries: []
                  env: []
                  standards: []
          tags:
            - origin:original
            - tier:core
        """
    )


def create_script(
    name: str,
    parent_dir: Path,
    description: str,
    role: str,
    output_contract: str,
    print_catalog: bool,
) -> int:
    """Create script files and print a catalog stub."""
    is_valid, error = validate_script_name(name)
    if not is_valid:
        print(f"Invalid script name: {error}", file=sys.stderr)
        return 1
    if role not in VALID_ROLES:
        print(f"Invalid role: {role}", file=sys.stderr)
        return 1
    if output_contract not in {"json-envelope", "bare-value", "exit-code"}:
        print(f"Invalid output contract: {output_contract}", file=sys.stderr)
        return 1

    script_dir = parent_dir / name
    script_path = script_dir / f"{name}.py"
    test_dir = script_dir / "tests"
    test_path = test_dir / f"test_{snake_name(name)}.py"

    existing = [path for path in (script_path, test_path) if path.exists()]
    if existing:
        for path in existing:
            print(f"Refusing to overwrite existing file: {path}", file=sys.stderr)
        return 1

    try:
        script_dir.mkdir(parents=True, exist_ok=True)
        test_dir.mkdir(parents=True, exist_ok=True)
        script_path.write_text(script_template(name, description, output_contract))
        test_path.write_text(test_template(name, output_contract))
        script_path.chmod(0o755)
    except OSError as exc:
        print(f"Failed to create script scaffold: {exc}", file=sys.stderr)
        return 1

    print(f"Created script: {script_path}")
    print(f"Created test: {test_path}")
    if print_catalog:
        print()
        print("Catalog stub:")
        print(catalog_stub(name, description, role, output_contract))
    return 0


def build_parser() -> argparse.ArgumentParser:
    """Build the command line parser."""
    parser = argparse.ArgumentParser(
        description="Initialize a first-class Library Python script primitive."
    )
    parser.add_argument("name", help="Script name in kebab-case")
    parser.add_argument(
        "--path",
        default="scripts",
        help="Parent scripts directory (default: scripts)",
    )
    parser.add_argument(
        "--description",
        default="",
        help="One-sentence script description for docstrings and catalog output",
    )
    parser.add_argument(
        "--role",
        default="helper",
        choices=sorted(VALID_ROLES),
        help="Script role for catalog metadata",
    )
    parser.add_argument(
        "--output-contract",
        default="json-envelope",
        choices=("json-envelope", "bare-value", "exit-code"),
        help="Output contract used by the generated script and test",
    )
    parser.add_argument(
        "--no-catalog",
        action="store_true",
        help="Do not print a Library catalog stub",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    """Run the scaffolder."""
    parser = build_parser()
    args = parser.parse_args(argv)
    return create_script(
        name=args.name,
        parent_dir=Path(args.path).resolve(),
        description=args.description,
        role=args.role,
        output_contract=args.output_contract,
        print_catalog=not args.no_catalog,
    )


if __name__ == "__main__":
    sys.exit(main())
