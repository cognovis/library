# Architecture decision index

| ADR | File | Status | Current relationship |
|---|---|---|---|
| 0001 | [sussdorff-plugins-removal.md](sussdorff-plugins-removal.md) | Superseded | Replaced by 0002 |
| 0002 | [canonical-library-architecture.md](canonical-library-architecture.md) | Accepted | Canonical sources and launcher ownership; amended by 0010 |
| 0003 | [three-layer-cache-architecture.md](three-layer-cache-architecture.md) | Accepted | Cache and deployment model; amended by 0010 and 0011 |
| 0004 | [frontmatter-dependency-resolution.md](frontmatter-dependency-resolution.md) | Accepted | Dependency and source layout; amended by 0010 |
| 0005 | [library-plane-vocabulary.md](library-plane-vocabulary.md) | Accepted | Catalog plane vocabulary; amended by 0010 |
| 0006 | [workflow-primitive.md](workflow-primitive.md) | Accepted | Workflow primitive; retained by 0011 |
| 0007 | [library-tool-surface-mcp.md](library-tool-surface-mcp.md) | Superseded | Private Library MCP implementation retired by CL-tbsz |
| 0008 | [intentional-release-lifecycle.md](intentional-release-lifecycle.md) | Superseded | Release lifecycle implementation retired by CL-tbsz |
| 0009 | [git-hook-chain-existing-composition.md](git-hook-chain-existing-composition.md) | Accepted | Existing git-hook chain composition contract |
| 0010 | [workspace-desired-state-reconciliation.md](workspace-desired-state-reconciliation.md) | Accepted | Universal ownership and Workspace desired state |
| 0011 | [heterogeneous-marketplace-workspaces.md](heterogeneous-marketplace-workspaces.md) | Accepted | Heterogeneous marketplace Workspaces |
| — | [library-yaml-information-model.md](library-yaml-information-model.md) | Accepted | Catalog section ownership; amended by 0010 |
| — | [per-harness-agent-base-files.md](per-harness-agent-base-files.md) | Accepted | Harness-specific base prompt files |

Accepted ADRs remain normative only where a later accepted ADR has not amended
them. Superseded ADRs are frozen historical records.
