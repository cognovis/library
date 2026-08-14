# CL-l022 Global Receipt Disposition

> Historical record: the 106-receipt inventory below was frozen on 2026-08-13.
> It is not the current deletion candidate set. The refreshed 103-receipt
> inventory and its guarded cutover boundary are maintained in
> `CL-31po-recovery-status.md`.

## Decision

This report freezes the disposition of the 106 receipts in the historical
user-global Library lock inspected on 2026-08-13. The input lock SHA-256 was
`ffc8e31819cfcd651b8ff9ba66270c51f18102a230aa45cafb68401897e75858`.

No catalog entry, Skill source, or marketplace content is removed. The catalog
continues to publish all 109 pre-existing Skills plus the new `library` Skill.
The word `remove` below means only removal of a Library-owned user-global
projection and its recorded harness bridges after all listed gates pass.

## Gates for Skill projection removal

The 28 Skill receipts are classified `remove-projection-after-backup`, but this
classification is not immediate deletion authority. Removal may occur only when:

1. the platform and Fleet feature branches are integrated into their target
   branches and the pinned project locks resolve from those published commits;
2. the final Executive Pack review returns ALLOW;
3. every target and recorded bridge is copied into a recoverable, checksummed
   backup together with the pre-change global lock;
4. the target is still owned by the matching Library receipt and has not drifted
   or been adopted since this report was generated; and
5. a post-change audit proves zero global Skill receipts while all 110 catalog
   Skill names remain present.

If any ownership or drift check fails, retain the projection and record it as a
manual follow-up. Never infer permission to remove a catalog source from a
projection disposition.

## Exact dispositions

### Skills: remove projection after backup (28)

| Receipt | Install target |
| --- | --- |
| `skill:worktree-cleanup` | `~/.agents/skills/worktree-cleanup/` |
| `skill:cognovis-beads` | `~/.agents/skills/cognovis-beads/` |
| `skill:cmux-workspace` | `~/.agents/skills/cmux-workspace/` |
| `skill:intake` | `~/.agents/skills/intake/` |
| `skill:inject-standards` | `~/.agents/skills/inject-standards/` |
| `skill:workplan` | `~/.agents/skills/workplan/` |
| `skill:session-close` | `~/.agents/skills/session-close/` |
| `skill:bead-implementation-loop` | `~/.agents/skills/bead-implementation-loop/` |
| `skill:compound` | `~/.agents/skills/compound/` |
| `skill:acpx-dispatch` | `~/.agents/skills/acpx-dispatch/` |
| `skill:bead-execution-loop` | `~/.agents/skills/bead-execution-loop/` |
| `skill:cmux` | `~/.agents/skills/cmux/` |
| `skill:cmux-bead-dispatch` | `~/.agents/skills/cmux-bead-dispatch/` |
| `skill:parallelize` | `~/.agents/skills/parallelize/` |
| `skill:council` | `~/.agents/skills/council/` |
| `skill:bug-triage` | `~/.agents/skills/bug-triage/` |
| `skill:bead-reviewer` | `~/.agents/skills/bead-reviewer/` |
| `skill:library` | `~/.agents/skills/library` |
| `skill:skill-forge` | `~/.agents/skills/skill-forge/` |
| `skill:agent-forge` | `~/.agents/skills/agent-forge/` |
| `skill:standard-forge` | `~/.agents/skills/standard-forge/` |
| `skill:script-forge` | `~/.agents/skills/script-forge/` |
| `skill:hook-forge` | `~/.agents/skills/hook-forge/` |
| `skill:context-handoff` | `~/.agents/skills/context-handoff/` |
| `skill:executive-pack` | `~/.agents/skills/executive-pack/` |
| `skill:fhir-ig-development` | `~/.agents/skills/fhir-ig-development/` |
| `skill:fhir-emission` | `~/.agents/skills/fhir-emission/` |
| `skill:aidbox-ig-development` | `~/.agents/skills/aidbox-ig-development/` |

The six adopted Skill receipts (`library`, `skill-forge`, `agent-forge`,
`standard-forge`, `script-forge`, and `hook-forge`) require the same ownership
gate; adopted status is never treated as blanket deletion authority.

### Bootstrap retain (1)

| Receipt | Install target | Rationale |
| --- | --- | --- |
| `mcp:open-brain` | `claude_code,codex,opencode` | Enumerated global Bootstrap singleton under ADR-0012. |

### Deferred retain (77)

Every non-Skill receipt other than `mcp:open-brain` remains global and outside
CL-l022 removal scope:

| Type | Count | Disposition |
| --- | ---: | --- |
| Agent | 27 | Retain pending CL-b3db or a separate evidence-backed decision. |
| Standard | 31 | Retain pending CL-b3db or a separate evidence-backed decision. |
| Script | 8 | Retain pending an explicit executable/bootstrap ownership decision. |
| Model standard | 5 | Retain pending a separate projection decision. |
| Prompt | 1 | Retain pending a separate projection decision. |
| Runtime config | 3 | Retain; Bootstrap ownership is resolved separately. |
| MCP (`markitdown`, `lsp`) | 2 | Retain until an exact replacement or archive decision exists. |

This totals 106 receipts: 28 conditional Skill projection removals, one
Bootstrap retain, and 77 deferred retains.

## Rollback boundary

Rollback restores the backed-up targets and bridges byte-for-byte and restores
the pre-change global lock atomically. The backup must remain outside catalog
working trees and must not be deleted until the replacement has survived the
final audit. Catalog repositories are never part of this rollback because their
Skill sources are not mutated.
