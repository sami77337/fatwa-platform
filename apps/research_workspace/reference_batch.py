"""Fresh locked TOC projection; never a cross-request permission cache.

Caller owns synthetic admission, canonical case lock, staff identity and an expiry
projection guard. Reload after ranking before ANY rows/counts/facets/pages leave.
"""

from contextlib import contextmanager
from dataclasses import asdict

from django.conf import settings
from django.db import connection
from django.utils import timezone

from apps.case_citations import services as citations
from apps.casework import services as cases
from apps.platform_recovery.integration import require_admission
from apps.reference_links.bridge import SourceIdentity
from apps.reference_links.resolution import Heading, Outcome, SnapshotCatalog, resolve
from apps.source_rights import services as ledger
from apps.source_rights.enforcement import required
from apps.source_rights.models import (
    RightsAction,
    RightsRevision,
    SourceRegistration,
    SourceVersion,
)

from . import services as workspace
from .rights import ResearchRights
from .source_rights_adapter import SourceRightsAdapter

CAPACITY = 64  # Existing case registration cap, not a new corpus limit.


def _stock(policy):
    return type(policy) is SourceRightsAdapter and "permits" not in vars(policy)


def _epoch(policy):
    if _stock(policy):
        return "canonical-locked-ledger"  # ledger is reloaded; expiry guard still mandatory
    try:
        epoch = policy.projection_epoch()
    except Exception as exc:
        raise cases.CaseConflict("research_policy_snapshot_required") from exc
    if type(epoch) is not str or not epoch or len(epoch) > 1000:
        raise cases.CaseConflict("research_policy_snapshot_required")
    return epoch


@contextmanager
def policy_boundary():
    policy = getattr(settings, "FATWA_RESEARCH_WORKSPACE_RIGHTS", None)
    if not isinstance(policy, ResearchRights):
        raise cases.CaseConflict("research_resource_not_authorized")
    epoch = _epoch(policy)
    yield
    if (
        getattr(settings, "FATWA_RESEARCH_WORKSPACE_RIGHTS", None) is not policy
        or _epoch(policy) != epoch
    ):
        raise cases.CaseConflict("research_policy_changed")


def _source(heading):
    """Exact existing resolver evidence from eagerly loaded five-level ancestry."""
    edition, node, path, seen = heading.edition, heading, [], set()
    for depth in range(5):
        if node.pk in seen or node.edition_id != edition.pk or not 1 <= node.depth <= 5:
            raise cases.CaseConflict("existing_verified_source_required")
        seen.add(node.pk)
        path.append(node.title_original)
        if node.parent_id is None:
            if node.depth != 1:
                raise cases.CaseConflict("existing_verified_source_required")
            break
        if depth == 4 or node.depth == 1 or node.parent.depth != node.depth - 1:
            raise cases.CaseConflict("existing_verified_source_required")
        node = node.parent
    evidence = Heading(
        edition_id=edition.pk,
        source_row_id=heading.source_row_id,
        work_title=edition.work.title_original,
        heading_title=heading.title_original,
        printed_part=heading.source_part,
        printed_page=heading.source_page_number,
        path=tuple(reversed(path)),
        source_namespace=edition.work.source_namespace,
        source_book_id=edition.work.source_book_id,
        edition_key=edition.edition_key,
        source_archive_sha256=edition.source_archive_sha256,
        source_input_sha256=edition.source_input_sha256,
    )
    resolved = resolve(
        {"edition_id": edition.pk, "source_row_id": heading.source_row_id},
        SnapshotCatalog([evidence]),
    )
    if resolved.outcome != Outcome.VERIFIED:
        raise cases.CaseConflict("existing_verified_source_required")
    source = asdict(resolved.evidence)
    source["path"] = list(source["path"])
    SourceIdentity(**{key: source[key] for key in SourceIdentity.__dataclass_fields__})
    source.update(
        edition_title=edition.title, publisher=edition.publisher, kind="SOURCE_BOOK_TOC_NOT_FATWAS"
    )
    workspace._bridge(source, catalog=SnapshotCatalog([evidence]))
    return {"source": source, "source_sha256": citations._digest(source)}


def _policy(policy, actor, provider, case, action, resource):
    # Exact stock adapter adds only the ledger predicates checked here. Subclass
    # or custom policy is ALWAYS called; its restrictions must never be bypassed.
    if _stock(policy):
        return True
    try:
        return (
            policy.permits(
                provider_id=provider.provider_id,
                subject_id=actor.subject_id,
                auth_epoch=actor.auth_epoch,
                case_ref=case.public_ref,
                action=action,
                resource=resource,
            )
            is True
        )
    except Exception as exc:
        raise cases.CaseConflict("research_rights_unavailable") from exc


def read_locked(*, case, actor, provider, edition_id):
    """Four bounded SQL reads; only current reviewed READ grants reach matching.

    No rights data leaves this internal boundary. Bad provenance fails closed.
    No cache, global policy override, monkeypatch, or relaxation of source checks.
    """
    require_admission()
    if not connection.in_atomic_block or not required():
        raise cases.CaseConflict("current_source_rights_required")
    workspace._enabled()
    citations._enabled()
    ledger._enabled()
    policy = getattr(settings, "FATWA_RESEARCH_WORKSPACE_RIGHTS", None)
    if not isinstance(policy, ResearchRights):
        raise cases.CaseConflict("research_resource_not_authorized")
    ids = list(SourceRegistration.objects.filter(case=case).values_list("source_id", flat=True))
    if len(ids) > CAPACITY:
        raise cases.CaseConflict("source_rights_registration_capacity")
    revisions = list(
        RightsRevision.objects.filter(case=case, source_id__in=ids)
        .order_by("source_id", "-number")
        .distinct("source_id")
    )
    actions = {}
    for revision_id, action in RightsAction.objects.filter(revision__in=revisions).values_list(
        "revision_id", "action"
    ):
        actions.setdefault(revision_id, set()).add(action)
    now = timezone.now()
    current = {
        r.source_id: r
        for r in revisions
        if r.valid_until > now
        and "READ" in r.uses
        and "APPROVE" in actions.get(r.pk, ())
        and not {"REVOKE", "REJECT"}.intersection(actions.get(r.pk, ()))
    }
    # Content is fetched only after eligible rights have been selected.
    versions = (
        SourceVersion.objects.filter(
            pk__in=current,
            kind="TOC_METADATA",
            heading__edition_id=edition_id,
            heading__edition__work__source_book_id="622",
        )
        .select_related("heading__edition__work", "heading__parent__parent__parent__parent")
        .order_by("heading__source_order", "heading__source_row_id")
    )
    rows, edition_allowed = [], None
    for version in versions:
        snapshot = _source(version.heading)
        if version.sha256 != ledger._digest(version.snapshot) or version.snapshot != {
            "kind": "TOC_METADATA",
            **snapshot,
        }:
            raise cases.CaseConflict("source_rights_source_changed")
        resource = workspace._source_resource(snapshot["source"], snapshot["source_sha256"])
        if edition_allowed is None:
            edition_allowed = _policy(
                policy,
                actor,
                provider,
                case,
                "DISCOVER",
                workspace._edition_resource(version.heading.edition),
            )
        if (
            not edition_allowed
            or not _policy(policy, actor, provider, case, "DISCOVER", resource)
            or not _policy(policy, actor, provider, case, "READ_METADATA", resource)
        ):
            continue
        revision = current[version.pk]
        ledger._projection_deadline(revision.valid_until)
        rows.append(
            {
                "resource": asdict(resource),
                "kind": "REFERENCE",
                "title": snapshot["source"]["heading_title"],
                "label": "عنوان فهرس؛ ليس متن الكتاب ولا فتوى",
                "source": snapshot["source"],
                "_rights_revision": str(revision.pk),
            }
        )
    if not rows:
        raise cases.CaseConflict("research_edition_unavailable")
    return rows


def recheck_locked(*, expected, **kwargs):
    """Reload grants/actions/provenance/policy; change invalidates all aggregates."""
    fresh = read_locked(**kwargs)
    if fresh != expected:
        raise cases.CaseConflict("research_rights_changed")
    # Final collection-level policy check AFTER all per-row construction/callbacks.
    # It catches SEC14-01; the enclosing epoch boundary additionally catches a
    # versioned policy changing an earlier grant during THIS final pass.
    from .rights import Resource

    policy = getattr(settings, "FATWA_RESEARCH_WORKSPACE_RIGHTS", None)
    for row in fresh:
        resource = Resource(**row["resource"])
        for action in ("DISCOVER", "READ_METADATA"):
            if not _policy(
                policy, kwargs["actor"], kwargs["provider"], kwargs["case"], action, resource
            ):
                raise cases.CaseConflict("research_resource_not_authorized")
    return fresh
