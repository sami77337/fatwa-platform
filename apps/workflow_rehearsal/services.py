"""Replay a fixed sequence against existing synthetic fixtures in memory only.

Preparation revisions and internal-review labels are independent dimensions.
REVIEWED_INTERNAL is a contract label, never scholarly approval or publication.
Reference verification is the existing fixed catalog's technical match; this
module neither improves it nor treats it as authority to review a real ruling.
"""

from dataclasses import dataclass, replace
from types import MappingProxyType

from apps.editorial_workbench.services import WorkbenchCase, build_cases
from apps.fatwa_drafts.domain import DraftRecord, transition
from apps.fatwa_drafts.intake import ValidationError
from apps.fatwa_drafts.revision_audit import RevisionAuditEntry, build_revision_audit
from apps.intake_workflow.contracts import ContractError, next_review_status

CASE_KEYS = (
    "history",
    "intake-1",
    "intake-2",
    "intake-3",
    "intake-4",
    "intake-5",
    "intake-6",
    "intake-7",
    "intake-8",
)

# No user-supplied commands, actor, source, target state, or mutable stage.
# The prohibited target is a deliberate negative test, never a product state.
_ATTEMPTS = (
    ("review", "complete_review"),
    ("preparation", "draft_preparation"),
    ("preparation", "published"),
    ("review", "start_review"),
    ("review", "request_changes"),
    ("review", "start_review"),
    ("review", "complete_review"),
    ("review", "complete_review"),
)


class RehearsalError(ValueError):
    """Selector is outside the fixed synthetic fixture allowlist."""


@dataclass(frozen=True, slots=True)
class RehearsalStep:
    ordinal: int
    dimension: str
    action: str
    accepted: bool
    reason: str
    from_preparation: str | None
    to_preparation: str | None
    from_review: str
    to_review: str
    from_revision: int | None
    to_revision: int | None


@dataclass(frozen=True, slots=True)
class Rehearsal:
    case: WorkbenchCase
    source_record: DraftRecord | None
    projected_record: DraftRecord | None
    steps: tuple[RehearsalStep, ...]
    audit: tuple[RevisionAuditEntry, ...]
    source_audit: tuple[RevisionAuditEntry, ...]
    review_status: str
    fixture_sha256: str


def _freeze(value):
    """Freeze the adapter's JSON diagnostic leaves after all adapters finish."""
    if isinstance(value, dict):
        return MappingProxyType({key: _freeze(item) for key, item in value.items()})
    if isinstance(value, (list, tuple)):
        return tuple(_freeze(item) for item in value)
    return value


def _audit(record: DraftRecord | None) -> tuple[RevisionAuditEntry, ...]:
    return (
        build_revision_audit(record, synthetic_fixtures_only=True).entries
        if record is not None
        else ()
    )


def build_rehearsal(key: str = "intake-7") -> Rehearsal:
    """Fresh immutable projection of one allowlisted fixture and fixed attempts.

    The first duplicate Wave7 row is blocked; row seven is the received ready draft.
    Missing drafts reject every attempt, without fabricating a record. Existing
    history retains its original preparation state and revision identities. Review
    attempts use only the pure transition table, never the persisted review service.
    All original Arabic, whitespace, reference identities and diagnostics survive.
    """
    if type(key) is not str or key not in CASE_KEYS:
        raise RehearsalError("rehearsal: unknown_fixed_case")
    case = next(case for case in build_cases() if case.key == key)
    return _rehearse(case)


def build_prepared_rehearsal(key: str, *, synthetic_fixtures_only: bool = False) -> Rehearsal:
    """Offline bridge for exact, fixed prepared rows, including rejected receipts.

    No arbitrary record, source path, actor or transition is accepted. Missing
    drafts remain missing. The original HTTP selector remains unchanged.
    """
    from apps.editorial_export.services import require_development
    from apps.editorial_workbench.services import build_prepared_workbench

    require_development(synthetic_fixtures_only)
    if type(key) is not str or key not in (
        *(f"batch-synthetic-csv-{n}" for n in range(1, 5)),
        *(f"batch-synthetic-json-{n}" for n in range(1, 5)),
        *(f"batch-synthetic-jsonl-{n}" for n in range(1, 4)),
    ):
        raise RehearsalError("rehearsal: unknown_fixed_prepared_case")
    matches = [case for case in build_prepared_workbench().cases if case.key == key]
    if len(matches) != 1:
        raise RehearsalError("rehearsal: prepared_identity_set")
    return _rehearse(matches[0])


def _rehearse(case: WorkbenchCase) -> Rehearsal:
    """Shared fixed attempts over an internally selected synthetic case."""
    case = replace(case, references=_freeze(case.references))
    source = record = case.record
    review = "UNREVIEWED"
    steps = []
    for ordinal, (dimension, action) in enumerate(_ATTEMPTS, 1):
        before_preparation = record.current.state.value if record else None
        before_revision = record.current.number if record else None
        before_review = review
        accepted = False
        reason = "rehearsal: no_draft_available"
        if record is not None:
            try:
                if dimension == "preparation":
                    record = transition(
                        record,
                        action,
                        expected_revision=record.current.number,
                        human_editor="وسم محاكاة اصطناعي ثابت",
                        editorial_note="إسقاط تقني في الذاكرة فقط؛ لا تحرير علمي أو اعتماد أو نشر.",
                    )
                else:
                    review = next_review_status(review, action).value
                accepted = True
                reason = "rehearsal: accepted_by_pure_contract"
            except (ValidationError, ContractError) as exc:
                reason = str(exc)
        steps.append(
            RehearsalStep(
                ordinal=ordinal,
                dimension=dimension,
                action=action,
                accepted=accepted,
                reason=reason,
                from_preparation=before_preparation,
                to_preparation=record.current.state.value if record else None,
                from_review=before_review,
                to_review=review,
                from_revision=before_revision,
                to_revision=record.current.number if record else None,
            )
        )
    return Rehearsal(
        case=case,
        source_record=source,
        projected_record=record,
        steps=tuple(steps),
        audit=_audit(record),
        source_audit=_audit(source),
        review_status=review,
        fixture_sha256=case.payload_sha256,
    )
