"""Approval-bound branch vocabulary; Task/run IDs remain internal identities."""

import re
from collections.abc import Callable
from typing import Annotated, Literal

from pydantic import AfterValidator, StringConstraints, TypeAdapter


def _semantic_name(value: str) -> str:
    slug = value.split("/", 2)[2]
    if re.search(r"(?:^|-)attempt-[0-9]+(?:-|$)", slug) or re.search(
        r"(?:^|-)[a-f0-9]{16,}(?:-|$)", slug
    ):
        raise ValueError("branch names require business meaning, not IDs or attempt numbers")
    return value


BranchName = Annotated[
    str,
    StringConstraints(
        min_length=11,
        max_length=240,
        pattern=r"^ai/(feature|bugfix)/[a-z][a-z0-9]*(?:-[a-z0-9]+)*$",
    ),
    AfterValidator(_semantic_name),
]

BRANCH_NAMING_INSTRUCTIONS = (
    "For ready output provide branch_name as ai/feature/<business-slug> for new functionality "
    "or ai/bugfix/<problem-slug> for an independent defect request. Use a concise lowercase "
    "English kebab-case business name; no Task IDs, hashes or attempt-N. Classify by the original "
    "request, not by later QA/Review rework. Ask for clarification if its nature is ambiguous. "
    "The name is reviewed and frozen with ProductSpec. Use meaningful scope qualifiers to "
    "distinguish unrelated requirements; never reuse another requirement's branch."
)

_SUCCESSOR_SUFFIXES = ("recovery", "review-fixes", "prerequisite-repair")
_SUCCESSOR_SUFFIX_RE = re.compile(
    rf"(?:-(?:{'|'.join(re.escape(item) for item in _SUCCESSOR_SUFFIXES)}))+$"
)


def _successor_root(original: BranchName) -> str:
    """Return the stable Product branch slug behind generated suffixes."""
    kind, slug = original.split("/", 2)[1:]
    root_slug = _SUCCESSOR_SUFFIX_RE.sub("", slug)
    return f"ai/{kind}/{root_slug}"


def successor_branch(
    original: BranchName | None,
    purpose: Literal["recovery", "review-fixes", "prerequisite-repair"],
) -> BranchName | None:
    """Preserve kind and business scope without recursively growing the name.

    None is reserved for historical unclassified deliveries. The source Task, not
    the initial ProductSpec, owns the current name across multiple successors. Generated
    purpose suffixes are collapsed before the next purpose is appended. Collision checks
    remain the caller's responsibility; this helper never truncates or invents an ID.
    """
    if original is None:
        return None
    root = _successor_root(original)
    return TypeAdapter(BranchName).validate_python(f"{root}-{purpose}")


def available_successor_branch(
    original: BranchName | None,
    purpose: Literal["recovery", "review-fixes", "prerequisite-repair"],
    *,
    is_occupied: Callable[[str], bool],
) -> BranchName | None:
    """Choose an unused semantic successor name for one delivery lineage.

    A repeated recovery must not append another generated suffix to the source
    Task (for example ``recovery-recovery``), and it must not reuse a branch
    still owned by an earlier immutable successor.  The first candidate keeps
    the historical semantic name; subsequent candidates add a bounded numeric
    qualifier to the same stable Product slug.  The caller supplies the
    read-only Git ownership check so this domain helper never mutates refs.
    """
    candidate = successor_branch(original, purpose)
    if candidate is None or not is_occupied(candidate):
        return candidate
    root = _successor_root(original) if original is not None else None
    if root is None:
        return None
    for ordinal in range(2, 1000):
        candidate = TypeAdapter(BranchName).validate_python(f"{root}-{purpose}-{ordinal}")
        if not is_occupied(candidate):
            return candidate
    raise ValueError("no available semantic successor branch")
