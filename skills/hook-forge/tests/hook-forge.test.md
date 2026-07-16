# Test Fixture: hook-forge

## Test 1 — High-frequency capture hook

**Input:** "Create a PostToolUse hook that records every tool input as JSON. Can it import a third-party logging package?"
**Expected behavior:** The guidance prefers a standard-library entrypoint, uses `json.dumps` for arbitrary tool input, exits 0 on errors, and requires a measured reason before adding third-party startup cost.
**Pass criteria:** The response does not turn dependency-free guidance into an absolute ban, and keeps the complete hook below the latency budget.

## Test 2 — Scoped formatter hook

**Input:** "Run the project's formatter after writes to Python files."
**Expected behavior:** The guidance permits a scoped external formatter, isolates required Python dependencies with UV where appropriate, and measures the complete hook.
**Pass criteria:** The response does not incorrectly require pure standard-library implementation for the formatter itself.
