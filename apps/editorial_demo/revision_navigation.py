"""Immutable neighbours for the comparison's authoritative changed-group order."""

from dataclasses import dataclass

from .revision_comparison import ChangeTarget

# These are the actual focusable section IDs rendered by the comparison partial.
_SECTION_ANCHORS = frozenset({
    "change-title", "change-answer", "change-reviewer_notes", "change-references",
})


@dataclass(frozen=True, slots=True)
class DifferenceNavigation:
    current: ChangeTarget
    previous: ChangeTarget | None
    following: ChangeTarget | None


def difference_sequence(targets: tuple[ChangeTarget, ...]) -> tuple[DifferenceNavigation, ...]:
    """Use only supplied groups; do not infer, sort, wrap or mutate neighbours.

    Reject duplicate or unrendered destinations before any link is presented.
    Labels remain original text and are escaped by the consuming Django template.
    """
    seen: set[str] = set()
    for target in targets:
        if target.anchor not in _SECTION_ANCHORS or target.anchor in seen:
            raise ValueError("invalid_difference_navigation_target")
        seen.add(target.anchor)
    return tuple(
        DifferenceNavigation(
            target, targets[index - 1] if index else None,
            targets[index + 1] if index + 1 < len(targets) else None,
        )
        for index, target in enumerate(targets)
    )
