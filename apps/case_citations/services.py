"""Human selection of existing, exact catalog entries; no generated references."""

import json
from dataclasses import asdict
from hashlib import sha256

from django.apps import apps as django_apps
from django.conf import settings

from apps.casework import services as cases
from apps.casework.models import AnswerRevision
from apps.platform_recovery.integration import mutation_service
from apps.reference import services as catalog
from apps.reference.models import ReferenceEdition, ReferenceHeading
from apps.reference.normalization import normalize_title
from apps.reference.query import InvalidQuery, Page, validate_search
from apps.reference_links.bridge import SourceIdentity
from apps.reference_links.django_adapter import DjangoCatalog
from apps.reference_links.resolution import Outcome, resolve

from .models import AnswerCitation, CitationCorrection

MAX_CITATIONS = 12


def _enabled():
    if getattr(settings, "FATWA_CASE_CITATIONS_ENABLED", False) is not True:
        raise cases.CaseConflict("case_citations_disabled")


def _rights_services():
    """Additional rights only; caller already owns the canonical case lock."""
    from apps.source_rights.enforcement import required

    if not required():
        return None
    if not django_apps.is_installed("apps.source_rights"):
        raise cases.CaseConflict("current_source_rights_required")
    from apps.source_rights import services as rights

    rights._enabled()
    return rights


def _permits_source(case, source, usage):
    try:
        rights = _rights_services()
        return (
            rights is None
            or rights.permits_reference_for_locked_case(case=case, source=source, usage=usage)
            is True
        )
    except cases.CaseConflict:
        return False


def _require_source(case, source, usage):
    if not _permits_source(case, source, usage):
        raise cases.CaseConflict("current_source_rights_required")


def _readable_sources(case):
    rights = _rights_services()
    if rights is None:
        return None
    from apps.source_rights.models import SourceVersion

    allowed = {}
    for version in (
        SourceVersion.objects.filter(sourceregistration__case=case, heading__isnull=False)
        .select_related("heading")
        .distinct()
    ):
        heading = version.heading
        try:
            source = _source(heading.edition_id, heading.source_row_id)
            if _permits_source(case, source, "READ"):
                allowed.setdefault(heading.edition_id, set()).add(heading.source_row_id)
        except cases.CaseConflict:
            continue
    return allowed


def _digest(value):
    return sha256(
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def _source(edition_id, source_row_id):
    result = resolve({"edition_id": edition_id, "source_row_id": source_row_id}, DjangoCatalog())
    if result.outcome != Outcome.VERIFIED:
        raise cases.CaseConflict("existing_verified_source_required")
    source = asdict(result.evidence)
    source["path"] = list(source["path"])
    try:
        SourceIdentity(**{key: source[key] for key in SourceIdentity.__dataclass_fields__})
    except (ValueError, TypeError, KeyError) as exc:
        raise cases.CaseConflict("existing_verified_source_required") from exc
    edition = ReferenceEdition.objects.get(pk=edition_id)
    source.update(
        edition_title=edition.title, publisher=edition.publisher, kind="SOURCE_BOOK_TOC_NOT_FATWAS"
    )
    return {"source": source, "source_sha256": _digest(source)}


@mutation_service
def search_sources(
    *,
    case_id,
    subject_id,
    provider,
    query="",
    edition_id=None,
    printed_part="",
    printed_page=None,
    synthetic_fixtures_only=False,
):
    with cases._staff_case(case_id, subject_id, provider, synthetic_fixtures_only) as (case, _):
        return _search_sources_for_locked_case(
            case,
            query=query,
            edition_id=edition_id,
            printed_part=printed_part,
            printed_page=printed_page,
            enforce_rights=True,
        )


@mutation_service
def _search_sources_for_rights_review(
    *, case_id, subject_id, provider, query="", edition_id=None, synthetic_fixtures_only=False
):
    """Private metadata bootstrap, authorized independently by the rights authority."""
    from apps.source_rights import services as rights

    with cases._staff_case(case_id, subject_id, provider, synthetic_fixtures_only) as (case, actor):
        rights._permit(actor, provider, case, "VIEW")
        result = _search_sources_for_locked_case(
            case, query=query, edition_id=edition_id, enforce_rights=False
        )
        rights._identity(case, actor, provider)
        return result


def _search_sources_for_locked_case(
    case, *, query="", edition_id=None, printed_part="", printed_page=None, enforce_rights=True
):
    _enabled()
    if type(query) is not str or len(query) > 100:
        raise cases.CaseConflict("invalid_citation_query")
    if (
        type(printed_part) is not str
        or len(printed_part) > 100
        or any(ord(char) < 32 for char in printed_part)
        or (
            printed_page is not None
            and (type(printed_page) is not int or not 1 <= printed_page <= 999999999)
        )
    ):
        raise cases.CaseConflict("invalid_citation_location")
    readable = _readable_sources(case) if enforce_rights else None
    edition_rows = ReferenceEdition.objects.filter(work__source_book_id="622")
    if readable is not None:
        edition_rows = edition_rows.filter(pk__in=readable)
    editions = list(edition_rows.select_related("work").order_by("pk")[:100])
    available = [
        {
            "id": e.pk,
            "book": e.work.title_original,
            "title": e.title,
            "edition_key": e.edition_key,
        }
        for e in editions
    ]
    if edition_id is None:
        return {"editions": available, "results": []}
    if type(edition_id) is not int or edition_id not in {e.pk for e in editions}:
        raise cases.CaseConflict("existing_edition_required")
    edition = next(e for e in editions if e.pk == edition_id)
    try:
        validate_search(query, "normalized")
        if readable is not None or printed_part or printed_page is not None:
            headings = ReferenceHeading.objects.filter(edition=edition)
            if readable is not None:
                headings = headings.filter(source_row_id__in=readable.get(edition.pk, ()))
            if printed_part:
                headings = headings.filter(source_part=printed_part)
            if printed_page is not None:
                headings = headings.filter(source_page_number=printed_page)
            normalized = normalize_title(query)
            if query.strip() and not normalized.strip():
                headings = headings.none()
            for token in dict.fromkeys(normalized.split()):
                headings = headings.filter(title_normalized__contains=token)
            ids = list(
                headings.order_by("source_order", "source_row_id").values_list(
                    "source_row_id", flat=True
                )[:20]
            )
        else:
            found = catalog.search(edition, query, "normalized", Page(20, 0))
            ids = [item["id"] for item in found.items]
    except InvalidQuery as exc:
        raise cases.CaseConflict("invalid_citation_query") from exc
    results = []
    for source_row_id in ids:
        try:
            results.append(_source(edition_id, source_row_id))
        except cases.CaseConflict:
            # Incomplete catalog evidence must never become a selectable citation.
            continue
    return {"editions": available, "results": results}


@mutation_service
def read_source(
    *, case_id, subject_id, provider, edition_id, source_row_id, synthetic_fixtures_only=False
):
    _enabled()
    with cases._staff_case(case_id, subject_id, provider, synthetic_fixtures_only) as (case, _):
        source = _source(edition_id, source_row_id)
        _require_source(case, source, "READ")
        return source


@mutation_service
def save_cited_answer(
    *,
    case_id,
    subject_id,
    provider,
    text,
    selections,
    expected_revision,
    expected_evidence_version,
    synthetic_fixtures_only=False,
    corrections=(),
):
    _enabled()
    cases._text(text)
    cases._mutation_versions(expected_revision, expected_evidence_version)
    if type(selections) not in (list, tuple) or not 1 <= len(selections) <= MAX_CITATIONS:
        raise cases.CaseConflict("bounded_explicit_citations_required")
    with cases._staff_case(
        case_id,
        subject_id,
        provider,
        synthetic_fixtures_only,
        expected_revision=expected_revision,
        expected_evidence_version=expected_evidence_version,
    ) as (case, actor):
        if case.stage == "NEEDS_CLARIFICATION":
            raise cases.CaseConflict("requester_clarification_still_required")
        previous = case.answers.order_by("-revision").first()
        checked, seen = [], set()
        for item in selections:
            if type(item) is not dict or set(item) != {
                "edition_id",
                "source_row_id",
                "source_sha256",
                "editorial_note",
            }:
                raise cases.CaseConflict("explicit_source_selection_required")
            cases._text(item["editorial_note"], optional=True)
            if len(item["editorial_note"]) > 2000:
                raise cases.CaseConflict("citation_note_too_long")
            source = _source(item["edition_id"], item["source_row_id"])
            _require_source(case, source, "CITE")
            key = (item["edition_id"], item["source_row_id"])
            if key in seen or source["source_sha256"] != item["source_sha256"]:
                raise cases.CaseConflict("citation_source_changed_or_duplicate")
            seen.add(key)
            heading = ReferenceHeading.objects.get(edition_id=key[0], source_row_id=key[1])
            checked.append((heading, source, item["editorial_note"]))
        correction_map = {}
        if type(corrections) not in (list, tuple) or len(corrections) > MAX_CITATIONS:
            raise cases.CaseConflict("invalid_citation_corrections")
        for change in corrections:
            if type(change) is not dict or set(change) != {"ordinal", "previous_id", "reason"}:
                raise cases.CaseConflict("invalid_citation_correction")
            ordinal = change["ordinal"]
            if type(ordinal) is not int or not 1 <= ordinal <= len(checked):
                raise cases.CaseConflict("invalid_citation_correction")
            cases._text(change["reason"])
            if len(change["reason"]) > 2000 or ordinal in correction_map:
                raise cases.CaseConflict("invalid_citation_correction")
            old = AnswerCitation.objects.filter(
                pk=cases._uuid(change["previous_id"]), answer=previous
            ).first()
            if old is None or old.pk in {row.pk for row, _ in correction_map.values()}:
                raise cases.CaseConflict("citation_correction_lineage_mismatch")
            correction_map[ordinal] = (old, change["reason"])
        # Same canonical history transition as casework.save_answer, within the
        # existing case lock so the answer and its source snapshots commit together.
        case.answer_revision += 1
        answer = AnswerRevision.objects.create(
            case=case,
            revision=case.answer_revision,
            evidence_version=case.evidence_version,
            text=text,
            text_sha256=cases._digest(text),
            subject_id=actor.subject_id,
            provider_id=provider.provider_id,
            auth_epoch=actor.auth_epoch,
        )
        case.stage, case.approved_answer = "UNDER_REVIEW", None
        cases._event(case, "SAVE_ANSWER", actor.subject_id, answer=answer)
        for ordinal, (heading, source, note) in enumerate(checked, 1):
            citation = AnswerCitation.objects.create(
                answer=answer, heading=heading, ordinal=ordinal, editorial_note=note, **source
            )
            if ordinal in correction_map:
                old, reason = correction_map[ordinal]
                CitationCorrection.objects.create(citation=citation, previous=old, reason=reason)
        if previous is not None and django_apps.is_installed("apps.answer_media"):
            from apps.answer_media.services import clone_parts_for_new_answer

            clone_parts_for_new_answer(previous, answer)
        return cases._staff(case)


def _citation_snapshots_for_locked_answer(answer):
    """Internal projection for callers holding the authorized canonical case lock.

    This is not an authorization entrypoint. Publication services can snapshot
    these records only after validating their own independently scoped authority.
    """
    result = []
    for row in AnswerCitation.objects.filter(answer=answer).select_related("heading"):
        if row.source_sha256 != _digest(row.source):
            raise cases.CaseConflict("citation_snapshot_inconsistent")
        current = _source(row.source["edition_id"], row.source["source_row_id"])
        if current["source_sha256"] != row.source_sha256:
            raise cases.CaseConflict("citation_source_changed")
        result.append(
            {
                "id": str(row.pk),
                "answer_id": str(row.answer_id),
                "ordinal": row.ordinal,
                "source": row.source,
                "source_sha256": row.source_sha256,
                "editorial_note": row.editorial_note,
            }
        )
    return result


def citations_for_locked_answer(answer):
    """Current CITE availability under the caller's existing canonical case lock."""
    rows = _citation_snapshots_for_locked_answer(answer)
    for row in rows:
        _require_source(answer.case, {key: row[key] for key in ("source", "source_sha256")}, "CITE")
    return rows


def clone_citations_for_new_answer(previous, answer):
    """Copy verified references in an already authorized answer-edit transaction.

    Caller holds the case lock, created the next canonical answer and SAVE_ANSWER
    event, and cleared approval. Copies source snapshots, never approval/release.
    PostgreSQL rejects writes outside the answer's creation transaction as well.
    """
    if (
        previous.case_id != answer.case_id
        or previous.pk == answer.pk
        or answer.revision != previous.revision + 1
    ):
        raise cases.CaseConflict("citation_answer_lineage_mismatch")
    snapshots = citations_for_locked_answer(previous)
    previous_rows = {str(row.pk): row for row in AnswerCitation.objects.filter(answer=previous)}
    for snapshot in snapshots:
        old = previous_rows[snapshot["id"]]
        AnswerCitation.objects.create(
            answer=answer,
            heading_id=old.heading_id,
            ordinal=old.ordinal,
            source=old.source,
            source_sha256=old.source_sha256,
            editorial_note=old.editorial_note,
        )


@mutation_service
def read_citations(*, case_id, subject_id, provider, answer_id=None, synthetic_fixtures_only=False):
    _enabled()
    with cases._staff_case(case_id, subject_id, provider, synthetic_fixtures_only) as (case, _):
        answer = (
            case.answers.filter(pk=cases._uuid(answer_id)).first()
            if answer_id
            else (case.answers.order_by("-revision").first())
        )
        if answer is None:
            if answer_id:
                raise cases.CaseConflict("case_answer_unavailable")
            return []
        rows = citations_for_locked_answer(answer)
        for row in rows:
            _require_source(
                case, {"source": row["source"], "source_sha256": row["source_sha256"]}, "READ"
            )
        return rows


@mutation_service
def suggest_sources(**kwargs):
    """Deterministic catalog candidates only; no generated text or scholarly score.

    The caller supplies a short human search phrase. This cannot write an answer,
    approve one, or claim that a heading establishes the answer's reasoning.
    """
    query = kwargs.get("query", "")
    found = search_sources(**kwargs)  # Authority checked even for empty searches.
    if len(normalize_title(query).strip()) < 2:
        return []
    return [
        dict(
            row, status="PROPOSED_REQUIRES_HUMAN_REVIEW", method="EXISTING_NORMALIZED_HEADING_MATCH"
        )
        for row in found["results"][:5]
    ]


@mutation_service
def read_citation_history(
    *, case_id, subject_id, provider, before_revision=None, synthetic_fixtures_only=False
):
    """Read immutable snapshots, including superseded entries, under current scope.

    A historical snapshot is never passed off as current catalog evidence. It
    remains readable when the current source cannot be resolved, but not selectable.
    """
    _enabled()
    if before_revision is not None and (type(before_revision) is not int or before_revision < 1):
        raise cases.CaseConflict("invalid_citation_history_cursor")
    with cases._staff_case(case_id, subject_id, provider, synthetic_fixtures_only) as (case, _):
        answers = case.answers.order_by("-revision")
        if before_revision is not None:
            answers = answers.filter(revision__lt=before_revision)
        page = list(answers[:21])
        history = []
        for answer in page[:20]:
            rows = []
            for row in answer.citations.select_related("correction__previous__answer"):
                if row.source_sha256 != _digest(row.source):
                    raise cases.CaseConflict("citation_snapshot_inconsistent")
                try:
                    current = _source(row.source["edition_id"], row.source["source_row_id"])
                    available = current["source_sha256"] == row.source_sha256 and _permits_source(
                        case, current, "CITE"
                    )
                except cases.CaseConflict:
                    available = False
                readable = _permits_source(
                    case, {"source": row.source, "source_sha256": row.source_sha256}, "READ"
                )
                correction = getattr(row, "correction", None)
                previous_readable = correction is not None and _permits_source(
                    case,
                    {
                        "source": correction.previous.source,
                        "source_sha256": correction.previous.source_sha256,
                    },
                    "READ",
                )
                rows.append(
                    dict(
                        id=str(row.pk),
                        ordinal=row.ordinal,
                        source=row.source if readable else None,
                        source_sha256=row.source_sha256 if readable else "",
                        editorial_note=row.editorial_note if readable else "",
                        rights_restricted=not readable,
                        current_source_available=available,
                        correction=None
                        if correction is None
                        else dict(
                            reason=correction.reason if readable and previous_readable else "",
                            previous_id=str(correction.previous_id),
                            previous_revision=correction.previous.answer.revision,
                            previous_source=correction.previous.source
                            if previous_readable
                            else None,
                        ),
                    )
                )
            history.append(
                dict(
                    answer_id=str(answer.pk),
                    revision=answer.revision,
                    evidence_version=answer.evidence_version,
                    created_at=answer.created_at,
                    subject_id=answer.subject_id,
                    citations=rows,
                )
            )
        return dict(revisions=history, next_before=page[19].revision if len(page) > 20 else None)
