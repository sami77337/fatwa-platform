"""Compatibility exports for the neutral revision core.

Definitions retain a single implementation; their canonical module and new pickle
paths are apps.revision_core. Existing editorial pickle globals remain resolvable.
"""

from apps.revision_core.revision_history import (
    DraftRecord as DraftRecord,
    HistoryDataError as HistoryDataError,
    HistoryEntry as HistoryEntry,
    IntakeItem as IntakeItem,
    InvalidRevisionId as InvalidRevisionId,
    Revision as Revision,
    UnknownRevisionId as UnknownRevisionId,
    build_history as build_history,
    compare_revisions as compare_revisions,
    dataclass as dataclass,
    re as re,
    select_revisions as select_revisions,
    text as text,
)
