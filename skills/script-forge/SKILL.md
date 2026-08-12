---
name: script-forge
description: >-
  Create, validate, and catalog first-class Python script primitives for the Library.
  Use when deterministic helper logic should be reusable across skills, agents, hooks,
  standards, or commands. Triggers on create script, script-forge,
  first-class script, Python helper, reusable validation script, doctor script, or formula script.
requires_standards: [agentic-primitives, primitive-placement, english-only, no-emoji]
---

# Script Forge

Scaffold deterministic Python helpers as first-class Library script primitives or
as bundled scripts owned by another primitive.

## Primitive Gate

Before creating anything, classify the request:

| Signal | Action |
|---|---|
| Deterministic parsing, scanning, validation, transformation, or export logic | Continue |
| Model judgment, prioritization, or tradeoff reasoning | Dispatch to `skill-forge` or `agent-forge` |
| User-facing slash workflow | Create a command that calls a script, not only a script |
| Lifecycle enforcement | Create a guardrail/hook that calls a script |
| Factual context | Dispatch to `standard-forge` |

Scripts are Python-only. Convert reusable shell logic to Python before cataloging it.

## Placement Gate

Use `standards/agentic-primitives/primitive-placement.md` before deciding whether
a script is first-class, bundled, repo-local, or product-owned.

| Question | Script-forge rule |
|----------|-------------------|
| Steward marketplace? | Platform self-description scripts belong in `library-platform`; other reusable dev-plane scripts belong in `cognovis-core` or `sussdorff-core`; third-party scripts keep third-party provenance; product-path scripts stay `repo-local`. |
| Dev-plane or product-plane? | A script that ships as product runtime code is a product-plane artifact, not a Library script. Refuse Library cataloging and redirect to a product repo bead. |
| Product counterpart? | A dev-plane validator/exporter that supports Mira, Polaris, FHIR, or another product artifact should record `repo`, `path`, `name`, `primitive_type`, and `notes`. Put bead or ADR references in `notes`. |
| Repo-local escape hatch? | Keep scripts local when they bake in one repo's filesystem, ADR IDs, credentials, generated paths, or deployment topology. |
| Harness support? | Ask whether the script works in all harnesses or is harness-specific. For one-harness scripts, set `metadata.library.harness_support.<harness>: supported` and mark the others `not-supported`. |
| Runtime requirements? | Ask whether the script requires external binaries such as `bun`, `rg`, `sushi`, or `shellcheck`; declare them under `runtime_requirements.binaries` when needed. |
| Deterministic route? | Scripts are the destination for deterministic parsing, scanning, validation, export, and transformation logic; wrap them with skills, hooks, agents, or standards only when a caller needs them. |

Product-plane refusal message:

```
This script is product-plane runtime code, not a Library script primitive.
Create or reference a product repository bead. A dev-plane script may validate or
export for that product counterpart, but it must not become the runtime source.
```

## Create Mode

Ask these questions, one at a time when not already answered:

1. **Name:** kebab-case script identifier.
2. **Ownership:** first-class `library.scripts` entry or bundled under an owning
   primitive (`skill`, `agent`, `standard`, `guardrail`, `prompt`)?
3. **Role:** `helper`, `entrypoint`, `command`, `doctor`, `validator`, `exporter`, or
   `formula-step`.
4. **Output contract:** `json-envelope`, `bare-value`, or `exit-code`.
6. **Runtime requirements:** binaries, environment variable names, standards.

## Scaffold

For a first-class script, prefer the bundled scaffolder:

```bash
python3 scripts/init-script.py <name> --description "<one sentence>"
```

It creates the script file, pytest skeleton, and a printable `library.yaml`
catalog stub.

For a first-class script, use:

```text
scripts/<name>/<name>.py
scripts/<name>/tests/test_<name_as_snake>.py
```

For a bundled script, use:

```text
<owner-root>/scripts/<name>.py
```

The Python file should:

- use `argparse` for CLI arguments;
- keep all source code, comments, log messages, and identifiers in English;
- return a JSON envelope for multi-field output;
- avoid prompting interactively;
- exit non-zero only for real execution failure or validation failure;
- include a `main()` returning an integer exit code.

Minimal JSON envelope:

```json
{"status":"ok","summary":"one sentence","data":{},"errors":[],"next_steps":[]}
```

## Catalog Snippets

First-class script:

```yaml
- name: <name>
  description: >-
    <what the script deterministically does>
  source: https://github.com/cognovis/library-core/blob/main/scripts/<name>/<name>.py
  language: python
  entrypoint: <name>.py
  output_contract: json-envelope
  metadata:
    library:
      plane: dev
      product_counterpart:
        repo: <product-repo>
        path: <product-path>
        name: <product-feature-or-script>
        primitive_type: <command|workflow|service|other>
        notes: <why this dev-plane script supports the product surface>
  tags:
    - origin:original
    - tier:core
```

Omit `product_counterpart:` when there is no paired product-plane artifact.

Bundled script declaration inside an owning primitive's catalog entry:

```yaml
scripts:
  - path: scripts/<name>.py
    role: <helper|entrypoint|command|doctor|validator|exporter|formula-step>
    entrypoint: <true|false>
    language: python
    output_contract: json-envelope
```

## Validation

Run Library validation after updating `library.yaml`:

```bash
python3 ../meta/scripts/validate-library.py --yaml ../meta/library.yaml
```

Script-specific checks:

- source or entrypoint ends in `.py`;
- `language: python`;
- bundled scripts are declared in `scripts:`;
- command/doctor/formula-step script roles set `entrypoint: true`.

## Consumer Runtime Gate

Run this gate before closeout when a script change may affect downstream project
repos.

- If a consumer repo executes the script by repo-local path, either promote it
  to a first-class `library.scripts` primitive or declare it in the target
  Workspace.
- If a standard, agent, skill, or hook instructs consumer repos to call the
  script, run a consumer updater dry-run:

```bash
library workspace status --all --scope project
```

- If the dry-run reports planned changes, either run
  `library workspace sync --all --scope project --apply` and
  finish the target repo commit, or file/follow a consumer propagation bead.

Do not leave ad hoc copy steps in prompts or forge output. Consumer propagation
belongs in the Workspace definition and reconciliation workflow.

## Do NOT

- Do NOT create Bash, zsh, sh, Ruby, Node, or mixed-language Library scripts.
- Do NOT put provider auth secrets in metadata or script defaults.
- Do NOT hide policy decisions in a script when a model must reason about them.
- Do NOT make a script first-class if exactly one primitive owns it and no second
  consumer exists.
