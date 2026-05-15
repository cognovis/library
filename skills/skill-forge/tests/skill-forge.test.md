# Test Fixture: skill-forge

## Test 1 — Happy path (create mode)

**Input:** "Create a new skill called hello-world that greets the user"
**Expected behavior:**
- Asks for or confirms skill name (`hello-world`), description, and purpose
- Runs inverse primitive check — all agent/hook/script dispatch criteria are NO
- Name passes validation (lowercase, no hyphens at boundaries, ≤64 chars)
- Description is within 1024-char limit
- Scaffolds `skills/hello-world/SKILL.md` with correct frontmatter
  (`requires_standards: [english-only, no-emoji]`, `compatibility: {}`, `metadata: {}`)
- No scripts/ stub (logic < 50 lines)
- Creates `skills/hello-world/tests/hello-world.test.md`
- Prints library.yaml snippet
- Runs `validate-skill.py skills/hello-world/ --strict` and exits 0
**Pass criteria:** SKILL.md created, validate exits 0, library snippet printed

## Test 2 — Name validation failure

**Input:** Skill name `Hello_World` (uppercase + underscore)
**Expected behavior:** Error "Name must match [a-z][a-z0-9-]+ — no uppercase, underscores,
or leading/trailing hyphens". Prompts for a valid name.
**Pass criteria:** No SKILL.md created; error shown; prompt re-issued

## Test 3 — C1 dispatch (agent-forge redirect)

**Input:** "Create a skill that has read-only tool access to verify implementations"
**Expected behavior:** Primitive gate detects C1 (different tool permissions) + C4
(info-barrier). Prints dispatch message recommending `agent-forge`. Stops — no SKILL.md
created.
**Pass criteria:** No files written; dispatch message references C1/C4; agent-forge named

## Test 4 — validate mode

**Input:** "Validate skill session-close"
**Expected behavior:** Runs `validate-skill.py skills/session-close/ --strict`, reports
findings or "No findings".
**Pass criteria:** Command runs; output is findings or clean confirmation

## Test 5 — audit-fleet mode

**Input:** "Audit all skills" / "skill health check"
**Expected behavior:** Runs the bundled `scan-skills.sh` and
`scan-codex-compat.py` checks.
**Pass criteria:** Scanner output is summarized into a fleet report

## Test 6 — Description hard-limit

**Input:** Skill description of 1100 chars (over 1024-char limit)
**Expected behavior:** Error "Description exceeds 1024-char Codex CLI hard limit (1100 chars).
Shorten to ≤1024 chars." Prompts for shorter description.
**Pass criteria:** No SKILL.md written; char count shown; prompt re-issued

## Test 7 — Script scaffold triggered

**Input:** "Create a skill that scans all YAML files and counts top-level keys —
the scanner itself is about 80 lines of Python"
**Expected behavior:**
- Primitive gate passes (no C-criterion)
- Detects logic > 50 lines estimate
- Proposes `scripts/yaml-key-counter.py` with JSON output contract
- Asks user to confirm or choose bare-value contract
- Creates stub script file
- References script in SKILL.md Resources section
**Pass criteria:** scripts/ stub exists; SKILL.md Resources section lists it; validate exits 0

## Test 8 — Side-effect skill requires action_boundary

**Input:** "Create a skill that sends an email to a customer after drafting the message"
**Expected behavior:**
- Primitive gate passes unless the user asks for a judge agent itself
- Action Boundary Gate detects a side effect beyond read-only or draft-only work
- Requires `action_boundary.risk_class: external-side-effect`
- Requires `action_boundary.effect_type: messaging`
- Requires `proposal_schema: standard://judge-layer/proposals/action-proposal.v1`
- Requires `judge: agent://judge-default`
- Requires `requires_mandate: true`
- Does not emit the obsolete `class:` key
**Pass criteria:** Generated SKILL.md contains action_boundary with current fields; validator exits 0

## Test 9 — Specialist proposal_schema allowed

**Input:** Validate a side-effect skill with
`proposal_schema: standard://payments/proposals/payment-proposal.v1`
**Expected behavior:**
- Validator accepts the specialist standard proposal URI shape
- Validator still rejects non-`standard://.../proposals/...vN` values
**Pass criteria:** Specialist proposal fixture exits 0 under `--strict`

## Test 10 — Invalid YAML frontmatter rejected

**Input:** Validate a skill with `argument-hint: [subcommand] [args]`
**Expected behavior:**
- Validator exits 2 before body checks
- Error says the SKILL.md frontmatter is invalid YAML
- Quoting the value as `argument-hint: "[subcommand] [args]"` passes
**Pass criteria:** Regression fixture in `tests/test_skill_forge_validator.py` passes
