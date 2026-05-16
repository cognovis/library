# Agent Troubleshooting Guide

## Agent Never Auto-Delegates

**Problem:** Agent never triggers automatically.

**Solutions:**
- Improve description with specific trigger keywords
- Add phrases users might say
- Include "Use PROACTIVELY when..." or "MUST BE USED for..."
- Test with typical user requests

**Root cause:** Auto-delegation matches user input against agent descriptions. Vague descriptions = no matches.

---

## Agent Lacks Necessary Tools

**Problem:** Agent can't perform required operations.

**Solutions:**
- Add the smallest needed entries to `capabilities:`
- Use names registered in `capabilities.yaml`
- If no registered capability fits, add one with Claude and Codex bindings
- Use raw `tools:` only for Claude-only repo-local escape hatches

---

## System Prompt Too Large

**Problem:** Validator warns about token count.

**Solutions:**
- Move detailed docs to references/ (loaded as needed)
- Use numbered lists instead of verbose explanations
- Remove repetitive examples
- Split into multiple specialized agents
- Target <3k tokens for best performance

WHY: Large prompts dilute attention -- the agent ignores instructions buried in walls of text.

---

## Agent Uses Wrong Model

**Problem:** Task too slow or too expensive.

**Solutions:**
- Haiku: Routine, fast, deterministic (test running, formatting)
- Sonnet: Balanced, most tasks (default)
- Opus: Complex reasoning only (architecture, security audit)
- Check if Haiku sufficient (90% quality, 3x cheaper)

---

## Agent Output Format Inconsistent

**Problem:** Agent produces different output structures each time.

**Solutions:**
- Define explicit output format in system prompt
- Add a reference example in the prompt
- Use XML tags to structure output sections
- Keep output instructions at the end of the prompt (recency bias)

---

## Pipeline Handoff Failures

**Problem:** Multi-agent pipeline loses context between stages.

**Solutions:**
- Define clear artifact format between stages
- Use slug-based artifact linking
- Ensure each stage writes output the next stage expects
- Add validation at each handoff point
