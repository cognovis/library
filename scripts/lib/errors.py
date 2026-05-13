"""
errors.py — Typed exceptions and exit codes for the library CLI.
"""

from __future__ import annotations


# Exit code constants
EXIT_SUCCESS = 0
EXIT_FAILURE = 1
EXIT_NOT_FOUND = 2       # catalog entry not found; NOTE: shares value with EXIT_DRIFT
EXIT_AMBIGUOUS = 3
EXIT_DEPENDENCY_MISSING = 4
EXIT_DRY_RUN = 0  # dry-run returns 0 with planned operations in output
EXIT_DRIFT = 2    # audit drift detected; NOTE: shares value with EXIT_NOT_FOUND (renumber in follow-up)


class LibraryError(Exception):
    """Base class for all library CLI errors."""

    def __init__(self, message: str, exit_code: int = EXIT_FAILURE) -> None:
        super().__init__(message)
        self.exit_code = exit_code


class NotFoundError(LibraryError):
    """Raised when a catalog entry is not found."""

    def __init__(self, name: str, primitive: str) -> None:
        super().__init__(
            f"No {primitive} named '{name}' found in catalog. "
            f"Run: python3 scripts/library.py {primitive} list",
            exit_code=EXIT_NOT_FOUND,
        )
        self.name = name
        self.primitive = primitive


class AmbiguousMatchError(LibraryError):
    """Raised when a query matches multiple entries."""

    def __init__(self, query: str, primitive: str, matches: list[str]) -> None:
        matches_str = ", ".join(f"'{m}'" for m in matches[:5])
        super().__init__(
            f"Ambiguous {primitive} query '{query}' — matches: {matches_str}. "
            f"Use an exact name.",
            exit_code=EXIT_AMBIGUOUS,
        )
        self.query = query
        self.primitive = primitive
        self.matches = matches


class DependencyMissingError(LibraryError):
    """Raised when a required dependency is not installed."""

    def __init__(self, dep: str, required_by: str) -> None:
        super().__init__(
            f"Dependency '{dep}' required by '{required_by}' is not installed. "
            f"Install it first.",
            exit_code=EXIT_DEPENDENCY_MISSING,
        )
        self.dep = dep
        self.required_by = required_by


class CatalogError(LibraryError):
    """Raised when library.yaml is invalid or cannot be loaded."""


class LockfileError(LibraryError):
    """Raised when .library.lock is invalid or cannot be written."""


class InstallError(LibraryError):
    """Raised when installation fails."""


class SourceError(LibraryError):
    """Raised when a source URL cannot be resolved or fetched."""
