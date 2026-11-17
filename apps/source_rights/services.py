"""Rights ledger and guarded adapters over canonical citations and knowledge links.

Registration records identity only. Every usable grant requires a current reviewed
revision, explicit permitted use, expiration, matching source and existing access.
Rights never authorize a publication, private identity, or full original book text.
"""

import json
import os
from contextlib import contextmanager
from datetime import timedelta
from hashlib import sha256

from django.conf import settings
from django.db import connection
from django.utils import timezone

from apps.case_citations import services as citations
from apps.casework import services as cases
from apps.experimental_publication.models import PublicationEdition
from apps.knowledge_links import services as knowledge
from apps.knowledge_links.models import KnowledgeRevision
from apps.platform_recovery.integration import mutation_service
from apps.reference.models import ReferenceHeading
from apps.transcript_case_links import services as transcripts
from apps.transcript_case_links.models import TranscriptLink

from .authority import SourceRightsAuthority
from .models import RightsAction, RightsRevision, SourceRegistration, SourceVersion

USES = {"READ", "CITE", "RELATE", "PREVIEW_METADATA"}
PRIVATE_USES = {"READ", "RELATE"}


def _enabled():
    if (
        os.environ.get("FATWA_PRODUCTION") != "0"
        or getattr(settings, "FATWA_SOURCE_RIGHTS_ENABLED", False) is not True
        or not isinstance(
            getattr(settings, "FATWA_SOURCE_RIGHTS_AUTHORITY", None), SourceRightsAuthority
        )
    ):
        raise cases.CaseConflict("source_rights_disabled")


def _digest(value):
    return sha256(
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def _text(value):
    cases._text(value)
    if len(value) > 1000:
        raise cases.CaseConflict("rights_text_too_long")


def _permit(actor, provider, case, action, source_sha=""):
    _enabled()
    try:
        allowed = settings.FATWA_SOURCE_RIGHTS_AUTHORITY.permits(
            provider_id=provider.provider_id,
            subject_id=actor.subject_id,
            auth_epoch=actor.auth_epoch,
            case_ref=case.public_ref,
            action=action,
            source_sha256=source_sha,
        )
    except Exception as exc:
        raise cases.CaseConflict("source_rights_authority_unavailable") from exc
    if allowed is not True:
        raise cases.CaseConflict("source_rights_action_denied")


def _identity(case, actor, provider):
    _enabled()
    if cases._identity(provider, actor.subject_id, case).auth_epoch != actor.auth_epoch:
        raise cases.CaseConflict("source_rights_identity_changed")


@contextmanager
def _serial(case_id, synthetic_fixtures_only):
    """Serialize rights writes and delegated canonical mutations without nesting
    their pre-transaction ownership guards. Session lock always precedes case lock.
    Existing canonical services retain their own atomic/identity/version checks.
    """
    _enabled()
    cases._guard(synthetic_fixtures_only)
    key = str(cases._uuid(case_id))
    with connection.cursor() as cursor:
        cursor.execute("SELECT pg_advisory_lock(hashtextextended(%s, 311))", [key])
    try:
        yield
    finally:
        with connection.cursor() as cursor:
            cursor.execute("SELECT pg_advisory_unlock(hashtextextended(%s, 311))", [key])


def _reference(heading_id):
    if type(heading_id) is not int or not 1 <= heading_id <= 2**63 - 1:
        raise cases.CaseConflict("source_rights_target_invalid")
    heading = ReferenceHeading.objects.filter(pk=heading_id).first()
    if heading is None:
        raise cases.CaseConflict("source_rights_target_unavailable")
    citations._enabled()
    source = citations._source(heading.edition_id, heading.source_row_id)
    return {"kind": "TOC_METADATA", **source}, heading


def _transcript(link_id, case):
    link = (
        TranscriptLink.objects.filter(pk=cases._uuid(link_id), case=case)
        .select_related("upload", "evidence", "event")
        .first()
    )
    if link is None:
        raise cases.CaseConflict("source_rights_target_unavailable")
    raw = bytes(link.upload.bundle)
    if sha256(raw).hexdigest() != link.upload.sha256:
        raise cases.CaseConflict("source_rights_source_changed")
    entry = next((e for e in transcripts._entries(raw) if e.external_id == link.external_id), None)
    if entry is None:
        raise cases.CaseConflict("source_rights_source_changed")
    transcripts._check_link(link, entry)
    return {
        "kind": "PRIVATE_TRANSCRIPT",
        "link_id": str(link.pk),
        "bundle_sha256": link.upload.sha256,
        "source_id": entry.source_id,
        "source_sha256": entry.source_sha256,
        "question_sha256": entry.question.sha256,
        "pair_id": entry.pair_id,
        "start_ms": entry.question.start_ms,
        "end_ms": entry.question.end_ms,
    }, link


def _current_source(source, case):
    if source.sha256 != _digest(source.snapshot):
        raise cases.CaseConflict("source_rights_source_changed")
    current, _ = (
        _reference(source.heading_id)
        if source.heading_id
        else _transcript(source.transcript_id, case)
    )
    if current != source.snapshot:
        raise cases.CaseConflict("source_rights_source_changed")


def _source(source_id, case):
    source = SourceVersion.objects.filter(pk=cases._uuid(source_id)).first()
    if source is None or not SourceRegistration.objects.filter(source=source, case=case).exists():
        raise cases.CaseConflict("source_rights_target_unavailable")
    _current_source(source, case)
    return source


def _latest(source, case):
    return RightsRevision.objects.filter(source=source, case=case).order_by("-number").first()


def _state(revision):
    if revision is None:
        return "UNKNOWN"
    actions = set(revision.actions.values_list("action", flat=True))
    if "REVOKE" in actions:
        return "REVOKED"
    if "REJECT" in actions:
        return "REJECTED"
    if revision.valid_until <= timezone.now():
        return "EXPIRED"
    if "APPROVE" not in actions:
        return "PENDING"
    return "ALLOWED" if revision.uses else "RESTRICTED"


@mutation_service
def register(*, case_id, subject_id, provider, kind, target_id, synthetic_fixtures_only=False):
    with _serial(case_id, synthetic_fixtures_only):
        with cases._staff_case(case_id, subject_id, provider, synthetic_fixtures_only) as (
            case,
            actor,
        ):
            if kind == "TOC_METADATA":
                snapshot, target = _reference(target_id)
                query = {"heading": target}
            elif kind == "PRIVATE_TRANSCRIPT":
                snapshot, target = _transcript(target_id, case)
                query = {"transcript": target}
            else:
                raise cases.CaseConflict("source_rights_material_kind_invalid")
            digest = _digest(snapshot)
            _permit(actor, provider, case, "REGISTER", digest)
            _identity(case, actor, provider)
            source, _ = SourceVersion.objects.get_or_create(
                **query, defaults={"snapshot": snapshot, "sha256": digest, "kind": kind}
            )
            _current_source(source, case)
            if (
                not SourceRegistration.objects.filter(source=source, case=case).exists()
                and SourceRegistration.objects.filter(case=case).count() >= 64
            ):
                raise cases.CaseConflict("source_rights_registration_capacity")
            SourceRegistration.objects.get_or_create(
                source=source,
                case=case,
                defaults={
                    "subject_id": actor.subject_id,
                    "provider_id": provider.provider_id,
                    "auth_epoch": actor.auth_epoch,
                },
            )
            return {
                "id": str(source.pk),
                "kind": source.kind,
                "sha256": source.sha256,
                "state": _state(_latest(source, case)),
            }


@mutation_service
def propose(
    *,
    case_id,
    subject_id,
    provider,
    source_id,
    expected_number,
    uses,
    basis,
    note,
    ttl_minutes,
    synthetic_fixtures_only=False,
):
    _text(basis)
    _text(note)
    if (
        type(expected_number) is not int
        or not 0 <= expected_number < 64
        or type(ttl_minutes) is not int
        or not 1 <= ttl_minutes <= 1440
        or type(uses) not in (list, tuple)
        or len(uses) > 4
        or any(type(use) is not str for use in uses)
        or len(set(uses)) != len(uses)
        or set(uses) - USES
    ):
        raise cases.CaseConflict("source_rights_proposal_invalid")
    with _serial(case_id, synthetic_fixtures_only):
        with cases._staff_case(case_id, subject_id, provider, synthetic_fixtures_only) as (
            case,
            actor,
        ):
            source = _source(source_id, case)
            current = _latest(source, case)
            if (current.number if current else 0) != expected_number:
                raise cases.CaseConflict("source_rights_revision_changed")
            if source.kind == "PRIVATE_TRANSCRIPT" and set(uses) - PRIVATE_USES:
                raise cases.CaseConflict("private_transcript_publication_not_permitted")
            _permit(actor, provider, case, "PROPOSE", source.sha256)
            _identity(case, actor, provider)
            revision = RightsRevision.objects.create(
                source=source,
                case=case,
                number=expected_number + 1,
                uses=sorted(uses),
                basis=basis,
                note=note,
                valid_until=timezone.now() + timedelta(minutes=ttl_minutes),
                subject_id=actor.subject_id,
                provider_id=provider.provider_id,
                auth_epoch=actor.auth_epoch,
            )
            return {"id": str(revision.pk), "number": revision.number, "state": _state(revision)}


@mutation_service
def review(
    *,
    case_id,
    subject_id,
    provider,
    revision_id,
    action,
    confirmed,
    note,
    synthetic_fixtures_only=False,
):
    _text(note)
    if action not in {"APPROVE", "REJECT", "REVOKE"} or confirmed is not True:
        raise cases.CaseConflict("source_rights_explicit_review_required")
    with _serial(case_id, synthetic_fixtures_only):
        with cases._staff_case(case_id, subject_id, provider, synthetic_fixtures_only) as (
            case,
            actor,
        ):
            revision = (
                RightsRevision.objects.filter(pk=cases._uuid(revision_id), case=case)
                .select_related("source")
                .first()
            )
            if revision is None or _latest(revision.source, case).pk != revision.pk:
                raise cases.CaseConflict("source_rights_revision_changed")
            state = _state(revision)
            if state in {"REVOKED", "REJECTED"} or (
                action in {"APPROVE", "REJECT"} and state != "PENDING"
            ):
                raise cases.CaseConflict("source_rights_transition_invalid")
            if action == "APPROVE":
                _current_source(revision.source, case)
                if (revision.provider_id, revision.subject_id) == (
                    provider.provider_id,
                    actor.subject_id,
                ):
                    raise cases.CaseConflict("independent_rights_reviewer_required")
            _permit(actor, provider, case, action, revision.source.sha256)
            _identity(case, actor, provider)
            RightsAction.objects.create(
                revision=revision,
                action=action,
                note=note,
                subject_id=actor.subject_id,
                provider_id=provider.provider_id,
                auth_epoch=actor.auth_epoch,
            )
            return {"id": str(revision.pk), "state": _state(revision)}


def permits_reference_for_locked_case(*, case, source, usage):
    """Integrator hook, not an authorization entrypoint. Caller has already checked
    synthetic DB, acquired the canonical case lock and established its own access.
    Source is the exact {source, source_sha256} citation snapshot. False by default.
    Never authorizes publication, original book text, or replaces preview policy.
    """
    try:
        _enabled()
        if usage not in USES or not connection.in_atomic_block:
            return False
        heading = ReferenceHeading.objects.filter(
            edition_id=source["source"]["edition_id"],
            source_row_id=source["source"]["source_row_id"],
        ).first()
        record = SourceVersion.objects.filter(heading=heading).first() if heading else None
        if record is None or record.snapshot != {"kind": "TOC_METADATA", **source}:
            return False
        _current_source(record, case)
        revision = _latest(record, case)
        return _state(revision) == "ALLOWED" and usage in revision.uses
    except (cases.CaseConflict, KeyError, TypeError, ValueError):
        return False


def _require_reference(case, heading_id, usage):
    snapshot, heading = _reference(heading_id)
    source = {key: snapshot[key] for key in ("source", "source_sha256")}
    if not permits_reference_for_locked_case(case=case, source=source, usage=usage):
        raise cases.CaseConflict("current_source_rights_required")
    return source, heading


def _require_relation(case, kind, target_id):
    if kind == "REFERENCE":
        _require_reference(case, target_id, "RELATE")
    elif kind == "TRANSCRIPT":
        record = SourceVersion.objects.filter(transcript_id=cases._uuid(target_id)).first()
        if record is None:
            raise cases.CaseConflict("current_source_rights_required")
        _current_source(record, case)
        revision = _latest(record, case)
        if _state(revision) != "ALLOWED" or "RELATE" not in revision.uses:
            raise cases.CaseConflict("current_source_rights_required")
    else:
        raise cases.CaseConflict("source_rights_material_kind_invalid")


@mutation_service
def correct_citation(
    *,
    case_id,
    subject_id,
    provider,
    citation_id,
    target_id,
    note,
    expected_revision,
    expected_evidence_version,
    synthetic_fixtures_only=False,
):
    """Use the existing canonical cited-answer service; preserve other citations/media.
    The rights advisory lock serializes rights revocation with this delegated write.
    """
    _text(note)
    common = dict(
        case_id=case_id,
        subject_id=subject_id,
        provider=provider,
        synthetic_fixtures_only=synthetic_fixtures_only,
    )
    with _serial(case_id, synthetic_fixtures_only):
        with cases._staff_case(
            case_id,
            subject_id,
            provider,
            synthetic_fixtures_only,
            expected_revision=expected_revision,
            expected_evidence_version=expected_evidence_version,
        ) as (case, actor):
            _permit(actor, provider, case, "VIEW")
            answer = case.answers.order_by("-revision").first()
            if answer is None:
                raise cases.CaseConflict("case_answer_unavailable")
            rows = citations._citation_snapshots_for_locked_answer(answer)
            if str(citation_id) not in {row["id"] for row in rows}:
                raise cases.CaseConflict("case_citation_unavailable")
            selections, corrections = [], []
            for ordinal, row in enumerate(rows, 1):
                if row["id"] == str(citation_id):
                    source, _ = _require_reference(case, target_id, "CITE")
                    # The reason can quote the previous restricted source. Keep it
                    # in canonical correction history, not the new source's note.
                    editorial_note = ""
                    corrections.append(
                        {"ordinal": ordinal, "previous_id": row["id"], "reason": note}
                    )
                else:
                    source = {key: row[key] for key in ("source", "source_sha256")}
                    if not permits_reference_for_locked_case(
                        case=case, source=source, usage="CITE"
                    ):
                        raise cases.CaseConflict("current_source_rights_required")
                    editorial_note = row["editorial_note"]
                selections.append(
                    {
                        "edition_id": source["source"]["edition_id"],
                        "source_row_id": source["source"]["source_row_id"],
                        "source_sha256": source["source_sha256"],
                        "editorial_note": editorial_note,
                    }
                )
            text = answer.text
            _identity(case, actor, provider)
        return citations.save_cited_answer(
            **common,
            text=text,
            selections=selections,
            corrections=corrections,
            expected_revision=expected_revision,
            expected_evidence_version=expected_evidence_version,
        )


@mutation_service
def propose_relation(
    *,
    case_id,
    subject_id,
    provider,
    publication_id,
    kind,
    target_id,
    reason,
    replaces_id=None,
    synthetic_fixtures_only=False,
):
    with _serial(case_id, synthetic_fixtures_only):
        with cases._staff_case(case_id, subject_id, provider, synthetic_fixtures_only) as (
            case,
            actor,
        ):
            _permit(actor, provider, case, "VIEW")
            if not PublicationEdition.objects.filter(
                pk=cases._uuid(publication_id), case=case
            ).exists():
                raise cases.CaseConflict("publication_unavailable")
            _require_relation(case, kind, target_id)
            _identity(case, actor, provider)
        return knowledge.propose(
            publication_id=publication_id,
            subject_id=subject_id,
            provider=provider,
            kind=kind,
            target_id=target_id,
            reason=reason,
            replaces_id=replaces_id,
            synthetic_fixtures_only=synthetic_fixtures_only,
        )


@mutation_service
def act_on_relation(
    *,
    case_id,
    subject_id,
    provider,
    publication_id,
    relation_id,
    action,
    confirmed,
    synthetic_fixtures_only=False,
):
    with _serial(case_id, synthetic_fixtures_only):
        with cases._staff_case(case_id, subject_id, provider, synthetic_fixtures_only) as (
            case,
            actor,
        ):
            _permit(actor, provider, case, "VIEW")
            row = KnowledgeRevision.objects.filter(
                pk=cases._uuid(relation_id),
                publication_id=cases._uuid(publication_id),
                publication__case=case,
            ).first()
            if row is None:
                raise cases.CaseConflict("knowledge_revision_unavailable")
            if action == "APPROVE":
                _require_relation(
                    case,
                    "REFERENCE" if row.heading_id else "TRANSCRIPT",
                    row.heading_id or row.transcript_id,
                )
            _identity(case, actor, provider)
        return knowledge.act(
            publication_id=publication_id,
            revision_id=relation_id,
            subject_id=subject_id,
            provider=provider,
            action=action,
            confirmed=confirmed,
            synthetic_fixtures_only=synthetic_fixtures_only,
        )


@mutation_service
def desk(
    *, case_id, subject_id, provider, query="", edition_id=None, synthetic_fixtures_only=False
):
    _enabled()
    common = dict(
        case_id=case_id,
        subject_id=subject_id,
        provider=provider,
        synthetic_fixtures_only=synthetic_fixtures_only,
    )
    # Public services run outside the workspace transaction, preserving guards.
    found = citations._search_sources_for_rights_review(
        **common, query=query, edition_id=edition_id
    )
    transcript_rows = transcripts.read_links(**common)
    with cases._staff_case(case_id, subject_id, provider, synthetic_fixtures_only) as (case, actor):
        _permit(actor, provider, case, "VIEW")
        answer = case.answers.order_by("-revision").first()
        cited = citations._citation_snapshots_for_locked_answer(answer) if answer else []
        heading_ids = {
            ReferenceHeading.objects.get(
                edition_id=item["source"]["edition_id"],
                source_row_id=item["source"]["source_row_id"],
            ).pk
            for item in [*found["results"], *cited]
        }
        for item in found["results"]:
            item["target_id"] = ReferenceHeading.objects.get(
                edition_id=item["source"]["edition_id"],
                source_row_id=item["source"]["source_row_id"],
            ).pk
        record_ids = set(
            SourceRegistration.objects.filter(case=case).values_list("source_id", flat=True)
        )
        record_ids.update(
            SourceVersion.objects.filter(heading_id__in=heading_ids).values_list("pk", flat=True)
        )
        record_ids.update(
            SourceVersion.objects.filter(transcript__case=case).values_list("pk", flat=True)
        )
        records = []
        for source in SourceVersion.objects.filter(pk__in=record_ids).order_by("created_at"):
            revisions = list(
                RightsRevision.objects.filter(source=source, case=case).order_by("-number")
            )
            state = _state(revisions[0] if revisions else None)
            try:
                _current_source(source, case)
            except cases.CaseConflict:
                state = "SOURCE_CHANGED"
            records.append(
                {
                    "id": str(source.pk),
                    "kind": source.kind,
                    "snapshot": source.snapshot,
                    "sha256": source.sha256,
                    "state": state,
                    "number": revisions[0].number if revisions else 0,
                    "history": [
                        {
                            "id": str(r.pk),
                            "number": r.number,
                            "uses": r.uses,
                            "basis": r.basis,
                            "note": r.note,
                            "state": _state(r),
                            "actor": r.subject_id,
                            "valid_until": r.valid_until,
                            "actions": list(
                                r.actions.values("action", "note", "subject_id", "created_at")
                            ),
                        }
                        for r in revisions
                    ],
                }
            )
        published = list(
            PublicationEdition.objects.filter(case=case, actions__action="APPROVE").order_by(
                "-number"
            )
        )
        relations = list(
            KnowledgeRevision.objects.filter(publication__case=case).order_by("-created_at")
        )
        _identity(case, actor, provider)
        return {
            "case_ref": case.public_ref,
            "revision": case.revision,
            "evidence_version": case.evidence_version,
            "records": records,
            "search": found,
            "citations": cited,
            "query": query,
            "edition_id": edition_id,
            "transcripts": [
                {"id": r["id"], "label": "سؤال تفريغ خاص مرتبط بالقضية"} for r in transcript_rows
            ],
            "publications": [
                {"id": str(e.pk), "title": e.title, "number": e.number} for e in published
            ],
            "relations": [
                {
                    "id": str(r.pk),
                    "publication_id": str(r.publication_id),
                    "number": r.number,
                    "state": knowledge._state(r),
                    "kind": "REFERENCE" if r.heading_id else "TRANSCRIPT",
                    "target_id": r.heading_id or str(r.transcript_id),
                }
                for r in relations
            ],
        }


def permits_transcript_for_locked_case(*, case, transcript_id, usage):
    """Additional internal gate. Existing staff scope and OPEN_TRANSCRIPT permission
    remain mandatory; this hook can never permit anonymous/public transcript access.
    """
    try:
        _enabled()
        if not connection.in_atomic_block or usage not in PRIVATE_USES:
            return False
        source = SourceVersion.objects.filter(transcript_id=cases._uuid(transcript_id)).first()
        if source is None:
            return False
        _current_source(source, case)
        revision = _latest(source, case)
        return _state(revision) == "ALLOWED" and usage in revision.uses
    except (cases.CaseConflict, KeyError, TypeError, ValueError):
        return False
