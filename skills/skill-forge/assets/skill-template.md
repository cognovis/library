---
name: <name>
description: >-
  use when: <concrete trigger pattern this routes for>
  NOT for: <adjacent concern this is wrong for>
  boundary: <how this differs from neighboring skills>
requires_standards: [english-only, no-emoji]
compatibility: {}
metadata: {}
# Include only when Action Boundary Gate classifies the skill as side-effecting:
# action_boundary:
#   risk_class: external-side-effect
#   effect_type: messaging
#   proposal_schema: standard://judge-layer/proposals/action-proposal.v1
#   judge: agent://judge-default
#   requires_mandate: true
---

# <Title>

<One-line purpose statement.>

## Inputs

- <What the consumer must provide before invoking>

## Outputs

- <What this skill produces>

## Exclusions

- <What this skill explicitly will not do>

## Workflow

<Short imperative execution contract. Keep methodology in standards and
deterministic logic in bundled scripts.>

## Do NOT

- <Anti-pattern 1>
- <Anti-pattern 2>

## Resources

| File | Purpose |
|------|---------|
