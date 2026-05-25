---
name: primitive-placement
description: Placement rubric for Library primitives, product counterparts, repo-local overlays, deterministic scripts, and Gas City projections.
tags:
  - origin:original
  - tier:core
  - category:standard
---

# Primitive Placement

> Scope: Placement guidance for forge skills that already use
> `agentic-primitives` to choose primitive type. This page classifies where a
> primitive belongs before scaffolding: platform source, marketplace source,
> repo-local overlay, product-plane feature, Gas City projection, or
> deterministic script.

ADR-0005 in `docs/adr/library-plane-vocabulary.md` is the vocabulary anchor:
library-platform is the dev-plane catalog and compiler, marketplaces are
stewarded primitive sources, Gas City PackV2 is a runtime projection target,
and product-plane runtime agents are product features rather than Library
primitives.

## Placement Record

Every forge should be able to name these fields before writing files:

| Field | Values | Meaning |
|-------|--------|---------|
| Steward marketplace | `library-platform`, `cognovis-core`, `sussdorff-core`, third-party source, or `repo-local` | Source owner for a reusable dev-plane primitive. |
| Plane | catalog value `dev`, or product-plane refusal | Library catalog entries are dev-plane primitives; product-plane artifacts are redirected to product repos. |
| Product counterpart | `none` or `repo + path/name/primitive_type/notes` | Paired product work supported by a dev primitive. |
| Repo-local escape | `none` or path plus ADR-heavy rationale | Reason a primitive remains inside a product repo overlay. |
| Gas City projection | `none`, `overlay`, `asset`, `command`, `doctor`, `formula`, `agent`, or `script` | PackV2 output shape, not source ownership. |
| Operational city | `global`, `city`, `rig`, or `provider` | Runtime scope where a projection is consumed. |
| Deterministic script | `none`, `bundled`, or `first-class` | Repeatable Python logic that should not live in prompt prose. |

Catalog metadata belongs under `metadata.library.*`; source files stay
portable. Use `metadata.library.product_counterpart` for references to
product-plane work. Migration-plan city names such as `cognovis-healthcare`
and `cognovis-agentics` belong in projection targets, pack names, or notes as
described by ADR-0005 and the migration plan, not in `scope`.

## Platform Boundary

Use `library-platform` for primitives that describe or operate the Library
platform itself: catalog schema, installers, launchers, primitive contracts,
forge skills, and standards required by those forges.

Use `cognovis-core` for reusable Cognovis team developer content that is not a
platform self-description. Use `sussdorff-core` for personal developer content.
Use `repo-local` when the artifact depends on one project's topology, private
ADRs, local credentials, or product paths.

## Plane Boundary

| Request | Classification | Forge response |
|---------|----------------|----------------|
| Create a Claude/Codex helper that developers use while editing Mira | Dev-plane Library primitive or repo-local overlay | Continue if primitive type is correct. |
| Create an agent that runs inside Mira for end users | Product-plane feature | Refuse Library primitive creation; create or reference a product repo bead instead. |
| Expose this dev helper through Gas City PackV2 | Dev-plane source with runtime projection | Keep source in Library; add catalog projection metadata. |
| Generate code that ships in Polaris runtime | Product-plane artifact | Keep in Polaris; Library may only reference a counterpart. |

Product-plane refusal is not a rejection of the product work. It is a source of
truth correction: product runtime behavior belongs in the product repository,
with Library primitives optionally supporting implementation, review, or
export.

## Forbidden Patterns

- Do not place product runtime source code, service orchestration, or end-user
  product behavior in Library primitive files.
- Do not embed secrets, credentials, tokens, tenant identifiers, or local
  provider auth material in packs, standards, skills, scripts, hooks, or agents.
- Do not make provider-specific authentication the source contract for a
  reusable primitive. Keep auth in product/runtime configuration and document
  required environment variables only as requirements.
- Do not add untyped placement metadata such as `steward_marketplace`,
  `product_counterpart.bead`, or `plane: dev-plane` to `library.yaml`; use the
  ADR-0005 schema fields under `metadata.library.*`.

## Repo-Local Escape Hatch

Keep a primitive repo-local when its value depends on concrete product paths,
private ADRs, local credentials, local hook wiring, or a single repo's topology.
Typical homes are `.claude/`, `.agents/`, `skills/`, `agents/`, or repo-local
standards folders.

Promotion to a stewarded source requires at least one of these signals:

- A second repo can consume the same behavior with only named placeholders.
- The product-specific parts can be moved to parameters, config, or references.
- The reusable part is a standard, skill, hook, agent, or Python script with a
  product counterpart reference instead of embedded product code.

## Naming

Skills should read like verbs or reusable developer capabilities:
`audit-citations`, `skill-forge`, `sync-standards`. Product
features should read like product nouns or services: eligibility workflow, sync
service, billing assistant, patient intake agent. A noun-like runtime feature
name is a product-plane signal unless the artifact is only a developer harness
helper.

## Deterministic Script Routing

Repeatable parsing, scanning, validation, export, and transformation logic over
roughly 50 lines belongs in Python script form. Use `script-forge` when the
script is reusable across primitives or can project into a Gas City command,
doctor, formula, or asset. Keep it bundled only when one owning primitive is
the sole realistic consumer.

## Examples

| Candidate | Placement | Rationale |
|-----------|-----------|-----------|
| `skill-forge` in library-platform | Dev-plane skill, steward `library-platform` | It authors developer primitives and carries no product runtime state. |
| Mira `.agents/skills/mira-aidbox` | Repo-local dev-plane overlay | Depends on Mira paths, Polaris-owned Aidbox setup, and local deployment assumptions. Keep generalized FHIR/Aidbox facts in the Samurai marketplace skills. |
| Mira `.claude/agents/aidbox-fhir` | Repo-local dev-plane overlay | Depends on Mira paths, Aidbox setup, and local workflow assumptions. Promote only generalized FHIR guidance. |
| Mira runtime billing or patient agent | Product-plane feature | Create a Mira bead and implementation artifact; Library may host reviewer skills or standards that support it. |
| FHIR terminology package validator | First-class Python script plus healthcare/FHIR standard | Deterministic checks can project to Gas City `doctor`; factual FHIR rules stay in standards. |
| Gitleaks or destructive-command enforcement | Hook plus reusable Python script if shared | Non-bypassable lifecycle control is a hook; shared detection logic is a script. |

## Product Counterpart Metadata

Use product counterpart metadata only as a pointer, not as source ownership:

```yaml
metadata:
  library:
    plane: dev
    product_counterpart:
      repo: mira
      path: packages/runtime-agents/billing
      name: billing-assistant
      primitive_type: agent
      notes: "Paired Mira bead: MIRA-123."
    gascity:
      exportable: true
      projections:
        - target: overlay
          pack: cognovis-healthcare
          scope: rig
          session_class: none
          provider_neutral: true
```

If the requested artifact itself is under `product_counterpart.path`, it is not
a Library primitive. The forge should redirect to product work and stop
scaffolding inside Library sources.
