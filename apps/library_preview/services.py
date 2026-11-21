"""Read-only anonymous projections over explicitly granted synthetic publications.

No service identity, staff cookie or capability is created for an anonymous reader.
The expiring preview policy authorizes exact redacted publication/source snapshots;
canonical services validate their current approval and bindings under the case lock.
"""

import os
from contextlib import ExitStack, contextmanager
from contextvars import ContextVar

from django.conf import settings
from django.db import connection, transaction
from django.utils import timezone

from apps.case_citations import services as citations
from apps.casework import services as cases
from apps.casework.models import Case
from apps.data_privacy import integration as privacy
from apps.editorial_search.query_terms import normalize_editorial_search
from apps.experimental_publication import services as publication
from apps.experimental_publication.models import PublicationEdition
from apps.intake_workflow.guards import require_owned_database
from apps.knowledge_links import services as knowledge
from apps.knowledge_links.models import KnowledgeRevision
from apps.platform_recovery.integration import mutation_service

from .policy import PreviewPolicy

PAGE_SIZE = 12
SOURCE_FIELDS = (
    "work_title",
    "heading_title",
    "edition_title",
    "edition_key",
    "publisher",
    "printed_part",
    "printed_page",
    "path",
)


_RETURN_DEADLINES = ContextVar("library_preview_return_deadlines", default=None)


def _retain_deadlines(values, *, replace=False):
    bounds = _RETURN_DEADLINES.get()
    if bounds is not None:
        if replace:
            bounds.clear()
        bounds.extend(value for value in values if value is not None)


class PreviewUnavailable(Exception):
    """Uniform denial: never include a private identifier or reason in HTTP output."""


class InvalidFilter(ValueError):
    pass


def policy() -> PreviewPolicy:
    if (
        os.environ.get("FATWA_PRODUCTION") != "0"
        or getattr(settings, "FATWA_LIBRARY_PREVIEW_ENABLED", False) is not True
        or getattr(settings, "FATWA_EXPERIMENTAL_PUBLICATION_ENABLED", False) is not True
        or getattr(settings, "FATWA_CASE_CITATIONS_ENABLED", False) is not True
        or getattr(settings, "FATWA_KNOWLEDGE_LINKS_ENABLED", False) is not True
    ):
        raise PreviewUnavailable()
    selected = getattr(settings, "FATWA_LIBRARY_PREVIEW_POLICY", None)
    if type(selected) is not PreviewPolicy:
        raise PreviewUnavailable()
    try:
        selected.validate()
    except (ValueError, TypeError, AttributeError):
        raise PreviewUnavailable() from None
    return selected


def _recheck(selected: PreviewPolicy) -> None:
    if policy() is not selected:
        raise PreviewUnavailable()


def _start() -> PreviewPolicy:
    selected = policy()
    if connection.in_atomic_block:
        # A composed reader may reuse only the already verified execution-local
        # queue unit bound to this exact connection and live atomic block.
        from apps.delivery_queue.services import QueueConflict, _postgres_only

        try:
            _postgres_only()
        except QueueConflict as exc:
            raise PreviewUnavailable() from exc
    else:
        require_owned_database(synthetic_fixtures_only=True)
    return selected


def _independent(edition: PublicationEdition) -> bool:
    actions = {a.action: a for a in edition.actions.all()}
    if "APPROVE" not in actions or "REVIEW" not in actions:
        return False
    approver, reviewer = actions["APPROVE"], actions["REVIEW"]
    return (approver.provider_id, approver.subject_id) not in {
        (edition.provider_id, edition.subject_id),
        (reviewer.provider_id, reviewer.subject_id),
        (edition.decision.provider_id, edition.decision.subject_id),
    }


def _grant(selected: PreviewPolicy, publication_id: str):
    return next((g for g in selected.publications if g.publication_id == str(publication_id)), None)


def _privacy_publisher(edition):
    from apps.data_privacy import services as classification

    if not classification.applicable("PUBLICATION", str(edition.pk)):
        return None
    event = edition.actions.filter(action="APPROVE").first()
    directory = getattr(settings, "FATWA_CASEWORK_IDENTITY_PROVIDER", None)
    if event is None or directory is None or directory.provider_id != event.provider_id:
        raise classification.PrivacyDenied("privacy_publication_actor_required")
    actor = cases._identity(directory, event.subject_id, edition.case)
    if actor.auth_epoch != event.auth_epoch:
        raise classification.PrivacyDenied("privacy_publication_actor_changed")
    return classification.staff_principal(directory, actor)


def _privacy_source(edition, kind, identifier):
    """The recorded publisher retains a current independent right over originals."""
    from apps.data_privacy import services as classification

    if not classification.applicable(kind, str(identifier)):
        return
    principal = _privacy_publisher(edition)
    if principal is None:
        raise classification.PrivacyDenied("privacy_publication_actor_required")
    classification.require(kind, identifier, principal=principal, action="PUBLISH")


def _privacy_edition(edition, *, action="READ"):
    from apps.data_privacy import services as classification
    from apps.data_privacy.resource_hooks import _references

    privacy.public("PUBLICATION", edition.pk, action=action)
    _privacy_source(edition, "ANSWER", edition.answer_id)
    for item in edition.citations:
        source = item["source"]
        identifiers = _references(
            edition.case, edition_id=source["edition_id"], source_row_id=source["source_row_id"]
        )
        if not identifiers and classification.enabled():
            raise classification.PrivacyDenied("privacy_registered_source_required")
        for identifier in identifiers:
            _privacy_source(edition, "SOURCE_VERSION", identifier)


@privacy.public_contextual
@contextmanager
def _current(selected: PreviewPolicy, publication_id: str):
    grant = _grant(selected, publication_id)
    if grant is None:
        raise PreviewUnavailable()
    edition = PublicationEdition.objects.filter(pk=grant.publication_id).first()
    if edition is None:
        raise PreviewUnavailable()
    with transaction.atomic(), ExitStack() as privacy_stack:
        from apps.precise_citations.integration import lock_dependencies

        lock_dependencies(edition.case_id)
        case = Case.objects.select_for_update().get(pk=edition.case_id)
        try:
            _privacy_edition(edition)
            privacy_stack.enter_context(privacy.published_sources(_privacy_publisher(edition)))
            cases._verify(case)
            publication._approved(case, edition)
            publication._verify(edition)
            publication._require_publication_sources(case, edition.citations)
            latest = (
                PublicationEdition.objects.filter(case=case, actions__action="APPROVE")
                .order_by("-number")
                .first()
            )
            if (
                edition.content_sha256 != grant.content_sha256
                or latest is None
                or latest.pk != edition.pk
                or not _independent(edition)
                or edition.actions.filter(action="WITHDRAW").exists()
                or edition.citations != publication._citation_snapshot(edition.answer)
            ):
                raise PreviewUnavailable()
        except cases.CaseConflict:
            raise PreviewUnavailable() from None
        yield edition
        _recheck(selected)
        # Clock expiry can occur while material/history is projected even though
        # the case lock serializes explicit revocation. Policy and source grants
        # must both remain valid at the projection's return boundary.
        try:
            deadline = publication._require_publication_sources(case, edition.citations)
            _retain_deadlines((selected.valid_until, deadline))
        except cases.CaseConflict:
            raise PreviewUnavailable() from None


def _permitted_source(selected: PreviewPolicy, item: dict, case) -> dict | None:
    source = item["source"]
    if not all(
        citations._permits_source(case, item, usage) for usage in ("READ", "PREVIEW_METADATA")
    ):
        return None
    if not any(
        grant.edition_id == source["edition_id"]
        and grant.source_row_id == source["source_row_id"]
        and grant.source_sha256 == item["source_sha256"]
        for grant in selected.references
    ):
        return None
    # Validation above checks the complete current citation. Only explicitly
    # allowed display metadata crosses this boundary; no editorial notes/IDs/hashes.
    return {key: source[key] for key in SOURCE_FIELDS}


def _references(selected: PreviewPolicy, edition: PublicationEdition) -> list[dict]:
    return [
        {"position": position, **source}
        for position, item in enumerate(edition.citations, 1)
        if (source := _permitted_source(selected, item, edition.case)) is not None
    ]


def _relationships(selected: PreviewPolicy, edition: PublicationEdition) -> dict:
    references, private_related, seen = [], False, set()
    for row in (
        KnowledgeRevision.objects.filter(publication=edition)
        .prefetch_related("actions")
        .order_by("series", "-number")
    ):
        if row.series in seen:
            continue
        seen.add(row.series)
        actions = {a.action: a for a in row.actions.all()}
        if "APPROVE" not in actions or "WITHDRAW" in actions:
            continue
        approved = actions["APPROVE"]
        if (approved.provider_id, approved.subject_id) == (
            row.provider_id,
            row.subject_id,
        ) or row.snapshot_sha256 != knowledge._digest(row.snapshot):
            continue
        if row.heading_id:
            try:
                _privacy_source(edition, "KNOWLEDGE_REVISION", row.pk)
                # Locked, exact-reference-only adapter. Do not call knowledge.browse:
                # that staff projection can resolve private transcript bundles.
                heading = row.heading
                source = citations._source(heading.edition_id, heading.source_row_id)
                if not citations._permits_source(edition.case, source, "RELATE"):
                    continue
                if source not in edition.citations or row.snapshot != {
                    "kind": "REFERENCE",
                    **source,
                }:
                    continue
                display = _permitted_source(selected, source, edition.case)
                if display is not None:
                    position = edition.citations.index(source) + 1
                    references.append({"position": position, "number": row.number, **display})
            except cases.CaseConflict:
                continue
        elif row.transcript_id:
            # A private relation may be indicated, but carries no identifier, text,
            # raw-evidence URL, timing, source name, or path to the staff API.
            # Private transcript rights cannot authorize anonymous metadata.
            # With rights enforced, even relationship existence remains private.
            from apps.data_privacy.services import enabled as privacy_enabled
            from apps.source_rights.enforcement import required

            if not required() and not privacy_enabled():
                private_related = True
    return {"references": references, "private_related": private_related}


def _projection(selected: PreviewPolicy, edition: PublicationEdition) -> dict:
    return {
        "id": str(edition.pk),
        "number": edition.number,
        "title": edition.title,
        "category": edition.category,
        "body": edition.body,
        "references": _references(selected, edition),
        "relations": _relationships(selected, edition),
    }


def _history(selected: PreviewPolicy, edition: PublicationEdition) -> list[dict]:
    rows = []
    # Only versions explicitly included in the preview policy and independently
    # approved. No candidate existence, title, body, case lineage or actor is shown.
    for old in PublicationEdition.objects.filter(
        case_id=edition.case_id, pk__in=[g.publication_id for g in selected.publications]
    ).order_by("-number"):
        grant = _grant(selected, str(old.pk))
        if not _independent(old) or old.content_sha256 != grant.content_sha256:
            continue
        try:
            _privacy_edition(old)
            publication._verify(old)
        except cases.CaseConflict:
            continue
        withdrawn = old.actions.filter(action="WITHDRAW").exists()
        rows.append(
            {
                "number": old.number,
                "state": "WITHDRAWN"
                if withdrawn
                else ("CURRENT" if old.pk == edition.pk else "SUPERSEDED"),
                "published_at": old.actions.get(action="APPROVE").created_at,
            }
        )
    return rows


def filters(*, query: str = "", category: str = "", material: str = "", page: int = 1) -> dict:
    for value in (query, category):
        if (
            type(value) is not str
            or len(value) > 80
            or any(ord(c) < 32 or ord(c) == 127 for c in value)
        ):
            raise InvalidFilter()
    if material not in {"", "reference"} or type(page) is not int or not 1 <= page <= 100:
        raise InvalidFilter()
    return {"query": query, "category": category, "material": material, "page": page}


@privacy.public_contextual
@contextmanager
def _media_boundary():
    from apps.casework.media_boundary import media_projection_boundary
    from apps.delivery_queue.services import synthetic_queue_atomic
    from apps.precise_citations.integration import answer_use_boundary

    bounds = []
    token = _RETURN_DEADLINES.set(bounds)
    try:
        _start()
        # This collection owns filtered, emitted-only deadline tracking below.
        # Do not retain deadlines for candidates subsequently removed by browse.
        with synthetic_queue_atomic(), answer_use_boundary(), media_projection_boundary(retain_deadlines=False):
            yield
        # The atomic media epoch read can itself span a deadline. No authority
        # callbacks follow this final clock. Browse retains only emitted grants,
        # preserving its established removal of already-expired earlier rows.
        now = timezone.now()
        if any(deadline <= now for deadline in bounds):
            raise PreviewUnavailable()
    except cases.CaseConflict:
        raise PreviewUnavailable() from None
    finally:
        _RETURN_DEADLINES.reset(token)


@mutation_service
@_media_boundary()
def browse(*, query: str = "", category: str = "", material: str = "", page: int = 1) -> dict:
    chosen = filters(query=query, category=category, material=material, page=page)
    selected = _start()
    available = []
    # Hold every selected case in a deterministic order until the catalog snapshot
    # is collected, so a concurrent withdrawal cannot leave an earlier row visible
    # while a later grant is being processed. No global/private-case scan.
    with transaction.atomic():
        case_ids = PublicationEdition.objects.filter(
            pk__in=[g.publication_id for g in selected.publications]
        ).values_list("case_id", flat=True)
        from apps.precise_citations.integration import prelock_cases

        case_ids = prelock_cases(case_ids)
        list(Case.objects.filter(pk__in=case_ids).order_by("pk").select_for_update())
        for grant in selected.publications:
            try:
                with _current(selected, grant.publication_id) as edition:
                    _privacy_edition(edition, action="SEARCH")
                    projected = _projection(selected, edition)
                # Publish to the response collection only after the context's
                # return-boundary checks succeeded. Failed exits cannot leave a
                # stale item, category or count in the response.
                available.append((edition, projected))
            except PreviewUnavailable:
                continue
        # Revalidate the whole collected batch after the last projection. A
        # per-item context exit cannot protect an earlier item while later ones
        # are assembled. Do this before deriving any facet, count or page.
        checked = []
        for edition, projected in available:
            try:
                deadline = publication._require_publication_sources(edition.case, edition.citations)
            except cases.CaseConflict:
                continue
            checked.append((projected, deadline))
        _recheck(selected)
        now = timezone.now()
        checked = [(row, end) for row, end in checked if end is None or end > now]
        available = [row for row, _ in checked]
        available.sort(key=lambda row: (normalize_editorial_search(row["title"]), row["id"]))
        categories = sorted({row["category"] for row in available}, key=normalize_editorial_search)
        needle = normalize_editorial_search(query)
        category_key = normalize_editorial_search(category)
        matched = []
        for row in available:
            source_text = " ".join(
                str(source[key]) for source in row["references"] for key in SOURCE_FIELDS
            )
            haystack = normalize_editorial_search(
                " ".join((row["title"], row["category"], row["body"], source_text))
            )
            if (
                (not needle or needle in haystack)
                and (not category_key or normalize_editorial_search(row["category"]) == category_key)
                and (material != "reference" or row["references"])
            ):
                # Listing does not duplicate the publication body.
                matched.append({key: value for key, value in row.items() if key != "body"})
        start = (page - 1) * PAGE_SIZE
        result = {
            "items": matched[start : start + PAGE_SIZE],
            "categories": categories,
            "total": len(matched),
            "has_previous": page > 1,
            "has_next": start + PAGE_SIZE < len(matched),
            "filters": chosen,
        }
        _recheck(selected)
        # A single final clock covers grants checked earlier in the pass too.
        # Expiry during sorting/filtering fails closed instead of exposing any
        # stale result or rebuilding an unbounded, repeatedly expiring response.
        now = timezone.now()
        if any(end is not None and end <= now for _, end in checked):
            raise PreviewUnavailable()
        _retain_deadlines((selected.valid_until, *(end for _, end in checked)), replace=True)
        return result


@mutation_service
@_media_boundary()
def read(publication_id: str) -> dict:
    selected = _start()
    with _current(selected, publication_id) as edition:
        result = _projection(selected, edition)
        result["history"] = _history(selected, edition)
        return result


@mutation_service
@_media_boundary()
def read_reference(publication_id: str, position: int) -> dict:
    if type(position) is not int or not 1 <= position <= 12:
        raise PreviewUnavailable()
    selected = _start()
    with _current(selected, publication_id) as edition:
        if position > len(edition.citations):
            raise PreviewUnavailable()
        display = _permitted_source(selected, edition.citations[position - 1], edition.case)
        if display is None:
            raise PreviewUnavailable()
        return {
            "publication_id": str(edition.pk),
            "publication_title": edition.title,
            "position": position,
            "source": display,
        }
