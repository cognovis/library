# Script

> Primitive reference extracted from [PRIMITIVES.md](../PRIMITIVES.md).

**Definition.** A deterministic Python helper distributed by the Library and called
by another primitive or runtime surface. Scripts are not model-context by default:
they are executable implementation artifacts with typed metadata, tests, and output
contracts.

**Key constitutive feature.** Deterministic execution: scripts hold logic that should
not be re-created by the model. They are callable by skills, agents, commands,
hooks/guardrails, standards, tests, CI, and Gas City pack exports.

**Language rule.** Cognovis Library scripts are **Python-only**. NORMATIVE.

Rationale: Python gives structured parsing, testability, packaging through `uv`,
and stable cross-platform behavior. Shell snippets remain acceptable as one-line
usage examples in docs, but reusable Library scripts are Python.

**Trigger semantics.** A script is never auto-selected by the model. It runs only when
another primitive or runtime calls it explicitly. Examples:

- a skill says "run `scripts/validate-spec.py`";
- a hook executes a Python guard script;
- a Gas City pack command uses the script as `commands/<name>/run.py`;
- a Gas City doctor check uses the script as `doctor/<name>/run.py`;
- a formula step calls a script through a command or provider session.

**Catalog format.** First-class scripts live under `library.scripts` in
`library.yaml`:

```yaml
- name: validate-spec
  description: Validate a spec document and return structured findings.
  source: https://github.com/cognovis/library-core/blob/main/scripts/validate-spec.py
  language: python
  output_contract: json-envelope
  metadata:
    library:
      plane: dev
      gascity:
        exportable: true
        projections:
          - target: script
            pack: cognovis-specs
            scope: rig
            target_path: assets/scripts/validate-spec.py
```

Skills, agents, standards, hooks, and prompts can also declare bundled scripts in
their catalog entry:

```yaml
scripts:
  - path: scripts/check.py
    role: validator
    entrypoint: true
    language: python
    output_contract: json-envelope
```

**Output contracts.**

| Contract | Use when |
|----------|----------|
| `json-envelope` | Multiple fields, warnings/errors, or next actions must be machine-readable |
| `bare-value` | The script prints exactly one atomic value |
| `exit-code` | The consumer only needs pass/fail plus stderr diagnostics |

The preferred general contract is `json-envelope`:

```json
{"status":"ok","summary":"one sentence","data":{},"errors":[],"next_steps":[]}
```

**Where scripts live.**

| Context | Script location |
|---------|----------------|
| First-class Library script | `scripts/<name>.py` or `scripts/<name>/<name>.py` |
| Skill implementation | `skills/<name>/scripts/<name>.py` |
| Agent helper | `agents/<name>/scripts/<name>.py` when the helper is agent-private |
| Standard enforcement/tooling | `standards/<name>/scripts/<name>.py` |
| Guardrail implementation | `guardrails/<name>/<harness-or-purpose>.py` |
| Gas City export | `assets/scripts/`, `commands/<name>/run.py`, or `doctor/<name>/run.py` |

**When to choose it.** Create a script when:

- logic is deterministic, testable, and over roughly 50 lines;
- a prompt would otherwise contain a shell/Python pipeline;
- structured parsing or transformation is required;
- the same helper will be reused by multiple primitives;
- Gas City pack export needs a deterministic command or doctor entrypoint.

**Counter-examples.**

- Do NOT make a script for model judgment, prioritization, or tradeoff reasoning.
- Do NOT hide workflow policy in a script if the model must reason about it; put
  policy in a skill, standard, or agent prompt and use scripts only for mechanics.
- Do NOT add shell scripts to the Library. Convert reusable shell logic to Python.

**Anti-pattern.** A 200-line shell pipeline embedded in a skill's prompt is a smell.
The model will hallucinate flags, get argument order wrong, and produce non-reproducible
results. Extract to a Python script and have the skill call it.

**Projection as MCP tools.** A Script can be projected as a typed tool by a
`library-tool-surface` [MCP server](mcp-server.md#species-2-library-tool-surface)
(established by [ADR-0007](../adr/library-tool-surface-mcp.md)). The Script
remains the deterministic backing implementation; the MCP tool wraps it
with a typed schema, server-side argument validation, and a stable JSON
envelope visible to the model as a first-class tool. Use this projection
when the same Script is invoked from many call sites and the agent
currently re-derives its invocation from skill prose. The mapping between
typed tool and backing Script lives in the server, not in `library.yaml` —
MCP's `tools/list` is the runtime source of truth.

---
