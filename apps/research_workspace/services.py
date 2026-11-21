"""Case-scoped research composition. Existing sources/citations own all persistence."""

import json
import os
from dataclasses import asdict, fields
from hashlib import sha256

from django.conf import settings

from apps.answer_media import services as answers
from apps.answer_media.models import AnswerPart
from apps.case_attachments import services as attachments
from apps.case_attachments.models import CaseAttachment
from apps.case_citations import services as citations
from apps.casework import services as cases
from apps.delivery_queue import services as queue
from apps.editorial_search.query_terms import normalize_editorial_search
from apps.experimental_publication import services as publication
from apps.experimental_publication.models import PublicationEdition
from apps.knowledge_links import services as knowledge
from apps.knowledge_links.models import KnowledgeRevision
from apps.platform_recovery.integration import mutation_service
from apps.reference.models import ReferenceEdition
from apps.reference_links.resolution import Heading
from apps.reference_triage.services import ReferenceTriage
from apps.research_bridge.services import bridge_reference
from apps.transcript_case_links import services as transcripts
from apps.transcript_case_links.models import TranscriptLink

from .rights import Resource, allowed, require

KINDS = {"all", "REFERENCE", "TRANSCRIPT", "KNOWLEDGE", "MEDIA"}
MAX_RESULTS = 40


def _enabled():
    if (
        os.environ.get("FATWA_PRODUCTION") != "0"
        or getattr(settings, "FATWA_RESEARCH_WORKSPACE_ENABLED", False) is not True
    ):
        raise cases.CaseConflict("research_workspace_disabled")


def _digest(value):
    return sha256(queue._canonical(value)).hexdigest()


def _recheck(case, actor, provider):
    fresh = cases._identity(provider, actor.subject_id, case)
    if (fresh.auth_epoch, fresh.role, fresh.case_keys) != (
        actor.auth_epoch,
        actor.role,
        actor.case_keys,
    ):
        raise cases.CaseConflict("research_identity_changed")


def _source_resource(source, digest):
    return Resource(
        "REFERENCE",
        f"{source['edition_id']}:{source['source_row_id']}",
        digest,
        **{
            key: source[key]
            for key in (
                "edition_id",
                "source_namespace",
                "source_book_id",
                "edition_key",
                "source_archive_sha256",
                "source_input_sha256",
            )
        },
    )


def _edition_resource(edition):
    return Resource(
        "EDITION",
        str(edition.pk),
        edition.ingest_checksum,
        edition.pk,
        edition.work.source_namespace,
        edition.work.source_book_id,
        edition.edition_key,
        edition.source_archive_sha256,
        edition.source_input_sha256,
    )


def _bridge(source, *, catalog=None):
    """Recheck verified canonical catalog evidence with the existing strict bridge.

    The upstream citation resolver supplied these pins; no fixture triage, guessed
    identity, scientific assertion or full-book text is manufactured here.
    """
    evidence = {field.name: source[field.name] for field in fields(Heading)}
    identity = {
        key: source[key]
        for key in (
            "edition_id",
            "source_row_id",
            "source_namespace",
            "source_book_id",
            "edition_key",
            "source_archive_sha256",
            "source_input_sha256",
        )
    }
    original = source["heading_title"]
    result = bridge_reference(
        ReferenceTriage(
            ordinal=1,
            status="verified",
            label="مطابقة فهرس تقنية",
            raw_status="verified",
            contract_status="VERIFIED",
            explanation="Existing citation resolver evidence",
            reason_explanations=(),
            reasons=(),
            recovery="",
            original_identity=json.dumps(identity),
            verified_identity=json.dumps(identity),
            evidence=json.dumps(evidence),
            source_text=original,
            source_start=None,
            source_end=None,
            source_sha256=sha256(original.encode()).hexdigest(),
        ),
        catalog=catalog,
    )
    if result.status != "verified":
        raise cases.CaseConflict("research_catalog_identity_changed")


def _reference(case, actor, provider, identifier, action):
    try:
        edition_id, row_id = [int(value) for value in identifier.split(":")]
    except (ValueError, AttributeError) as exc:
        raise cases.CaseConflict("research_target_invalid") from exc
    item = citations._source(edition_id, row_id)
    resource = _source_resource(item["source"], item["source_sha256"])
    require(actor, provider, case, action, resource)
    _bridge(item["source"])
    require(actor, provider, case, action, resource)
    return resource, item


def _transcript(case, actor, provider, identifier, action):
    row = (
        TranscriptLink.objects.select_related("upload", "evidence", "event")
        .filter(
            pk=cases._uuid(identifier),
            case=case,
        )
        .first()
    )
    if row is None:
        raise cases.CaseConflict("research_target_unavailable")
    resource = Resource(
        "TRANSCRIPT", str(row.pk), _digest([row.upload.sha256, row.question_sha256])
    )
    require(actor, provider, case, action, resource)
    # Existing separate transcript permission remains mandatory.
    knowledge._permit(actor, provider, case, "OPEN_TRANSCRIPT", "TRANSCRIPT")
    raw = bytes(row.upload.bundle)
    if sha256(raw).hexdigest() != row.upload.sha256:
        raise cases.CaseConflict("transcript_binding_inconsistent")
    entry = next((e for e in transcripts._entries(raw) if e.external_id == row.external_id), None)
    if entry is None:
        raise cases.CaseConflict("transcript_binding_inconsistent")
    transcripts._check_link(row, entry)
    return resource, entry


def _media_resource(row):
    return Resource(
        "ATTACHMENT" if isinstance(row, CaseAttachment) else "ANSWER_MEDIA", str(row.pk), row.sha256
    )


def _media_rows(case):
    rows = list(CaseAttachment.objects.filter(case=case).order_by("created_at")[:40])
    answer = case.answers.order_by("-revision").first()
    if answer and answer.evidence_version == case.evidence_version:
        rows += list(
            AnswerPart.objects.filter(manifest__answer=answer, ordinal__gt=1).order_by("ordinal")
        )
    return rows


def _knowledge(case, actor, provider, identifier, action):
    row = (
        KnowledgeRevision.objects.select_related("publication")
        .filter(
            pk=cases._uuid(identifier),
            publication__case=case,
        )
        .first()
    )
    if row is None:
        raise cases.CaseConflict("research_target_unavailable")
    resource = Resource("KNOWLEDGE", str(row.pk), row.snapshot_sha256)
    require(actor, provider, case, action, resource)
    if row.transcript_id:
        _transcript(case, actor, provider, str(row.transcript_id), "READ_TEXT")
    if row.heading_id:
        _reference(
            case,
            actor,
            provider,
            f"{row.snapshot['source']['edition_id']}:{row.snapshot['source']['source_row_id']}",
            "READ_METADATA",
        )
    result = knowledge.open_material(
        publication_id=row.publication_id,
        revision_id=row.pk,
        subject_id=actor.subject_id,
        provider=provider,
        synthetic_fixtures_only=True,
    )
    # Existing open_material checks publication, relation approval and source pins.
    # Reading transcript text additionally needs this workspace's exact text grant.
    if row.transcript_id:
        _transcript(case, actor, provider, str(row.transcript_id), "READ_TEXT")
    if row.heading_id:
        _reference(
            case,
            actor,
            provider,
            f"{row.snapshot['source']['edition_id']}:{row.snapshot['source']['source_row_id']}",
            "READ_METADATA",
        )
    return resource, result


@mutation_service
def search(
    *,
    case_id,
    subject_id,
    provider,
    query="",
    kind="all",
    edition_id=None,
    printed_part="",
    printed_page=None,
    synthetic_fixtures_only=False,
):
    _enabled()
    if kind not in KINDS or type(query) is not str or len(query) > 80:
        raise cases.CaseConflict("research_query_invalid")
    cases._text(query, optional=True)
    if (
        type(printed_part) is not str
        or len(printed_part) > 100
        or any(ord(char) < 32 for char in printed_part)
        or (edition_id is not None and (type(edition_id) is not int or edition_id < 1))
        or (
            printed_page is not None
            and (type(printed_page) is not int or not 1 <= printed_page <= 999999999)
        )
    ):
        raise cases.CaseConflict("research_query_invalid")
    normalized = normalize_editorial_search(query)

    def matches(value):
        return all(token in normalize_editorial_search(value) for token in normalized.split())

    common = dict(
        case_id=case_id, subject_id=subject_id, provider=provider, synthetic_fixtures_only=True
    )
    with (
        queue.synthetic_queue_atomic(),
        cases._staff_case(case_id, subject_id, provider, synthetic_fixtures_only) as (case, actor),
        citations._projection_expiry_guard(),
    ):
        from apps.data_privacy.integration import staff as privacy

        privacy("CASE", case.pk, provider=provider, actor=actor, action="SEARCH")
        editions = [
            e
            for e in ReferenceEdition.objects.select_related("work")
            .filter(work__source_book_id="622")
            .order_by("pk")[:100]
            if allowed(actor, provider, case, "DISCOVER", _edition_resource(e))
        ]
        if edition_id is not None and edition_id not in {e.pk for e in editions}:
            raise cases.CaseConflict("research_edition_unavailable")
        results = []
        knowledge_sources = {}
        if kind in {"all", "REFERENCE"} and edition_id is not None:
            found = citations.search_sources(
                **common,
                query=query,
                edition_id=edition_id,
                printed_part=printed_part,
                printed_page=printed_page,
            )
            for item in found["results"]:
                source = item["source"]
                resource = _source_resource(source, item["source_sha256"])
                if allowed(actor, provider, case, "DISCOVER", resource):
                    results.append(
                        {
                            "resource": asdict(resource),
                            "kind": "REFERENCE",
                            "title": source["heading_title"],
                            "label": "عنوان فهرس؛ ليس متن الكتاب ولا فتوى",
                            "source": source,
                        }
                    )
        if kind in {"all", "TRANSCRIPT"}:
            for row in (
                TranscriptLink.objects.filter(case=case)
                .select_related("upload")
                .order_by("evidence__version")[:40]
            ):
                resource = Resource(
                    "TRANSCRIPT", str(row.pk), _digest([row.upload.sha256, row.question_sha256])
                )
                if not allowed(actor, provider, case, "DISCOVER", resource):
                    continue
                action = "SEARCH_TEXT" if query.strip() else "READ_METADATA"
                if not allowed(actor, provider, case, action, resource):
                    continue
                try:
                    _, entry = _transcript(case, actor, provider, str(row.pk), action)
                except cases.CaseConflict as exc:
                    if str(exc) in {"knowledge_authority_required", "knowledge_action_denied"}:
                        continue
                    raise
                if matches(
                    entry.question.text
                    + " "
                    + (entry.answer.text if entry.answer else "")
                    + " "
                    + entry.source_id
                ):
                    results.append(
                        {
                            "resource": asdict(resource),
                            "kind": "TRANSCRIPT",
                            "title": "سؤال من التفريغ المرتبط " + entry.source_id,
                            "label": "نص تفريغ فعلي محفوظ؛ ليس جوابًا معتمدًا للقضية",
                            "start_ms": entry.question.start_ms,
                            "end_ms": entry.question.end_ms,
                        }
                    )
        if kind in {"all", "MEDIA"}:
            for row in _media_rows(case):
                resource = _media_resource(row)
                if allowed(actor, provider, case, "DISCOVER", resource) and matches(row.filename):
                    results.append(
                        {
                            "resource": asdict(resource),
                            "kind": resource.kind,
                            "title": row.filename,
                            "label": "وسيط القضية؛ لا تُفترض علاقة علمية بالدرس",
                            "media_type": row.media_type,
                        }
                    )
        if kind in {"all", "KNOWLEDGE"} and getattr(
            settings, "FATWA_KNOWLEDGE_LINKS_ENABLED", False
        ):
            eligible = publication.library(
                subject_id=subject_id, provider=provider, synthetic_fixtures_only=True
            )
            ids = PublicationEdition.objects.filter(
                case=case, pk__in=[r["id"] for r in eligible]
            ).values_list("pk", flat=True)
            for publication_id in list(ids)[:10]:
                linked = knowledge.browse(
                    publication_id=publication_id,
                    subject_id=subject_id,
                    provider=provider,
                    query=query,
                    synthetic_fixtures_only=True,
                )
                for link in linked["links"]:
                    row = KnowledgeRevision.objects.get(pk=link["id"])
                    resource = Resource("KNOWLEDGE", str(row.pk), row.snapshot_sha256)
                    if row.heading_id:
                        knowledge_sources[str(row.pk)] = _source_resource(
                            row.snapshot["source"], row.snapshot["source_sha256"]
                        )
                    if allowed(actor, provider, case, "DISCOVER", resource) and (
                        not row.heading_id
                        or allowed(
                            actor, provider, case, "DISCOVER", knowledge_sources[str(row.pk)]
                        )
                    ):
                        results.append(
                            {
                                "resource": asdict(resource),
                                "kind": "KNOWLEDGE",
                                "title": link["title"],
                                "label": "علاقة معتمدة بشريًا؛ الإتاحة تفحص عند الفتح",
                            }
                        )
        # Rights can be revoked during source parsing: recheck every returned item.
        results = [
            r
            for r in results[:MAX_RESULTS]
            if allowed(actor, provider, case, "DISCOVER", Resource(**r["resource"]))
            and (
                r["kind"] != "KNOWLEDGE"
                or r["resource"]["identifier"] not in knowledge_sources
                or allowed(
                    actor,
                    provider,
                    case,
                    "DISCOVER",
                    knowledge_sources[r["resource"]["identifier"]],
                )
            )
            and (
                r["kind"] != "TRANSCRIPT"
                or allowed(
                    actor,
                    provider,
                    case,
                    "SEARCH_TEXT" if query.strip() else "READ_METADATA",
                    Resource(**r["resource"]),
                )
            )
        ]
        _recheck(case, actor, provider)
        return {
            "public_ref": case.public_ref,
            "revision": case.revision,
            "evidence_version": case.evidence_version,
            "editions": [
                {"id": e.pk, "title": e.title, "book": e.work.title_original}
                for e in editions
                if allowed(actor, provider, case, "DISCOVER", _edition_resource(e))
            ],
            "results": results,
            "limited": len(results) == MAX_RESULTS,
        }


@mutation_service
def open_resource(*, case_id, subject_id, provider, resource, synthetic_fixtures_only=False):
    _enabled()
    if not isinstance(resource, Resource):
        raise cases.CaseConflict("research_target_invalid")
    with (
        queue.synthetic_queue_atomic(),
        cases._staff_case(case_id, subject_id, provider, synthetic_fixtures_only) as (case, actor),
        citations._projection_expiry_guard(),
    ):
        if resource.kind == "REFERENCE":
            fresh, result = _reference(case, actor, provider, resource.identifier, "READ_METADATA")
        elif resource.kind == "TRANSCRIPT":
            fresh, entry = _transcript(case, actor, provider, resource.identifier, "READ_TEXT")
            result = {
                "source_id": entry.source_id,
                "question": asdict(entry.question),
                "answer": asdict(entry.answer) if entry.answer else None,
                "source_sha256": entry.source_sha256,
                "input_sha256": entry.input_sha256,
            }
        elif resource.kind == "KNOWLEDGE":
            fresh, result = _knowledge(case, actor, provider, resource.identifier, "READ_METADATA")
        elif resource.kind in {"ATTACHMENT", "ANSWER_MEDIA"}:
            row = next((r for r in _media_rows(case) if _media_resource(r) == resource), None)
            if row is None:
                raise cases.CaseConflict("research_target_unavailable")
            fresh = _media_resource(row)
            require(actor, provider, case, "READ_MEDIA", fresh)
            result = (
                attachments.staff_read(
                    case_id=case.pk,
                    attachment_id=row.pk,
                    subject_id=subject_id,
                    provider=provider,
                    synthetic_fixtures_only=True,
                )
                if resource.kind == "ATTACHMENT"
                else answers.staff_read(
                    part_id=row.pk,
                    subject_id=subject_id,
                    provider=provider,
                    synthetic_fixtures_only=True,
                )
            )
            if sha256(result["raw"]).hexdigest() != resource.sha256:
                raise cases.CaseConflict("research_media_changed")
            require(actor, provider, case, "READ_MEDIA", fresh)
        else:
            raise cases.CaseConflict("research_target_invalid")
        if fresh != resource:
            raise cases.CaseConflict("research_source_changed")
        action = {
            "REFERENCE": "READ_METADATA",
            "TRANSCRIPT": "READ_TEXT",
            "KNOWLEDGE": "READ_METADATA",
        }.get(resource.kind, "READ_MEDIA")
        require(actor, provider, case, action, fresh)
        _recheck(case, actor, provider)
        return result


@mutation_service
def add_citation(
    *,
    case_id,
    subject_id,
    provider,
    resource,
    note,
    expected_revision,
    expected_evidence_version,
    synthetic_fixtures_only=False,
):
    """Append one exact reference through the existing versioned citation service."""
    _enabled()
    if not isinstance(resource, Resource) or resource.kind != "REFERENCE":
        raise cases.CaseConflict("research_reference_required")
    with (
        queue.synthetic_queue_atomic(),
        cases._staff_case(
            case_id,
            subject_id,
            provider,
            synthetic_fixtures_only,
            expected_revision=expected_revision,
            expected_evidence_version=expected_evidence_version,
        ) as (case, actor),
    ):
        fresh, _ = _reference(case, actor, provider, resource.identifier, "CITE")
        if fresh != resource:
            raise cases.CaseConflict("research_source_changed")
        previous = case.answers.order_by("-revision").first()
        if previous is None or previous.evidence_version != case.evidence_version:
            raise cases.CaseConflict("research_current_saved_answer_required")
        existing = citations.citations_for_locked_answer(previous)
        selections = []
        for item in existing:
            old = _source_resource(item["source"], item["source_sha256"])
            require(actor, provider, case, "CITE", old)
            selections.append(
                {
                    "edition_id": old.edition_id,
                    "source_row_id": item["source"]["source_row_id"],
                    "source_sha256": old.sha256,
                    "editorial_note": item["editorial_note"],
                }
            )
        selections.append(
            {
                "edition_id": resource.edition_id,
                "source_row_id": int(resource.identifier.split(":")[1]),
                "source_sha256": resource.sha256,
                "editorial_note": note,
            }
        )
        result = citations.save_cited_answer(
            case_id=case.pk,
            subject_id=subject_id,
            provider=provider,
            text=previous.text,
            selections=selections,
            expected_revision=expected_revision,
            expected_evidence_version=expected_evidence_version,
            synthetic_fixtures_only=True,
        )
        # A post-write revocation rolls back the canonical revision and cloned media.
        require(actor, provider, case, "CITE", fresh)
        for item in existing:
            require(
                actor,
                provider,
                case,
                "CITE",
                _source_resource(item["source"], item["source_sha256"]),
            )
        _recheck(case, actor, provider)
        return {
            "revision": result["revision"],
            "evidence_version": result["evidence_version"],
            "answer_revision": result["answers"][-1]["revision"],
        }
