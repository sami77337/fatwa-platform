"""Bounded exact reference-ledger reads; no identity or custom-policy authority.

Use only inside the canonical authorized case transaction. The exit check is a
fresh database read, not a cached decision. A changed member invalidates the
whole projection, including its counts/facets. Custom policy callbacks still
need the consumer's independent final collection checks.
"""

from contextlib import contextmanager
from copy import deepcopy
from dataclasses import asdict

from django.db import connection
from django.db.models import Q
from django.utils import timezone

from apps.case_citations import services as citations
from apps.casework import services as cases
from apps.casework.models import Case
from apps.reference.models import ReferenceHeading
from apps.reference_links.bridge import SourceIdentity
from apps.reference_links.resolution import Heading, Outcome, SnapshotCatalog, resolve

from . import services as ledger
from .models import RightsAction, RightsRevision, SourceVersion

MAX_IDENTITIES = 256


def _inputs(identities, usages):
    if not isinstance(identities, (list, tuple)) or len(identities) > MAX_IDENTITIES:
        raise cases.CaseConflict("rights_batch_bound")
    if (
        not isinstance(usages, (list, tuple))
        or not usages
        or any(type(use) is not str or use not in ledger.USES for use in usages)
    ):
        raise cases.CaseConflict("rights_batch_usage")
    result = []
    for key in identities:
        if (
            not isinstance(key, (list, tuple))
            or len(key) != 2
            or any(type(value) is not int or not 1 <= value <= 2**63 - 1 for value in key)
        ):
            raise cases.CaseConflict("rights_batch_identity")
        result.append(tuple(key))
    return tuple(dict.fromkeys(result)), frozenset(usages)


def _catalog(identities):
    """Same bounded path and pure resolver as canonical citations, bulk ancestors."""
    if not identities:
        return {}, {}
    requested = set(identities)
    exact = Q()
    for edition_id, row_id in requested:
        exact |= Q(edition_id=edition_id, source_row_id=row_id)
    candidates = list(ReferenceHeading.objects.filter(exact).select_related("edition__work"))
    nodes = {row.pk: row for row in candidates}
    frontier = candidates
    for _ in range(4):
        missing = {
            row.parent_id for row in frontier if row.parent_id and row.parent_id not in nodes
        }
        if not missing:
            break
        frontier = list(ReferenceHeading.objects.filter(pk__in=missing))
        nodes.update((row.pk, row) for row in frontier)
    snapshots = {}
    headings = {}
    for row in candidates:
        current, path, seen = row, [], set()
        valid = False
        for _ in range(5):
            if (
                current.pk in seen
                or current.edition_id != row.edition_id
                or not 1 <= current.depth <= 5
            ):
                break
            seen.add(current.pk)
            path.append(current.title_original)
            if current.parent_id is None:
                valid = current.depth == 1
                break
            parent = nodes.get(current.parent_id)
            if parent is None or parent.depth != current.depth - 1:
                break
            current = parent
        if not valid:
            continue
        edition = row.edition
        evidence = Heading(
            edition_id=edition.pk,
            source_row_id=row.source_row_id,
            work_title=edition.work.title_original,
            heading_title=row.title_original,
            printed_part=row.source_part,
            printed_page=row.source_page_number,
            path=tuple(reversed(path)),
            source_namespace=edition.work.source_namespace,
            source_book_id=edition.work.source_book_id,
            source_input_sha256=edition.source_input_sha256,
            edition_key=edition.edition_key,
            source_archive_sha256=edition.source_archive_sha256,
        )
        key = (edition.pk, row.source_row_id)
        resolution = resolve(
            dict(zip(("edition_id", "source_row_id"), key)), SnapshotCatalog([evidence])
        )
        if resolution.outcome != Outcome.VERIFIED:
            continue
        source = asdict(resolution.evidence)
        source["path"] = list(source["path"])
        try:
            SourceIdentity(**{name: source[name] for name in SourceIdentity.__dataclass_fields__})
        except (ValueError, TypeError, KeyError):
            continue
        source.update(
            edition_title=edition.title,
            publisher=edition.publisher,
            kind="SOURCE_BOOK_TOC_NOT_FATWAS",
        )
        snapshots[key] = {"source": source, "source_sha256": citations._digest(source)}
        headings[row.pk] = key
    return snapshots, headings


def _read(case, identities, usages):
    ledger._enabled()
    citations._enabled()
    if not connection.in_atomic_block:
        raise cases.CaseConflict("rights_batch_transaction_required")
    snapshots, headings = _catalog(identities)
    versions = list(
        SourceVersion.objects.filter(
            heading_id__in=headings,
            sourceregistration__case_id=case.pk,
        )
    )
    latest = {
        row.source_id: row
        for row in RightsRevision.objects.filter(
            case_id=case.pk,
            source_id__in=[version.pk for version in versions],
        )
        .order_by("source_id", "-number")
        .distinct("source_id")
    }
    actions = {}
    for revision_id, action in RightsAction.objects.filter(
        revision_id__in=[row.pk for row in latest.values()],
    ).values_list("revision_id", "action"):
        actions.setdefault(revision_id, set()).add(action)
    result, receipts = {}, {}
    now = timezone.now()
    for version in versions:
        key = headings[version.heading_id]
        source = snapshots[key]
        revision = latest.get(version.pk)
        if (
            version.kind != "TOC_METADATA"
            or version.snapshot != {"kind": "TOC_METADATA", **source}
            or version.sha256 != ledger._digest(version.snapshot)
            or revision is None
            or revision.valid_until <= now
            or not usages.issubset(revision.uses)
        ):
            continue
        decisions = actions.get(revision.pk, set())
        if "APPROVE" not in decisions or decisions & {"REJECT", "REVOKE"}:
            continue
        result[key] = source
        receipts[key] = (str(version.pk), str(revision.pk), revision.valid_until)
        ledger._projection_deadline(revision.valid_until)
    return result, receipts


@contextmanager
def reference_projection_for_locked_case(*, case, identities, usages=("READ",)):
    """Yield readable canonical sources, then re-read all yielded grants before exit.

    No result may escape before successful context exit. Do not retain the mapping
    for later requests. Consumer must independently enforce custom policy, current
    staff identity and source visibility, including all count/facet inputs. No
    callbacks are invoked by this API. Empty or denied grants expose no metadata.
    """
    identities, usages = _inputs(identities, usages)
    if not connection.in_atomic_block:
        raise cases.CaseConflict("rights_batch_transaction_required")
    # Lock is defense in depth, not authorization. Canonical callers already own
    # it; source-rights mutation services serialize on this same row.
    if not Case.objects.select_for_update().filter(pk=case.pk, public_ref=case.public_ref).exists():
        raise cases.CaseConflict("rights_batch_case_unavailable")
    initial, receipts = _read(case, identities, usages)
    with ledger.projection_expiry_guard():
        yield deepcopy(initial)
        final, final_receipts = _read(case, tuple(initial), usages)
        if final != initial or final_receipts != receipts:
            raise cases.CaseConflict("current_source_rights_required")
        now = timezone.now()
        if any(receipt[2] <= now for receipt in final_receipts.values()):
            raise cases.CaseConflict("current_source_rights_required")
