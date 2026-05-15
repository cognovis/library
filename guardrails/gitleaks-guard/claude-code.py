#!/usr/bin/env python3
"""PreToolUse hook: block git push if gitleaks detects secrets.

Self-contained - no external dependencies beyond Python stdlib + gitleaks binary.
Works on macOS, Linux, and Windows.
"""

import json
import re
import subprocess
import sys


def main():
    try:
        input_data = json.load(sys.stdin)
    except (json.JSONDecodeError, ValueError):
        sys.exit(0)

    tool_name = input_data.get("tool_name", "")
    tool_input = input_data.get("tool_input", {})

    if tool_name != "Bash":
        sys.exit(0)

    command = tool_input.get("command", "")

    # Block commands that would print secret env vars to chat
    SECRET_PATTERNS = [
        r"GetEnvironmentVariable\s*\(\s*['\"].*(?:PASSWORD|SECRET|TOKEN|KEY|CREDENTIAL)",
        r"\becho\b.*\$\{?(?:DOLT_REMOTE_PASSWORD|STAFF_JWT_SECRET|AIDBOX_CLIENT_SECRET)",
        r"\bprintenv\b.*(?:PASSWORD|SECRET|TOKEN|KEY)",
        r"\bset\b\s*\|.*(?:PASSWORD|SECRET|TOKEN)",
    ]
    for pat in SECRET_PATTERNS:
        if re.search(pat, command, re.IGNORECASE):
            print("BLOCKED: command would expose secret env vars to chat", file=sys.stderr)
            sys.exit(2)

    # Only intercept git push commands
    if not re.search(r"\bgit\s+push\b", command):
        sys.exit(0)

    # Skip help
    if re.search(r"\bgit\s+push\s+--help\b", command):
        sys.exit(0)

    # Check if gitleaks is available. Missing scanner is a hard failure because
    # allowing a push would create false confidence in the guardrail.
    try:
        version_check = subprocess.run(
            ["gitleaks", "version"], capture_output=True, timeout=5
        )
        if version_check.returncode != 0:
            raise RuntimeError("gitleaks version check failed")
    except (FileNotFoundError, subprocess.TimeoutExpired):
        print(
            "BLOCKED: gitleaks is required for gitleaks-guard but is not installed",
            file=sys.stderr,
        )
        print("Install: brew install gitleaks (macOS) or scoop install gitleaks (Windows)", file=sys.stderr)
        sys.exit(2)
    except RuntimeError:
        print(
            "BLOCKED: gitleaks is required for gitleaks-guard but did not run successfully",
            file=sys.stderr,
        )
        sys.exit(2)

    # Resolve the repo root so all git/gitleaks commands run from the right directory
    try:
        repo_root = subprocess.run(
            ["git", "rev-parse", "--show-toplevel"],
            capture_output=True, text=True, timeout=5,
        ).stdout.strip() or None
    except Exception:
        repo_root = None

    # Get the commit hash being pushed (HEAD)
    try:
        head = subprocess.run(
            ["git", "log", "-1", "--format=%H"],
            capture_output=True, text=True, timeout=5,
            cwd=repo_root,
        ).stdout.strip()
    except Exception:
        head = "HEAD"

    # Run gitleaks scan only on commits not yet on remote (new work only).
    # Using `git log origin/main..HEAD` range avoids re-scanning historical commits.
    # Falls back to HEAD~1..HEAD if origin/main is not available.
    try:
        range_check = subprocess.run(
            ["git", "rev-parse", "--verify", "origin/main"],
            capture_output=True, timeout=5,
            cwd=repo_root,
        )
        log_range = "origin/main..HEAD" if range_check.returncode == 0 else f"{head}~1..{head}"
    except Exception:
        log_range = f"{head}~1..{head}"

    try:
        result = subprocess.run(
            ["gitleaks", "detect", "--log-opts", log_range, "--verbose", "--exit-code", "1"],
            capture_output=True,
            text=True,
            timeout=60,
            cwd=repo_root,
        )
        if result.returncode != 0:
            print(
                "BLOCKED: gitleaks detected secrets in the repository",
                file=sys.stderr,
            )
            print(result.stdout, file=sys.stderr)
            print(result.stderr, file=sys.stderr)
            print(
                "Fix: remove secrets, add to .gitleaksignore, or use allowlist",
                file=sys.stderr,
            )
            sys.exit(2)
    except subprocess.TimeoutExpired:
        print("BLOCKED: gitleaks scan timed out", file=sys.stderr)
        sys.exit(2)

    sys.exit(0)


if __name__ == "__main__":
    main()
