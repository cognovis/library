"""
workflow_runtime.py — Spike runtime for Anthropic Workflow JS specs.

This is a constrained proof-of-concept:
- it reads a workflow spec as source text
- enforces inert-spine bans
- extracts a small JSON-compatible meta block
- dispatches `agent()` leaves through pluggable executors
- journals leaf results by hash(prompt + opts)
"""

from __future__ import annotations

import abc
import hashlib
import json
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, ClassVar, Optional


class SpineConstraintError(ValueError):
    """Raised when the workflow spine uses a banned operation."""


class JournalSchemaError(ValueError):
    """Raised when a journal file has an incompatible schema."""


ADAPTER_PRESERVATION_STATUS: dict[str, str] = {
    "claude-agent": "blocked",
    "codex-impl": "separate-harness",
    "codex-exec": "separate-harness",
    "cursor-composer": "not-applicable",
}

_MUTATING_ALLOWED_STATUSES = frozenset({"verified"})


class MutatingExecutionBlockedError(ValueError):
    """Raised when mutating workflow execution is attempted for an unverified adapter."""


class SpineConstraintChecker:
    """Heuristic static analysis for inert-spine rules."""

    _BANNED_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
        ("filesystem require()", re.compile(r"\brequire\s*\(")),
        ("filesystem import fs", re.compile(r"\bimport\b[^;]*['\"]fs(?:/[^'\"]+)?['\"]")),
        (
            "filesystem import child_process",
            re.compile(r"\bimport\b[^;]*['\"]child_process(?:/[^'\"]+)?['\"]"),
        ),
        ("filesystem import net", re.compile(r"\bimport\b[^;]*['\"]net(?:/[^'\"]+)?['\"]")),
        ("shell exec", re.compile(r"\b(?:exec|spawn|system|popen)\s*\(")),
        ("network fetch", re.compile(r"\bfetch\s*\(")),
        ("network net module", re.compile(r"\bnet\.")),
        ("filesystem api", re.compile(r"\bfs\.")),
        ("Date.now", re.compile(r"\bDate\.now\s*\(")),
        ("Math.random", re.compile(r"\bMath\.random\s*\(")),
        ("new Date()", re.compile(r"\bnew\s+Date\s*\(\s*\)")),
    )

    def find_violations(self, source: str) -> list[str]:
        """Return a list of banned constructs detected in source."""
        violations: list[str] = []
        stripped = self._strip_comments(source)

        for label, pattern in self._BANNED_PATTERNS:
            if pattern.search(stripped):
                violations.append(label)

        return violations

    def validate(self, source: str) -> None:
        """Raise when the workflow spine is not inert."""
        violations = self.find_violations(source)
        if violations:
            raise SpineConstraintError(
                "Workflow spine is not inert: " + ", ".join(violations)
            )

    @staticmethod
    def _strip_comments(source: str) -> str:
        """Remove line and block comments while leaving strings untouched.

        Uses char-by-char state tracking to detect whether // or /* are inside
        string literals ('...', "...", or `...`). Only treats // and /* as
        comment starts when NOT inside a string.
        """
        result = []
        i = 0
        in_string = False
        string_delim = ""
        escape = False

        while i < len(source):
            char = source[i]

            # Handle escape sequences inside strings
            if in_string:
                result.append(char)
                if escape:
                    escape = False
                elif char == "\\":
                    escape = True
                elif char == string_delim:
                    in_string = False
                i += 1
                continue

            # Handle string starts (not in a string yet)
            if char in ('"', "'", "`"):
                in_string = True
                string_delim = char
                result.append(char)
                i += 1
                continue

            # Handle block comments (/* ... */)
            if i + 1 < len(source) and char == "/" and source[i + 1] == "*":
                # Skip until we find */
                i += 2
                while i + 1 < len(source):
                    if source[i] == "*" and source[i + 1] == "/":
                        i += 2
                        break
                    i += 1
                # Replace comment with space
                result.append(" ")
                continue

            # Handle line comments (// ...)
            if i + 1 < len(source) and char == "/" and source[i + 1] == "/":
                # Skip until end of line
                i += 2
                while i < len(source) and source[i] != "\n":
                    i += 1
                # Replace comment with space
                result.append(" ")
                # Keep the newline
                if i < len(source) and source[i] == "\n":
                    result.append("\n")
                    i += 1
                continue

            # Regular character
            result.append(char)
            i += 1

        return "".join(result)


class AgentExecutor(abc.ABC):
    """Interface for workflow leaf executors."""

    adapter_name: str

    @abc.abstractmethod
    def run(self, prompt: str, opts: dict[str, Any]) -> dict[str, Any]:
        """Execute a single agent leaf."""


class ClaudeAgentExecutor(AgentExecutor):
    """Spike executor for the `claude-agent` adapter."""

    adapter_name = "claude-agent"

    def __init__(self, command_runner: Optional[Callable[[list[str]], Any]] = None) -> None:
        self._command_runner = command_runner

    def build_command(self, prompt: str, opts: dict[str, Any]) -> list[str]:
        """Build the claude leaf command for the requested prompt."""
        command = ["claude", "-p", "--output-format", "json"]
        model = opts.get("model")
        if isinstance(model, str) and model:
            command.extend(["--model", model])
        command.append(prompt)
        return command

    def run(self, prompt: str, opts: dict[str, Any]) -> dict[str, Any]:
        """Return a leaf execution record or invoke the injected runner."""
        command = self.build_command(prompt, opts)
        if self._command_runner is None:
            return {
                "adapter": self.adapter_name,
                "command": command,
                "prompt": prompt,
                "opts": dict(opts),
                "status": "prepared",
            }

        result = self._command_runner(command)
        return {
            "adapter": self.adapter_name,
            "command": command,
            "prompt": prompt,
            "opts": dict(opts),
            "status": "executed",
            "result": result,
        }


def _canonical_payload(prompt: str, opts: dict[str, Any]) -> str:
    return json.dumps({"prompt": prompt, "opts": opts}, sort_keys=True, separators=(",", ":"))


def _hash_prompt_opts(prompt: str, opts: dict[str, Any]) -> str:
    payload = _canonical_payload(prompt, opts).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


@dataclass
class JournalStore:
    """Dict-backed journal with optional JSON persistence."""

    SCHEMA_VERSION: ClassVar[str] = "1"

    entries: dict[str, Any] = field(default_factory=dict)
    path: Optional[Path] = None
    spec_hash: Optional[str] = None
    route_profile: Optional[str] = None
    workflow: Optional[str] = None

    def key_for(self, prompt: str, opts: dict[str, Any]) -> str:
        return _hash_prompt_opts(prompt, opts)

    def get(self, prompt: str, opts: dict[str, Any]) -> Any:
        entry = self.entries.get(self.key_for(prompt, opts))
        if self._is_rich_entry(entry):
            return entry["result"]
        return entry

    def put(self, prompt: str, opts: dict[str, Any], value: Any) -> str:
        return self.put_leaf(
            prompt,
            opts,
            value,
            slot=self._slot_from_opts(opts),
            adapter=self._adapter_from_opts(opts),
        )

    def put_leaf(
        self,
        prompt: str,
        opts: dict[str, Any],
        value: Any,
        *,
        slot: Optional[str] = None,
        adapter: Optional[str] = None,
    ) -> str:
        key = self.key_for(prompt, opts)
        self.entries[key] = {
            "slot": slot,
            "adapter": adapter,
            "prompt_opts_hash": key,
            "result": value,
            "metadata": {},
        }
        return key

    def bind_identity(
        self,
        spec_hash: Optional[str],
        route_profile: Optional[str],
        workflow: Optional[str],
    ) -> bool:
        """Bind the journal to the current workflow identity.

        Returns True when existing entries were invalidated.
        """
        identity_changed = (
            self.spec_hash != spec_hash
            or self.route_profile != route_profile
            or self.workflow != workflow
        )
        if identity_changed and self.entries:
            self.entries.clear()

        self.spec_hash = spec_hash
        self.route_profile = route_profile
        self.workflow = workflow
        return identity_changed

    def to_dict(self) -> dict[str, Any]:
        return {
            "version": self.SCHEMA_VERSION,
            "spec_hash": self.spec_hash,
            "route_profile": self.route_profile,
            "workflow": self.workflow,
            "entries": dict(self.entries),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any], path: Optional[Path] = None) -> "JournalStore":
        entries = data.get("entries", {})
        if not isinstance(entries, dict):
            raise JournalSchemaError(
                f"Journal 'entries' field is malformed (got {type(entries).__name__!r}); "
                f"delete the journal file to reset"
            )
        return cls(
            entries=dict(entries),
            path=path,
            spec_hash=cls._optional_string(data.get("spec_hash")),
            route_profile=cls._optional_string(data.get("route_profile")),
            workflow=cls._optional_string(data.get("workflow")),
        )

    @classmethod
    def from_path(cls, path: Path) -> "JournalStore":
        if not path.exists():
            return cls(path=path)
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
            if not isinstance(raw, dict):
                raise ValueError("Journal root must be a JSON object")
        except (json.JSONDecodeError, ValueError, TypeError, OSError):
            cls._quarantine_corrupt(path)
            return cls(path=path)
        if raw.get("version") != cls.SCHEMA_VERSION:
            found = raw.get("version")
            raise JournalSchemaError(
                f"Journal version {found!r} is incompatible with {cls.SCHEMA_VERSION!r}; "
                f"delete {path} to reset"
            )
        try:
            return cls.from_dict(raw, path=path)
        except JournalSchemaError:
            cls._quarantine_corrupt(path)
            raise

    def save(self) -> None:
        if self.path is None:
            return
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp_path = self.path.with_suffix(self.path.suffix + ".tmp")
        tmp_path.write_text(json.dumps(self.to_dict(), indent=2, sort_keys=True), encoding="utf-8")
        tmp_path.rename(self.path)

    @staticmethod
    def _is_rich_entry(entry: Any) -> bool:
        return (
            isinstance(entry, dict)
            and {"slot", "adapter", "prompt_opts_hash", "result", "metadata"}.issubset(entry)
        )

    @staticmethod
    def _slot_from_opts(opts: dict[str, Any]) -> Optional[str]:
        slot = opts.get("slot")
        return slot if isinstance(slot, str) else None

    @staticmethod
    def _adapter_from_opts(opts: dict[str, Any]) -> Optional[str]:
        slot_target = opts.get("slot_target")
        if isinstance(slot_target, dict):
            adapter = slot_target.get("adapter")
            if isinstance(adapter, str):
                return adapter
        adapter = opts.get("adapter")
        return adapter if isinstance(adapter, str) else None

    @staticmethod
    def _optional_string(value: Any) -> Optional[str]:
        return value if isinstance(value, str) else None

    @staticmethod
    def _quarantine_corrupt(path: Path) -> None:
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        corrupt_base = path.with_suffix(".corrupt")
        corrupt_path = corrupt_base.with_name(f"{corrupt_base.name}.{timestamp}")
        counter = 1
        while corrupt_path.exists():
            corrupt_path = corrupt_base.with_name(f"{corrupt_base.name}.{timestamp}.{counter}")
            counter += 1
        try:
            path.rename(corrupt_path)
        except OSError:
            pass


class ResumeContext:
    """Load/save wrapper around the journal store."""

    def __init__(self, path: Optional[Path] = None, journal: Optional[JournalStore] = None) -> None:
        self.path = path
        self.journal = journal or JournalStore(path=path)
        if self.path is not None and self.path.exists():
            self.load()

    def load(self) -> JournalStore:
        if self.path is None:
            return self.journal
        self.journal = JournalStore.from_path(self.path)
        return self.journal

    def save(self) -> None:
        if self.path is not None:
            self.journal.path = self.path
        self.journal.save()


class WorkflowRuntime:
    """Read-only spike runtime for workflow JS specs."""

    def __init__(
        self,
        *,
        journal: Optional[JournalStore] = None,
        resume_context: Optional[ResumeContext] = None,
        executor_registry: Optional[dict[str, AgentExecutor]] = None,
        constraint_checker: Optional[SpineConstraintChecker] = None,
    ) -> None:
        self.constraint_checker = constraint_checker or SpineConstraintChecker()
        self.resume_context = resume_context
        self.journal = journal or (resume_context.journal if resume_context else JournalStore())
        self.executor_registry = executor_registry or {
            "claude-agent": ClaudeAgentExecutor(),
        }

    def run(self, spec_path: str | Path, args: dict[str, Any]) -> dict[str, Any]:
        """Load a workflow spec, validate the spine, and execute its agent leaves."""
        path = Path(spec_path)
        spec_bytes = path.read_bytes()
        spec_hash = hashlib.sha256(spec_bytes).hexdigest()
        source = spec_bytes.decode("utf-8")
        self.constraint_checker.validate(source)

        if self.resume_context is not None:
            self.journal = self.resume_context.load()
        self.journal.bind_identity(
            spec_hash,
            self._optional_arg_string(args.get("route_profile")),
            self._optional_arg_string(args.get("workflow")),
        )
        if self.resume_context is not None:
            self.resume_context.journal = self.journal

        meta = self._extract_meta(source)
        agent_calls = self._extract_agent_calls(source)

        leaf_results: list[dict[str, Any]] = []
        for call in agent_calls:
            prompt = call["prompt"]
            opts = dict(call["opts"])
            slot_target = self._resolve_slot_target(args, opts)
            opts.setdefault("slot_target", slot_target)
            leaf_results.append(self._run_leaf(prompt, opts))

        result = {
            "status": "ok",
            "spec": str(path),
            "meta": meta,
            "args": dict(args),
            "leaf_results": leaf_results,
            "journal": dict(self.journal.entries),
        }

        if self.resume_context is not None:
            self.resume_context.save()

        return result

    def _run_leaf(self, prompt: str, opts: dict[str, Any]) -> dict[str, Any]:
        adapter_name = self._resolve_adapter_name(opts)
        self.check_mutating_allowed(adapter_name, opts.get("readOnly") is True)

        cached = self.journal.get(prompt, opts)
        if cached is not None:
            return {
                "cached": True,
                "journal_key": self.journal.key_for(prompt, opts),
                "result": cached,
                "prompt": prompt,
                "opts": dict(opts),
            }

        executor = self.executor_registry.get(adapter_name)
        if executor is None:
            raise ValueError(f"No executor registered for adapter {adapter_name!r}")

        result = executor.run(prompt, opts)
        journal_key = self.journal.put_leaf(
            prompt,
            opts,
            result,
            slot=self._slot_from_opts(opts),
            adapter=adapter_name,
        )
        return {
            "cached": False,
            "journal_key": journal_key,
            "result": result,
            "prompt": prompt,
            "opts": dict(opts),
        }

    def check_mutating_allowed(self, adapter_name: str, read_only: bool) -> None:
        """Block mutating execution unless adapter preservation is verified."""
        if read_only:
            return

        status = ADAPTER_PRESERVATION_STATUS.get(adapter_name, "unknown")
        if status not in _MUTATING_ALLOWED_STATUSES:
            raise MutatingExecutionBlockedError(
                "Mutating workflow execution is blocked for adapter "
                f"{adapter_name!r}: preservation status is {status!r}"
            )

    @staticmethod
    def _resolve_adapter_name(opts: dict[str, Any]) -> str:
        slot_target = opts.get("slot_target", {})
        if isinstance(slot_target, dict):
            adapter = slot_target.get("adapter")
            if isinstance(adapter, str) and adapter:
                return adapter
        adapter = opts.get("adapter")
        if isinstance(adapter, str) and adapter:
            return adapter
        return "claude-agent"

    @staticmethod
    def _slot_from_opts(opts: dict[str, Any]) -> Optional[str]:
        slot = opts.get("slot")
        return slot if isinstance(slot, str) else None

    @staticmethod
    def _optional_arg_string(value: Any) -> Optional[str]:
        return value if isinstance(value, str) else None

    @staticmethod
    def _resolve_slot_target(args: dict[str, Any], opts: dict[str, Any]) -> dict[str, Any] | None:
        route_profiles = args.get("route_profiles")
        route_profile_name = args.get("route_profile")
        workflow = args.get("workflow", "full")
        slot_name = opts.get("slot")

        if not (
            isinstance(route_profiles, dict)
            and isinstance(route_profile_name, str)
            and route_profile_name
            and isinstance(slot_name, str)
            and slot_name
        ):
            return None

        profile = route_profiles.get(route_profile_name, {})
        slots = profile.get("slots", {}) if isinstance(profile, dict) else {}
        workflow_slots = slots.get(workflow, {}) if isinstance(slots, dict) else {}
        slot_target = workflow_slots.get(slot_name, {}) if isinstance(workflow_slots, dict) else {}
        return slot_target if isinstance(slot_target, dict) else None

    @staticmethod
    def _extract_meta(source: str) -> dict[str, Any]:
        marker = "export const meta ="
        start = source.find(marker)
        if start == -1:
            return {}
        brace_start = source.find("{", start)
        if brace_start == -1:
            return {}
        block, _ = WorkflowRuntime._extract_balanced(source, brace_start, "{", "}")
        try:
            return json.loads(block)
        except json.JSONDecodeError:
            return {}

    @staticmethod
    def _extract_agent_calls(source: str) -> list[dict[str, Any]]:
        calls: list[dict[str, Any]] = []
        cursor = 0
        marker = "await agent("
        stripped = SpineConstraintChecker._strip_comments(source)
        while True:
            idx = WorkflowRuntime._find_marker_outside_strings(stripped, marker, cursor)
            if idx == -1:
                break
            paren_start = stripped.find("(", idx)
            if paren_start == -1:
                break
            call_block, call_end = WorkflowRuntime._extract_balanced(stripped, paren_start, "(", ")")
            args_text = call_block[1:-1].strip()
            prompt_text, opts_text = WorkflowRuntime._split_agent_args(args_text)
            calls.append(
                {
                    "prompt": json.loads(prompt_text),
                    "opts": json.loads(opts_text),
                }
            )
            cursor = call_end
        return calls

    @staticmethod
    def _find_marker_outside_strings(source: str, marker: str, start: int) -> int:
        in_string = False
        string_delim = ""
        escape = False
        index = start

        while index < len(source):
            char = source[index]

            if in_string:
                if escape:
                    escape = False
                elif char == "\\":
                    escape = True
                elif char == string_delim:
                    in_string = False
                index += 1
                continue

            if char in ('"', "'", "`"):
                in_string = True
                string_delim = char
                index += 1
                continue

            if source.startswith(marker, index):
                return index

            index += 1

        return -1

    @staticmethod
    def _split_agent_args(args_text: str) -> tuple[str, str]:
        comma_index = WorkflowRuntime._find_top_level_comma(args_text)
        if comma_index == -1:
            raise ValueError("agent() call must include prompt and opts")
        prompt_text = args_text[:comma_index].strip()
        opts_text = args_text[comma_index + 1 :].strip()
        return prompt_text, opts_text

    @staticmethod
    def _find_top_level_comma(source: str) -> int:
        depth = 0
        in_string = False
        string_delim = ""
        escape = False
        for index, char in enumerate(source):
            if in_string:
                if escape:
                    escape = False
                elif char == "\\":
                    escape = True
                elif char == string_delim:
                    in_string = False
                continue

            if char in ('"', "'"):
                in_string = True
                string_delim = char
                continue
            if char in "{[(":
                depth += 1
                continue
            if char in "}])":
                depth -= 1
                continue
            if char == "," and depth == 0:
                return index
        return -1

    @staticmethod
    def _extract_balanced(source: str, start_index: int, open_char: str, close_char: str) -> tuple[str, int]:
        depth = 0
        in_string = False
        string_delim = ""
        escape = False
        for index in range(start_index, len(source)):
            char = source[index]
            if in_string:
                if escape:
                    escape = False
                elif char == "\\":
                    escape = True
                elif char == string_delim:
                    in_string = False
                continue
            if char in ('"', "'"):
                in_string = True
                string_delim = char
                continue
            if char == open_char:
                depth += 1
            elif char == close_char:
                depth -= 1
                if depth == 0:
                    return source[start_index : index + 1], index + 1
        raise ValueError(f"Unbalanced {open_char}{close_char} block in workflow source")
