---
name: script-forge
description: >-
  Create, validate, and catalog first-class Python script primitives for the Library.
  Use when deterministic helper logic should be reusable across skills, agents, hooks,
  standards, commands, or Gas City packs. Triggers on create script, script-forge,
  first-class script, Python helper, pack command script, doctor script, formula script.
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
| Deterministic route? | Scripts are the destination for deterministic parsing, scanning, validation, export, and transformation logic; wrap them with skills, hooks, agents, standards, or Gas City surfaces only when a caller needs them. |
| Gas City projection? | PackV2 command, doctor, formula, or asset metadata is catalog metadata; the Python source remains a Library or repo-local script. |

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
5. **Gas City targets:** `asset`, `command`, `doctor`, or `formula` if pack-exportable.
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
      gascity:
        exportable: <true|false>
        projections:
          - target: script
            pack: <pack-name>
            scope: <city|rig|provider|global>
            session_class: none
            provider_neutral: true
            requires:
              binaries: []
              env: []
              standards: []
  tags:
    - origin:original
    - tier:core
```

Omit `product_counterpart:` when there is no paired product-plane artifact.
Legacy `gascity.target`, `gascity.pack`, and `gascity.scope` may remain on
existing catalog entries, but new snippets should use `gascity.projections[]`.

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
python3 ../meta/scripts/validate-gascity-export.py --yaml ../meta/library.yaml
```

Script-specific checks:

- source or entrypoint ends in `.py`;
- `language: python`;
- Gas City export metadata has `target`, `pack`, and `scope` when exportable;
- bundled scripts are declared in `scripts:`;
- command/doctor/formula-step script roles set `entrypoint: true`.

## Consumer Runtime Gate

Run this gate before closeout when a script change may affect downstream project
repos.

- If a consumer repo executes the script by repo-local path, either promote it
  to a first-class `library.scripts` primitive or list the copied path under
  `managed_files` in `consumer-projects.yml`.
- If a standard, agent, skill, or hook instructs consumer repos to call the
  script, run a consumer updater dry-run:

```bash
python3 scripts/update-consumers.py --json
python3 scripts/update-consumers.py --consumer <name> --json
```

- If the dry-run reports planned changes, either run
  `python3 scripts/update-consumers.py --consumer <name> --apply --json` and
  finish the target repo commit, or file/follow a consumer propagation bead.

Do not leave ad hoc copy steps in prompts or forge output. Consumer propagation
belongs in `consumer-projects.yml` plus the updater dry-run/apply workflow.

## Do NOT

- Do NOT create Bash, zsh, sh, Ruby, Node, or mixed-language Library scripts.
- Do NOT put provider auth secrets in metadata or script defaults.
- Do NOT hide policy decisions in a script when a model must reason about them.
- Do NOT make a script first-class if exactly one primitive owns it and no second
  consumer or pack export exists.
