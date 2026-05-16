---
name: agent-forge
description: >-
  Create and review agents (subagents). Use when creating specialized AI
  assistants, reviewing/auditing existing agents, deciding between agent vs skill vs
  command, scaffolding judge agents, or asking about agent best practices, multi-agent pipelines, and model selection.
  Also use when making agents Gas City-packable, choosing polecat vs crew semantics,
  or separating provider-neutral core prompts from harness adapters.
  MUST BE USED when the user says "create agent", "new subagent", "review agent",
  "audit agent", "agent vs skill", or asks about multi-agent architecture.
disableModelInvocation: true
requires_standards: [agentic-primitives, primitive-placement, judge-layer, english-only, no-emoji]
---

# Agent Forge

Create, review, and improve agents -- specialized AI assistants with isolated context windows, custom system prompts, and configurable tool permissions.

## When to Use

**Triggers:** "create an agent", "new subagent", "review agent", "audit my agents", "agent vs skill", "multi-agent pipeline", "agent best practices", "improve this agent", "create a judge"

**Use agents when:**
- Task needs isolated context (prevents main conversation pollution)
- Custom system prompt and behavior required
- Different tool permissions or model than main agent
- Building multi-agent workflows

**Not agents -- use instead:**
- Procedural knowledge, no isolation needed -> Skill
- User-triggered shortcut, simple workflow -> Command

Full decision tree: `references/agent-vs-skill-vs-command.md`

## Justification Gate

Before scaffolding any agent, verify that at least one C1-C7 criterion holds.
If no criterion holds, do NOT proceed to Agent Creation Workflow — dispatch to skill-forge instead.

| ID | Criterion | Trigger phrase |
|----|-----------|----------------|
| **C1** | Needs a different tool permission set than the parent | "must NOT have Write/Bash", "read-only verifier", "tool grant narrower than caller" |
| **C2** | Needs its own context budget (~2k+ tokens of work, would pollute parent) | "big report", "long transcript analysis", "would blow up the orchestrator's window" |
| **C3** | Runs in parallel with sibling agents | "fan out across 5 inputs", "wave dispatch", "concurrent investigations" |
| **C4** | Information barrier required (read-only, blocked-from-X, isolated test vs. impl) | "implementer must not see review notes", "verification can't share context with implementation" |
| **C5** | Needs its own model (Haiku for cheap polling, Opus for deep reasoning) | "long idle poll", "deep architectural reasoning", "model differs from parent" |
| **C6** | Multi-phase stateful orchestration (>3 phases that must run in sequence) | "phase 1, then phase 2, then phase 3 with checkpoints", "session-close pipeline" |
| **C7** | Pre-action gate that decides whether a proposed side effect may execute | "judge", "validator", "guardrail before tool call", "authorization check before action" |

Gas City session shape is not a standalone agent justification. Only set
`metadata.library.gascity.session_class` after C1-C7 already justify an agent.
Use `polecat` for one-shot agent work, `crew` for persistent coordination or
interactive sessions, and `none` when the primitive should export as a command,
script, hook, formula, or overlay instead of an agent.

**If no criterion holds**, output the following message and stop:

```
This request does not meet any agent justification criterion (C1-C7).
It should be a skill, not an agent — dispatching to skill-forge.
Invoke `/skill-forge` to build a context-injected skill instead.
```

Do NOT proceed to Agent Creation Workflow if no criterion holds.

## Placement Gate

After C1-C7 justify an agent, classify source ownership and plane using
`standards/agentic-primitives/primitive-placement.md` before scaffolding:

| Question | Agent-forge rule |
|----------|------------------|
| Steward marketplace? | Use `library-platform` for platform self-description agents. Use `cognovis-core` or `sussdorff-core` only for reusable dev-plane agents. Use `repo-local` for product path/ADR overlays. |
| Dev-plane or product-plane? | Product runtime agents are product features, not Library agents. Refuse Library scaffolding and redirect to a product repo bead. |
| Product counterpart? | If a dev-plane agent supports Mira, Polaris, or another runtime artifact, record `repo`, `path`, `name`, `primitive_type`, and `notes` in catalog metadata. Put bead or ADR references in `notes`. |
| Repo-local escape hatch? | Keep agents local when prompts name product paths, private ADRs, local credentials, or one repo's topology. |
| Deterministic script route? | Move collection, parsing, polling, export, or validation logic into Python scripts; use `script-forge` if reusable or pack-exported. |
| Gas City projection? | `polecat`/`crew` is metadata after agent justification and placement; it never justifies creating an agent by itself. |

Product-plane refusal message:

```
This is a product-plane runtime agent, not a Library agent.
Create or reference a product repository bead for the runtime artifact. A
dev-plane Library agent may reference it with metadata.library.product_counterpart,
but the product artifact stays in the product repo.
```

## Judge Agent Path

Use the judge template when C7 holds. A judge agent evaluates an Action Proposal
before a side-effecting actor executes the proposed action.

Required contract:
- Input: `standard://judge-layer/proposals/action-proposal.v1`
- Output: `judge-outcomes.md` fields: `decision`, `reason`,
  `reason_category`, `provenance_refs`, plus conditional `constraints`,
  `revised_proposal`, or `escalation_target`
- Frontmatter: narrow read-only tools, `requires_standards: [judge-layer]`
- Evidence discipline: non-ALLOW outcomes name the failed evidence,
  authorization, policy, or scope boundary

Do not use the judge template for normal validation, post-action review, or
generic critique. The judge path is only for pre-action authorization decisions.
See `references/judge-pattern.md` for failure modes and specialization guidance.

## Agent Creation Workflow

### Step 1: Confirm Agent is Appropriate

Verify against the decision criteria above. If skill or command fits better, say so and stop.

### Step 2: Design Purpose and Scope

Define before writing any code:
- Single, focused purpose (one clear goal)
- Trigger keywords for auto-delegation
- Minimal required tools
- Appropriate model for complexity level
- Standalone or part of a pipeline?
- Steward marketplace, plane, repo-local escape decision, and product counterpart
- Gas City session class if packable: `polecat` for one-shot work, `crew` for
  persistent coordination/interactive sessions, or `none` if not exported as an agent
- Provider-neutral core prompt? Keep Claude/Codex-specific details in harness adapters
  or Gas City provider/agent config, not in the reusable prompt body.

Patterns: single-purpose, pipeline stage, orchestrator, meta-agent.
Single responsibility keeps agents composable and token-efficient.

Details and real-world examples: `references/agent-patterns.md`

### Step 3: Initialize Agent File

```bash
# Creates <name>.md unified agent source with YAML frontmatter
python3 scripts/init-agent.py <agent-name>
```

For a judge agent:

```bash
python3 scripts/init-agent.py <agent-name> --template judge
```

Creates a single `.md` source file with YAML frontmatter and system prompt.
The Library builder emits harness-native Claude `.md` and Codex `.toml`
artifacts from that source at install time.

```
agents/<agent-name>.md    # Unified source; build-agent.py emits harness artifacts
```

### Step 4: Configure Frontmatter

```yaml
---
name: kebab-case-name              # Required
description: |                     # Required (critical for auto-delegation!)
  Describe when and why to use this agent.
  Use PROACTIVELY when [trigger scenario].
model:
  tier: standard                  # economy|standard|premium|frontier
  reasoning: medium               # low|medium|high|max
  context: large                  # small|medium|large
  cost_priority: balanced         # cheapest|balanced|quality-first
capabilities:                    # Closed vocabulary from capabilities.yaml
  - read_files
agent_base_extends: cognovis-base # Layer 1 logical alias
codex:                            # Optional Codex overrides
  nickname_candidates:
    - kebab-case-name
---
```

**All supported frontmatter fields:**

| Field | Type | Required | Default | Description |
|-------|------|----------|---------|-------------|
| `name` | string | Yes | — | Kebab-case identifier |
| `description` | string | Yes | — | When to delegate (critical for auto-delegation) |
| `capabilities` | list | No | — | Closed capability names projected to harness-native bindings |
| `tools` | list | No | all | Legacy Claude tool list; prefer capabilities for new agents |
| `disallowedTools` | list | No | — | Tools to deny from inherited set |
| `model` | string or object | No | inherit | Requirement block resolved through `models.yaml`, or legacy alias/full model ID |
| `permissionMode` | string | No | default | `default`, `acceptEdits`, `dontAsk`, `bypassPermissions`, `plan` |
| `mcpServers` | list | No | — | MCP servers (inline or string references) |
| `hooks` | object | No | — | PreToolUse, PostToolUse, Stop hooks |
| `skills` | list | No | — | Skill names to preload |
| `memory` | string | No | — | `user`, `project`, or `local` |
| `maxTurns` | integer | No | — | Auto-stop after N turns |
| `color` | string | No | — | Visual identifier in CLI |
| `agent_base_extends` | string | No | `cognovis-base` | Layer 1 base for Library composition |
| `model_standards` | list | No | auto | Layer 3 model overlays; builder auto-loads resolved model ID |
| `codex` | object | No | — | Codex-only overrides emitted into TOML |

**Harness-specific body blocks:**

```markdown
Shared instructions appear outside directive blocks.

::: harness claude :::
Claude-only instructions.
::: end :::

::: harness codex :::
Codex-only instructions.
::: end :::
```

Malformed, nested, or unclosed directive blocks fail `scripts/build-agent.py`.

**Model selection:**
- Prefer requirement blocks. The builder resolves the cheapest model per harness
  that satisfies `tier`, `reasoning`, and `context`.
- Use `cost_priority: cheapest`, `balanced`, or `quality-first`.
- Escape hatch per harness when required: `claude-code: claude-opus-4-7` or
  `codex: { tier: premium, reasoning: high }`.

**Important:** `model` defaults to `inherit`, not `opus`. An agent without `model:` gets whatever model the caller uses. Always set model explicitly to avoid surprises in pipelines.

**Capability patterns:**
- Read-only: `read_files`
- Implementation: `read_files`, `edit_files`, `run_shell`
- Research: `read_files`, `search_web`
- SearXNG-only research: `search_searxng`, `use_skills`
- Orchestration: `spawn_subagents`, `manage_beads`

Minimal capabilities reduce attack surface and keep the agent focused.

Full field documentation: `references/agent-frontmatter-reference.md`

## Fleet Migration Mode

Use this mode when updating existing marketplace agents after builder or
frontmatter changes. Migration is mechanical, but every file still needs a
semantic access review.

For each existing agent:

1. Read the current frontmatter and identify the actual tool intent.
2. Replace Claude-specific `tools:` with `capabilities:` from `capabilities.yaml`.
   Add a capability only when no existing vocabulary entry expresses the intent.
3. Replace scalar model aliases (`haiku`, `sonnet`, `opus`) with a requirement
   block using `tier`, `reasoning`, `context`, and `cost_priority`.
4. Remove manual `model_standards:` when the builder can auto-load the resolved
   model ID. Keep it only as an explicit escape hatch and document why.
5. Keep harness override blocks only for true harness differences such as
   descriptions, nicknames, or explicitly approved model/sandbox exceptions.
6. Build both targets with `scripts/build-agent.py --harness all` and inspect the
   emitted Claude frontmatter plus Codex TOML.
7. Grep body prose for stale harness claims introduced by older runtime limits.
   Correct factual drift during the migration.

Validator policy:

- `tools:` without `capabilities:` is legacy. The validator warns by default and
  fails in `--strict` mode.
- Scalar `model:` with manual `model_standards:` is legacy for migrated
  marketplace agents. Prefer model requirements plus automatic Layer 3 loading.

### Step 5: Write System Prompt

```markdown
# Purpose
[One clear sentence defining role and expertise]

## Instructions
1. [First concrete action]
2. [Second concrete action]

## Output Format
[Define expected response structure]
```

**Guidelines:**
- Keep lean (<3k tokens ideal, <10k max)
- Imperative form ("Analyze the code" not "You should analyze")
- Specific and concrete (avoid vague language)
- Define output format explicitly
- Include decision criteria for judgment calls
- Include a `## Tool Usage` section with WHEN/HOW per tool to reduce hallucinated tool choice
- Do not embed deterministic shell/Python workflows in the prompt when bundled Python
  scripts can do the work predictably. If the helper is reusable or pack-exported,
  dispatch to `script-forge`.
- For helper outputs with multiple fields or actionable failures, use the execution-result contract in `references/execution-result-contract.md`

Token efficiency keeps agents composable -- lightweight agents combine better in pipelines.

Comprehensive writing guide: `references/agent-best-practices.md`

### Step 6: Validate

```bash
python3 scripts/validate-agent.py <agent-path>
```

Checks: frontmatter structure, required fields, name format, description quality, tool validity, model selection, token count, TODO markers.
Also warns about extractable executable code or inline shell/Python pipeline logic embedded in the prompt.

### Step 7: Test

**Auto-delegation:** Try phrases that should trigger the agent. If it fails, improve description with more trigger keywords.

**Functional:** Verify tools are sufficient, model is appropriate, output matches expected format, context is properly isolated.

### Step 8: Deploy

**Storage locations:** See your harness adapter for the exact paths and priority order.
In general, agents can be stored at project-level (highest priority), user-level (personal use),
and plugin-level. Consult your harness documentation for the exact directory names.

Document usage examples, expected inputs, and when to use vs other agents.

### Step 9: Library Packability Metadata

When the agent should be installable through Library or exported into Gas City,
print a `library.yaml` snippet with `metadata.library.gascity`.

```yaml
- name: <agent-name>
  description: >-
    <agent description>
  source: https://github.com/cognovis/library-core/blob/main/agents/<agent-name>.md
  metadata:
    library:
      plane: dev
      product_counterpart:
        repo: <product-repo>
        path: <product-path>
        name: <product-feature-or-agent>
        primitive_type: agent
        notes: <why this dev-plane agent supports the product surface>
      gascity:
        exportable: <true|false>
        projections:
          - target: agent
            pack: <cognovis-base|cognovis-wave|cognovis-specs|...>
            scope: <city|rig|provider|global>
            session_class: <polecat|crew>
            provider_neutral: true
            requires:
              binaries: [bd]
              env: []
              standards: []
```

Rules:
- `polecat` means bounded one-shot work: bead workers, reviewers, verifiers,
  validators, doc updaters.
- `crew` means persistent named session: mayor, wave lead, spec lead, release lead.
- Provider defaults belong in Gas City `agent.toml`/provider config or harness
  adapters, not in the provider-neutral core prompt.
- Bundled deterministic helpers must be Python scripts and declared in `scripts:`.
- Omit `product_counterpart:` when there is no paired product-plane artifact.
  Legacy `gascity.target`, `gascity.pack`, and `gascity.scope` may remain on
  existing catalog entries, but new snippets should use `gascity.projections[]`.

**After deployment:** Immediately run the Agent Review Workflow on the newly created agent
to catch issues before the agent is used in production.

## Agent Review Workflow

Use this when asked to review, audit, or improve an existing agent.

### Step 1: Load and Analyze

Read the agent `.md` file. Check:
- Is the YAML frontmatter well-formed?
- Does the description contain specific trigger keywords?
- Are tools minimal for the agent's purpose?
- Is the model appropriate for task complexity?

### Step 2: Run Validation

```bash
python3 scripts/validate-agent.py <agent-path>
```

Review errors and warnings. Fix errors first, then address warnings.

### Step 3: Assess Prompt Quality

Evaluate the system prompt against these criteria:
- **Clarity**: Are instructions specific and actionable?
- **Token efficiency**: Is the prompt lean or bloated?
- **Output format**: Is the expected output clearly defined?
- **Scope boundaries**: Does the agent know what it owns and doesn't own?
- **Edge cases**: Are decision criteria provided for ambiguous situations?

### Step 4: Check Auto-Delegation

Test whether the agent's description matches realistic user phrases. If the agent should auto-trigger but doesn't, the description needs more trigger keywords. If it triggers incorrectly, the description is too broad.

### Step 5: Report Findings

Structure findings as:
- **Errors** (must fix): broken metadata, missing required fields, security issues
- **Improvements** (should fix): weak description, excessive tools, wrong model tier
- **Suggestions** (nice to have): prompt restructuring, better output format

## Example: Gate Refusal

**Request:** "Create an agent that greps for a symbol and returns the file path."

**C-criterion check:**
- C1: No — no different tool permission needed; parent can Grep directly.
- C2: No — a single grep is not 2k+ tokens of work; it does not pollute the parent context.
- C3: No — no parallelism involved.
- C4: No — no information barrier required.
- C5: No — no model difference needed.
- C6: No — a single lookup is not multi-phase orchestration.
- C7: No — no pre-action side-effect gate is involved.

**Result:** No criterion holds. Output:

```
This request does not meet any agent justification criterion (C1-C7).
It should be a skill, not an agent — dispatching to skill-forge.
Invoke `/skill-forge` to build a context-injected skill instead.
```

The agent is not created. The user is directed to `/skill-forge`.

## Do NOT

- Create agents for tasks a skill or command handles better.
  Agents have context isolation overhead -- unnecessary for simple knowledge injection or user shortcuts.
- Grant more tools than minimally required.
  Excess tools expand attack surface and dilute agent focus.
- Write system prompts over 10k tokens.
  Attention dilution causes the agent to ignore instructions.
- Encode deterministic workflows as prompt-local shell/Python programs.
  Extract them into bundled scripts and return machine-readable results instead.
- Skip the validation step before deploying.
  Malformed frontmatter silently breaks auto-delegation.
- Omit the `model` field assuming it defaults to opus — it defaults to `inherit`.
  Always set model explicitly. In pipelines, an inherited model may not be what you expect.
- Default to haiku to save costs before verifying the agent works correctly.
  Premature downgrade causes subtle quality issues.

## Resources

### references/
| File | Content |
|------|---------|
| `agent-vs-skill-vs-command.md` | Decision tree, comparison table, hybrid patterns |
| `agent-frontmatter-reference.md` | All frontmatter fields, valid values, examples |
| `agent-best-practices.md` | Token efficiency, model economics, multi-agent patterns |
| `execution-result-contract.md` | Script-first workflow rule and canonical JSON envelope |
| `agent-patterns.md` | Complete agent files: single-purpose, pipelines, orchestrators |
| `judge-pattern.md` | Judge-agent contract, failure modes, and specialization guidance |
| `troubleshooting.md` | Auto-delegation failures, tool issues, prompt sizing |

### scripts/
| Script | Purpose |
|--------|---------|
| `init-agent.py` | Initialize new agent with validated template |
| `validate-agent.py` | Check structure, frontmatter, token count |

### assets/
| File | Purpose |
|------|---------|
| `agent-template.md` | Starter template for manual creation |
| `judge-template.md` | Starter template for pre-action judge agents |
