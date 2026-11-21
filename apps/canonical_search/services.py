"""Real PostgreSQL FTS/fuzzy retrieval with current authorization before ranking."""

import uuid
from contextlib import contextmanager

from django.contrib.postgres.search import SearchQuery, SearchRank, TrigramWordSimilarity
from django.db import connection
from django.db.models import FloatField, Value
from django.db.models.functions import Least

from apps.casework import services as cases
from apps.platform_recovery.integration import mutation_service

from . import policy, sources
from .models import SearchDocument, SearchGeneration
from .text import FUZZY_THRESHOLD, PROFILE, canonical, digest, normalize, query, text_digest

PAGE_SIZE = 20
MAX_RESULTS = 160
KINDS = {"ALL", "QUESTION", "FOLLOWUP", "ANSWER", "TRANSCRIPT", "RECORDING_TRANSCRIPT"}


def _body(row):
    excluded = {"canonical_payload", "digest", "transaction_id", "created_at", "vector"}
    result = {}
    for field in row._meta.fields:
        if field.name not in excluded:
            value = getattr(row, field.attname)
            result[field.attname] = str(value) if isinstance(value, uuid.UUID) else value
    return result


def _seal(row):
    row.canonical_payload = canonical(_body(row))
    row.digest = text_digest(row.canonical_payload)
    row.save(force_insert=True)
    row.refresh_from_db()
    return row


def _verify(row):
    if row.canonical_payload != canonical(_body(row)) or row.digest != text_digest(
        row.canonical_payload
    ):
        raise cases.CaseConflict("search_index_integrity")


def _generation(case, available):
    """A generation may contain revoked rows; only current allowed IDs reach SQL."""
    row = SearchGeneration.objects.filter(case=case).order_by("-number").first()
    if row is None:
        return None, {}, "MISSING"
    _verify(row)
    if row.profile != PROFILE or row.source_fingerprint != digest(sources.fingerprint([case.pk])):
        return row, {}, "STALE"
    documents = list(SearchDocument.objects.filter(generation=row).order_by("ordinal"))
    if not isinstance(row.manifest, list) or len(documents) != len(row.manifest):
        raise cases.CaseConflict("search_index_integrity")
    if len({digest(item["pin"]) for item in row.manifest}) != len(row.manifest):
        raise cases.CaseConflict("search_index_integrity")
    usable = {}
    for ordinal, (document, manifest) in enumerate(zip(documents, row.manifest, strict=True), 1):
        _verify(document)
        if (
            document.ordinal != ordinal
            or document.kind != manifest["kind"]
            or str(document.source_id) != manifest["source_id"]
            or document.pin != manifest["pin"]
            or text_digest(document.original_text) != document.pin["text_sha256"]
            or normalize(document.original_text) != document.normalized_text
            or text_digest(document.normalized_text) != manifest["derived_sha256"]
        ):
            raise cases.CaseConflict("search_index_integrity")
        key = digest(document.pin)
        if key in available:
            source = available[key]
            if source.manifest_entry() != manifest or source.text != document.original_text:
                raise cases.CaseConflict("search_index_source_mismatch")
            usable[str(document.pk)] = source
    # A newly granted source is not silently omitted. Ask for an explicit rebuild
    # when the current generation lacks any currently eligible source.
    if {source.key for source in usable.values()} != set(available):
        return row, {}, "STALE"
    return row, usable, "CURRENT"


def _case_data(context, case):
    available = {row.key: row for row in context.read(case)}
    generation, usable, state = _generation(case, available)
    return (
        generation,
        usable,
        {
            "case_id": str(case.pk),
            "case_ref": case.public_ref,
            "revision": case.revision,
            "evidence_version": case.evidence_version,
            "generation": generation.number if generation else 0,
            "generation_id": str(generation.pk) if generation else "",
            "state": state,
        },
    )


def desk_in_context(context, *, case_id):
    case = context.cases[str(case_id)]
    generation, usable, result = _case_data(context, case)
    result.update(
        profile=PROFILE,
        available_documents=len(usable),
        built_at=generation.created_at if generation else None,
    )
    return result


@mutation_service
def desk(**base):
    with policy.boundary(**base) as context:
        return desk_in_context(context, case_id=base["case_id"])


@mutation_service
def rebuild(
    *, expected_revision, expected_evidence_version, expected_generation, request_key, **base
):
    request_key = cases._uuid(request_key)
    with policy.boundary(**base, action="REBUILD") as context:
        case = context.cases[str(base["case_id"])]
        if (
            type(expected_revision) is not int
            or type(expected_evidence_version) is not int
            or (case.revision, case.evidence_version)
            != (expected_revision, expected_evidence_version)
            or type(expected_generation) is not int
            or expected_generation < 0
        ):
            raise cases.CaseConflict("search_rebuild_stale")
        documents = context.read(case)
        manifest = [row.manifest_entry() for row in documents]
        source_fingerprint = digest(sources.fingerprint([case.pk]))
        previous = SearchGeneration.objects.filter(case=case).order_by("-number").first()
        replay = SearchGeneration.objects.filter(
            case=case,
            provider_id=base["provider"].provider_id,
            subject_id=base["subject_id"],
            request_key=request_key,
        ).first()
        if replay:
            _verify(replay)
            if previous is None or previous.pk != replay.pk:
                raise cases.CaseConflict("search_request_superseded")
            if (
                replay.source_fingerprint != source_fingerprint
                or replay.manifest != manifest
                or replay.profile != PROFILE
            ):
                raise cases.CaseConflict("search_request_conflict")
            return {"generation_id": str(replay.pk), "number": replay.number, "created": False}
        if expected_generation != (previous.number if previous else 0):
            raise cases.CaseConflict("search_rebuild_stale")
        if previous:
            _verify(previous)
            if (
                previous.source_fingerprint == source_fingerprint
                and previous.manifest == manifest
                and previous.profile == PROFILE
            ):
                _generation(case, {row.key: row for row in documents})
                return {
                    "generation_id": str(previous.pk),
                    "number": previous.number,
                    "created": False,
                }
        number = previous.number + 1 if previous else 1
        if number > 128:
            raise cases.CaseConflict("search_generation_capacity")
        generation = _seal(
            SearchGeneration(
                case=case,
                number=number,
                profile=PROFILE,
                source_fingerprint=source_fingerprint,
                manifest=manifest,
                case_revision=case.revision,
                evidence_version=case.evidence_version,
                provider_id=base["provider"].provider_id,
                subject_id=context.actor.subject_id,
                auth_epoch=context.actor.auth_epoch,
                request_key=request_key,
            )
        )
        saved = []
        for ordinal, row in enumerate(documents, 1):
            saved.append(
                _seal(
                    SearchDocument(
                        generation=generation,
                        ordinal=ordinal,
                        kind=row.kind,
                        source_id=cases._uuid(row.source_id),
                        pin=row.pin,
                        original_text=row.text,
                        normalized_text=row.normalized,
                    )
                )
            )
        context.wrote(generation, saved)
        return {"generation_id": str(generation.pk), "number": generation.number, "created": True}


@contextmanager
def fuzzy_threshold():
    """Bounded local operator threshold; restore caller state even on SQL failure."""
    with connection.cursor() as cursor:
        # CREATE EXTENSION survives restore; loading its C module is per-backend.
        # A fresh reader may not know this GUC until one real pg_trgm function
        # runs. Load it without modifying settings before preserving its value.
        cursor.execute("SELECT word_similarity('', '')")
        cursor.execute("SHOW pg_trgm.word_similarity_threshold")
        previous = cursor.fetchone()[0]
        try:
            cursor.execute(
                "SELECT set_config('pg_trgm.word_similarity_threshold', %s, true)",
                [FUZZY_THRESHOLD],
            )
            yield
        finally:
            # A failed statement aborts its transaction. The enclosing atomic
            # rollback restores SET LOCAL without executing in that failed unit.
            if not connection.needs_rollback:
                cursor.execute(
                    "SELECT set_config('pg_trgm.word_similarity_threshold', %s, true)", [previous]
                )


def _queryset(ids, value, mode):
    normalized, tokens = query(value, mode)
    rows = SearchDocument.objects.filter(pk__in=ids)
    if mode == "LITERAL":
        return rows.filter(original_text__contains=value).annotate(
            score=Value(1.0, output_field=FloatField())
        )
    if mode == "FTS":
        expression = SearchQuery(normalized, config="simple", search_type="plain")
        return rows.filter(vector=expression).annotate(
            score=SearchRank("vector", expression, cover_density=True)
        )
    scores = [TrigramWordSimilarity(token, "normalized_text") for token in tokens]
    for token in tokens:
        rows = rows.filter(normalized_text__trigram_word_similar=token)
    return rows.annotate(score=scores[0] if len(scores) == 1 else Least(*scores))


def search_in_context(context, *, value, mode="FTS", kind="ALL", page=1):
    query(value, mode)
    if kind not in KINDS or type(page) is not int or not 1 <= page <= MAX_RESULTS // PAGE_SIZE:
        raise cases.CaseConflict("search_query_invalid")
    allowed, cases_by_document, statuses = {}, {}, []
    for case in context.cases.values():
        _, usable, status = _case_data(context, case)
        statuses.append(status)
        for identifier, source in usable.items():
            if kind == "ALL" or source.kind == kind:
                allowed[identifier] = source
                cases_by_document[identifier] = case
    rows = _queryset(list(allowed), value, mode).order_by(
        "-score", "generation__case_id", "ordinal", "pk"
    )
    if mode == "FUZZY":
        with fuzzy_threshold():
            matched = list(rows.values("id", "generation_id", "score")[: MAX_RESULTS + 1])
    else:
        matched = list(rows.values("id", "generation_id", "score")[: MAX_RESULTS + 1])
    limited = len(matched) > MAX_RESULTS
    matched = matched[:MAX_RESULTS]
    selected = matched[(page - 1) * PAGE_SIZE : page * PAGE_SIZE]
    result = []
    for row in selected:
        identifier = str(row["id"])
        source, case = allowed[identifier], cases_by_document[identifier]
        result.append(
            {
                "document_id": identifier,
                "generation_id": str(row["generation_id"]),
                "case_id": str(case.pk),
                "case_ref": case.public_ref,
                "kind": source.kind,
                "label": source.label,
                "pin": source.pin,
                "excerpt": source.text[:320],
                "segment_url": source.segment_url,
                "mode": mode,
            }
        )
    return {
        "results": result,
        "total": len(matched),
        "limited": limited,
        "page": page,
        "has_next": page * PAGE_SIZE < len(matched),
        "has_previous": page > 1,
        "indexes": statuses,
        "profile": PROFILE,
        "query": value,
        "mode": mode,
        "kind": kind,
    }


@mutation_service
def search(*, value, mode="FTS", kind="ALL", page=1, scope="CASE", **base):
    with policy.boundary(**base, action="SEARCH", scope=scope) as context:
        return search_in_context(context, value=value, mode=mode, kind=kind, page=page)


def open_in_context(context, *, case_id, generation_id, document_id):
    case = context.cases[str(case_id)]
    generation, usable, status = _case_data(context, case)
    identifier = str(cases._uuid(document_id))
    if (
        status["state"] != "CURRENT"
        or str(generation.pk) != str(cases._uuid(generation_id))
        or identifier not in usable
    ):
        raise cases.CaseConflict("search_result_stale_or_unavailable")
    source = usable[identifier]
    return {
        "case_ref": case.public_ref,
        "case_id": str(case.pk),
        "label": source.label,
        "text": source.text,
        "segment_url": source.segment_url,
        "pin": source.pin,
        "generation_id": str(generation.pk),
        "document_id": identifier,
    }


@mutation_service
def open_source(*, generation_id, document_id, **base):
    with policy.boundary(**base, action="OPEN") as context:
        return open_in_context(
            context, case_id=base["case_id"], generation_id=generation_id, document_id=document_id
        )
