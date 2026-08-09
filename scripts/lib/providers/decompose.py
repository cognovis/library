"""Decomposition of an upstream tree into typed Library items.

ADR-0011 `Mixed external bundles`: an external bundle is **decomposed** into its
typed members -- Skills, Workflows, Pi extensions, Pi profiles, Standards,
Prompts -- each classified individually. A generic `harness` primitive is
rejected by default.

Two layouts are supported, and which one applies is a property of the *source
registration*, not of anything this module discovers:

| Layout | What an item is |
|---|---|
| `marker` | A directory carrying a marker file (`SKILL.md`, `AGENT.md`, ...) |
| `bundle` | Every marker directory, **plus** each remaining file as its own member |

`marker` is the conservative reading and stays the default: a repository that
publishes primitives publishes them as marker directories, and treating its
`README.md` as a Prompt would fill an inventory with noise. `bundle` is for the
mixed repository the ADR describes, where the primitives are the point but they
do not all live behind a marker.

The rules are Library-owned and contain no provider knowledge. They key on a
member's own collection path and file extension, which is why an unrelated
provider laying its content out the same way classifies the same way.

**A member that fits no rule is `UNCLASSIFIED`.** That is the whole reason this
module exists rather than a two-line `for path in tree` loop: the tempting
alternatives are a new catch-all primitive, which is exactly what the ADR
refuses, and filing the member under the nearest existing type, which records a
classification nobody made.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Mapping, Sequence

from .classification import ITEM_MARKERS, UNCLASSIFIED, library_type_for

#: Upstream id for an item whose marker file sits at the tree root. The upstream
#: id is a tree-relative directory, and the root directory has no name; `.` is
#: that directory's name and keeps the id non-empty and unique.
ROOT_ITEM_ID = "."

MARKER_LAYOUT = "marker"
BUNDLE_LAYOUT = "bundle"
LAYOUTS = (MARKER_LAYOUT, BUNDLE_LAYOUT)

#: Layout rules for a bundle's loose members: `(collection segment, suffixes) ->
#: Library type`. The collection segment is the *immediate* parent directory,
#: because a rule that matched any ancestor would type a repository's whole
#: `docs/` subtree from one directory name several levels up.
_COLLECTION_RULES: tuple[tuple[str, tuple[str, ...], str], ...] = (
    ("extensions", (".ts", ".tsx", ".js", ".mjs", ".cjs", ".py"), "pi-extension"),
    ("profiles", (".json", ".yaml", ".yml", ".toml"), "pi-profile"),
    ("prompts", (".md", ".txt"), "prompt"),
    ("standards", (".md",), "standard"),
    ("workflows", (".md",), "workflow"),
)


class AmbiguousItemLayout(RuntimeError):
    """A tree-level item coexists with nested items.

    Their content overlaps, so which item owns which bytes is undefined. The
    durable cache would hold the same bytes under two identities and two
    receipts. Fail loudly here instead.
    """


@dataclass(frozen=True)
class ItemLayout:
    """One decomposed item: what it is called, and exactly which files it owns."""

    upstream_id: str
    upstream_name: str
    collection_membership: tuple[str, ...]
    member_paths: tuple[str, ...]
    primary_path: str
    library_type: str
    type_basis: str

    def relative(self, path: str) -> str:
        """A member's item-relative path.

        A directory item strips its own prefix; a single-file item is its own
        basename. Both forms have to round-trip through the cache, so the
        stripping happens once, here, and never at a call site.
        """
        if self.upstream_id == ROOT_ITEM_ID:
            return path
        prefix = f"{self.upstream_id}/"
        if path.startswith(prefix):
            return path[len(prefix) :]
        if path == self.upstream_id:
            return path.rsplit("/", 1)[-1]
        raise ValueError(f"{path!r} is not a member of item {self.upstream_id!r}")


def _suffix(path: str) -> str:
    basename = path.rsplit("/", 1)[-1].lower()
    return basename[basename.rfind(".") :] if "." in basename else ""


def _collection_type(path: str) -> tuple[str, str] | None:
    segments = path.split("/")
    if len(segments) < 2:
        return None
    parent = segments[-2].lower()
    suffix = _suffix(path)
    for collection, suffixes, library_type in _COLLECTION_RULES:
        if parent == collection and suffix in suffixes:
            return library_type, f"collection-layout:{collection}"
    return None


def _marker_directories(paths: Sequence[str]) -> dict[str, str]:
    """Directory -> its marker path, for every marker file in the tree."""
    found: dict[str, str] = {}
    for path in paths:
        basename = path.rsplit("/", 1)[-1].lower()
        if basename not in ITEM_MARKERS:
            continue
        directory = path.rsplit("/", 1)[0] if "/" in path else ROOT_ITEM_ID
        # A directory with two markers is not two items; the first in sorted
        # order wins so the layout is a deterministic function of the tree.
        found.setdefault(directory, path)
    return found


def _refuse_nested_markers(markers: Mapping[str, str]) -> None:
    """Refuse a marker directory that contains another marker directory.

    A marker item owns every path beneath its directory, so a nested marker makes
    two items own the same bytes: the outer item's content contains the inner
    item's whole content. Downstream that is two cache identities and two
    receipts for one artifact, which is the exact ownership collision the
    tree-level refusal already covers — the tree root is simply the case someone
    thought of first. Review demonstrated the general one: `outer/SKILL.md` beside
    `outer/child/AGENT.md` produced two items claiming the same files under both
    layouts.

    Refusing rather than trimming the outer item is deliberate. Trimming would
    silently redefine what the outer item *is*, and an upstream author who nested
    two markers has stated something the Library cannot interpret.
    """
    directories = sorted(name for name in markers if name != ROOT_ITEM_ID)
    for index, outer in enumerate(directories):
        prefix = f"{outer}/"
        for inner in directories[index + 1 :]:
            if inner.startswith(prefix):
                raise AmbiguousItemLayout(
                    f"marker item {inner!r} ({markers[inner]}) is nested inside "
                    f"marker item {outer!r} ({markers[outer]}); the outer item's "
                    "content contains the inner item's bytes, so item ownership is "
                    "undefined"
                )


def _marker_items(paths: Sequence[str], markers: Mapping[str, str]) -> list[ItemLayout]:
    items: list[ItemLayout] = []
    for directory in sorted(markers):
        marker_path = markers[directory]
        if directory == ROOT_ITEM_ID:
            members = tuple(paths)
            name = ""
            membership: tuple[str, ...] = ()
        else:
            prefix = f"{directory}/"
            members = tuple(path for path in paths if path.startswith(prefix))
            segments = directory.split("/")
            name = segments[-1]
            membership = tuple(segments[:-1])
        library_type, basis = library_type_for(marker_path)
        items.append(
            ItemLayout(
                upstream_id=directory,
                upstream_name=name,
                collection_membership=membership,
                member_paths=members,
                primary_path=marker_path,
                library_type=library_type,
                type_basis=basis,
            )
        )
    return items


def _loose_items(paths: Sequence[str], claimed: Iterable[str]) -> list[ItemLayout]:
    claimed_paths = set(claimed)
    items: list[ItemLayout] = []
    for path in paths:
        if path in claimed_paths:
            continue
        segments = path.split("/")
        typed = _collection_type(path)
        if typed is None:
            library_type, basis = library_type_for(path)
        else:
            library_type, basis = typed
        items.append(
            ItemLayout(
                upstream_id=path,
                upstream_name=segments[-1],
                collection_membership=tuple(segments[:-1]),
                member_paths=(path,),
                primary_path=path,
                library_type=library_type,
                type_basis=basis,
            )
        )
    return items


def decompose_tree(
    paths: Sequence[str], *, layout: str = MARKER_LAYOUT, root_name: str = ""
) -> tuple[ItemLayout, ...]:
    """Decompose one tree's blob paths into typed items.

    Args:
        paths: Every blob path in the tree, tree-relative.
        layout: `marker` or `bundle`; see the module docstring.
        root_name: The name a root-level marker item takes, since the root
            directory has none of its own.

    Raises:
        AmbiguousItemLayout: when a root-level marker coexists with nested
            items under the `marker` layout, so item ownership is undefined.
        ValueError: on an unknown layout.
    """
    if layout not in LAYOUTS:
        raise ValueError(f"unknown decomposition layout {layout!r}; expected {list(LAYOUTS)}")
    ordered = sorted(paths)
    markers = _marker_directories(ordered)
    _refuse_nested_markers(markers)
    items = _marker_items(ordered, markers)

    if layout == MARKER_LAYOUT:
        if ROOT_ITEM_ID in markers and len(items) > 1:
            raise AmbiguousItemLayout(
                f"a tree-level {markers[ROOT_ITEM_ID]} coexists with {len(items) - 1} "
                "nested item(s); the root item's content would contain the nested "
                "items' bytes, so item ownership is undefined"
            )
    else:
        # A root marker under the bundle layout would claim every file in the
        # tree, which is the same ownership collision, reached from the other
        # side. The bundle layout exists to split a repository up, so a member
        # that swallows it whole is refused rather than silently preferred.
        if ROOT_ITEM_ID in markers:
            raise AmbiguousItemLayout(
                f"a tree-level {markers[ROOT_ITEM_ID]} claims every file in a bundle "
                "layout, so no other member could own its own bytes"
            )
        claimed = {path for item in items for path in item.member_paths}
        items.extend(_loose_items(ordered, claimed))

    resolved: list[ItemLayout] = []
    for item in items:
        if item.upstream_id == ROOT_ITEM_ID:
            if not root_name.strip():
                raise ValueError(
                    "a root-level item needs a name from its source; the root "
                    "directory has none of its own"
                )
            item = ItemLayout(
                upstream_id=item.upstream_id,
                upstream_name=root_name,
                collection_membership=item.collection_membership,
                member_paths=item.member_paths,
                primary_path=item.primary_path,
                library_type=item.library_type,
                type_basis=item.type_basis,
            )
        resolved.append(item)
    return tuple(sorted(resolved, key=lambda entry: entry.upstream_id))


def unclassified_members(items: Sequence[ItemLayout]) -> tuple[ItemLayout, ...]:
    """The members no existing Library type fits."""
    return tuple(item for item in items if item.library_type == UNCLASSIFIED)
