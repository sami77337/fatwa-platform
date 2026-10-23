"""Pure triage groups over an existing caller-asserted synthetic report.

This projection adds no reference decisions, citation rendering, source lookups
or evidence. Synthetic acknowledgement is a caller assertion, never proof of
source authenticity, archive inspection or scholarly validity. Existing gate
holds and deployment restrictions are unaffected.
"""

from dataclasses import dataclass
from hashlib import sha256

from apps.intake_workflow import contracts as c
from apps.intake_workflow.references import ItemReferenceVerification, ReferenceVerification

from .diagnostics import ReferenceDiagnosticReport


@dataclass(frozen=True, slots=True)
class DiagnosticGroupMember:
    """One occurrence, retaining the exact original item/reference objects.

    Locator components are input hash, row ordinal and reference ordinal.
    Source hashes describe the retained UTF-8 slices; equal text/source IDs do
    not collapse separate occurrences. Byte offsets remain on the source DTOs.
    """

    locator: tuple[str, int, int]
    item: ItemReferenceVerification
    reference: ReferenceVerification
    item_source_sha256: str
    reference_source_sha256: str


@dataclass(frozen=True, slots=True)
class ReferenceDiagnosticGroup:
    """One exact technical status/reason tuple, including verified/no-reason.

    Reasons retain their original order and multiplicity; they are neither
    reinterpreted nor expanded into separately counted reference occurrences.
    Item count is distinct source row ordinals represented in this group.
    """

    status: c.ReferenceStatus
    reasons: tuple[str, ...]
    members: tuple[DiagnosticGroupMember, ...]
    item_count: int
    reference_count: int


@dataclass(frozen=True, slots=True)
class ReferenceDiagnosticGroups:
    """Frozen projection retaining its original report without serialization.

    Total item count includes items without references. Group item counts may
    overlap when an item has different outcomes, so they must not be summed to
    obtain the report total. Each reference belongs to exactly one group.
    """

    report: ReferenceDiagnosticReport
    groups: tuple[ReferenceDiagnosticGroup, ...]
    item_count: int
    reference_count: int


def group_reference_diagnostics(
    report: ReferenceDiagnosticReport, *, synthetic_fixtures_only: bool = False,
) -> ReferenceDiagnosticGroups:
    """Group an immutable report from ``build_reference_diagnostics``.

    This is a presentation projection, not a validator for manually fabricated
    DTO graphs. The original immutable report and planner results are retained
    by identity. Groups sort lexically by contract status value then the exact
    reason tuple; members sort by row/reference ordinal. No I/O is performed.
    """
    if synthetic_fixtures_only is not True:
        raise c.ContractError("synthetic_acknowledgement_required")
    if type(report) is not ReferenceDiagnosticReport:
        raise c.ContractError("reference: diagnostic_report_required")

    grouped: dict[
        tuple[c.ReferenceStatus, tuple[str, ...]], list[DiagnosticGroupMember]
    ] = {}
    reference_count = 0
    for item in report.items:
        item_hash = sha256(item.source.text.encode("utf-8")).hexdigest()
        for reference in item.references:
            member = DiagnosticGroupMember(
                (report.payload_sha256, item.row_ordinal, reference.reference_ordinal),
                item, reference, item_hash,
                sha256(reference.source.text.encode("utf-8")).hexdigest(),
            )
            grouped.setdefault((reference.status, reference.reasons), []).append(member)
            reference_count += 1

    groups = tuple(
        ReferenceDiagnosticGroup(
            status, reasons, tuple(sorted(members, key=lambda member: member.locator)),
            len({member.item.row_ordinal for member in members}), len(members),
        )
        for (status, reasons), members in sorted(
            grouped.items(), key=lambda entry: (entry[0][0].value, entry[0][1]),
        )
    )
    return ReferenceDiagnosticGroups(report, groups, len(report.items), reference_count)
