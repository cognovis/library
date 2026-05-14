# Command

> Primitive reference extracted from [PRIMITIVES.md](../PRIMITIVES.md).

**Definition.** A prompt template that a *user* explicitly invokes via a `/name`
slash syntax. The model does not auto-pick commands; the user must type the command.

**Key constitutive feature.** User-only trigger: commands exist because the user
needs explicit control over when a workflow runs, not model discretion.

**Trigger semantics.** User types `/command-name [args]` in the chat interface. The
harness injects the command's template into the conversation. The model then executes
the workflow defined in the template.

**Cost.** Command templates are injected only on explicit invocation — no standing
context cost between invocations.

**Format (Claude Code).** `.claude/commands/<name>.md` with YAML frontmatter. NORMATIVE.

**Format (Codex).** Custom prompts/commands are not supported in Codex. Use skills
instead. NORMATIVE — per CL-qzw research.

**When to choose it.** Use a command when:
- The workflow requires deliberate, explicit user intent (e.g., a destructive operation).
- The workflow is parameterized by user-supplied arguments at invocation time.
- The capability would be confusing or dangerous if auto-triggered by the model.

**Counter-examples.**
- Do NOT use a command for something the model should recognize and apply automatically
  — that is a skill.
- Do NOT use a command in Codex — use a skill with explicit invocation
  guidance in its description.

**Worked examples.**

| Command | Why it is a command |
|---------|-------------------|
| `/compact-reference path/to/file.md` | User explicitly passes a file path. Auto-triggering this would be wrong — the user chooses which file to compact. |
| `/install-playwright` | Destructive system install; user must consciously invoke it. Model should not decide to install Playwright autonomously. |
| `/install-plugin` | Installation is a deliberate act; the user picks the plugin. Auto-triggering would violate user autonomy over system state. |

---
