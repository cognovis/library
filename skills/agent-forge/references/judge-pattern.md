# Judge Agent Pattern

A judge is an Agent specialization for pre-action authorization. It evaluates a
structured Action Proposal before a side-effecting actor runs the action, then
returns one of `ALLOW`, `BLOCK`, `REVISE`, or `ESCALATE`.

## When to Specialize

Use a judge agent when all are true:

- The actor proposes a side effect, not just a read-only analysis.
- The decision needs model reasoning over evidence, policy, authorization, or scope.
- The caller can supply an Action Proposal with enough structure to audit.
- A deterministic hook or orchestrator can call the judge before executing the action.

Keep the decision inside the ordinary worker when the action is read-only,
reversible local draft work, or already governed by deterministic checks. Use a
hook when the rule must fire unconditionally and can be expressed deterministically.

## Contract

Input contract:

- `proposal_schema: standard://judge-layer/proposals/action-proposal.v1`
- `risk_class`: `read-only`, `reversible-write`, `external-side-effect`, or `high-risk`
- `effect_type`: `filesystem`, `network`, `financial`, `messaging`, `credential`, or `other`
- `evidence_refs`: observed, inferred, generated, confirmed, disputed, or superseded provenance
- `authorization`: mandate reference or inline authorization evidence

Output contract:

- `decision` is exactly `ALLOW`, `BLOCK`, `REVISE`, or `ESCALATE`.
- `reason`, `reason_category`, and `provenance_refs` are always present.
- Non-ALLOW outcomes name the failed evidence, authorization, policy, or scope boundary in `reason` and `provenance_refs`.
- `ALLOW` may include a `constraints` object.
- `REVISE` includes a full replacement `revised_proposal`.
- `ESCALATE` includes an `escalation_target`.

## Failure Modes

| Failure mode | Risk | Countermeasure |
|--------------|------|----------------|
| Correlated judgment | The same model family generated the proposal and rubber-stamps it. | Require structured evidence refs and treat generated-only evidence as weak for side effects. |
| Specification gaming | The actor phrases the proposal to exploit broad policy language. | Judge against concrete fields: actor, target, risk class, scope, mandate, expected consequence, rollback path. |
| Escalation drift | Ambiguous cases slowly become ALLOW because escalation feels expensive. | Use `ESCALATE` whenever policy, evidence, or authorization cannot be resolved from the proposal. |
| Latency/cost | Calling a judge for every low-risk action slows the workflow. | Gate C7 to side effects and allow reversible local writes through lighter policy when documented. |
| Policy drift | Specialist judges diverge from the shared outcome or mandate contract. | Require `judge-layer` and keep local policy as additive scope rules, not replacement semantics. |

## Anti-Gaming Discipline

The proposal is a claim, not proof. A judge must verify whether each claim has
evidence and whether that evidence is strong enough for the declared risk class.
For external-side-effect and high-risk actions, generated-only evidence is
insufficient unless a valid mandate explicitly allows it.

## Specialist vs Default

Use `judge-default` for general pre-action gates. Create a specialist judge only
when a domain has additional factual policy or mandate rules, such as financial
limits, credential handling, regulated messaging, or product-specific scope.
Specialist judges still inherit the same proposal schema, outcome set, provenance
labels, and mandate rules.
