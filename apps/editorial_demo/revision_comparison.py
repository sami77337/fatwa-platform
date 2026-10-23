"""Compatibility exports for the neutral revision core.

Definitions retain a single implementation; their canonical module and new pickle
paths are apps.revision_core. Existing editorial pickle globals remain resolvable.
"""

from apps.revision_core.revision_comparison import (
    ChangeKind as ChangeKind,
    ChangeTarget as ChangeTarget,
    Literal as Literal,
    MAX_TEXT_LENGTH as MAX_TEXT_LENGTH,
    ReferenceComparison as ReferenceComparison,
    ReferenceLink as ReferenceLink,
    Revision as Revision,
    RevisionComparison as RevisionComparison,
    SequenceMatcher as SequenceMatcher,
    TextComparison as TextComparison,
    TextPart as TextPart,
    compare_revisions as compare_revisions,
    dataclass as dataclass,
)
