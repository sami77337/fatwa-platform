"""Canonical source adapters. Index rows are never an independent permission source."""

from dataclasses import dataclass

from django.apps import apps

from apps.casework import services as cases
from apps.casework.models import AnswerRevision, Case, CaseEvidence, CaseSource
from apps.research_workspace import services as research
from apps.research_workspace.rights import Resource, allowed
from apps.transcript_case_links.models import TranscriptLink

from .text import digest, normalize, text_digest

MAX_DOCUMENTS = 512


def frozen_rows(query):
    return tuple(tuple(None if value is None else str(value) for value in row) for row in query)


def fingerprint(case_ids):
    """Pure canonical heads, including absence; all referenced text rows are immutable."""
    recordings = ()
    if apps.is_installed("apps.public_answer_media"):
        from apps.public_answer_media.models import RecordingTranscript

        recordings = frozen_rows(
            RecordingTranscript.objects.filter(case_id__in=case_ids)
            .order_by("pk")
            .values_list("pk", "case_id", "part_id", "number", "digest", "text_sha256")
        )
    return (
        frozen_rows(
            Case.objects.filter(pk__in=case_ids)
            .order_by("pk")
            .values_list(
                "id",
                "public_ref",
                "revision",
                "evidence_version",
                "answer_revision",
                "approved_answer_id",
                "stage",
            )
        ),
        frozen_rows(
            CaseSource.objects.filter(case_id__in=case_ids)
            .order_by("case_id")
            .values_list(
                "case_id",
                "question_sha256",
            )
        ),
        frozen_rows(
            CaseEvidence.objects.filter(case_id__in=case_ids)
            .order_by("case_id", "version")
            .values_list(
                "id",
                "case_id",
                "version",
                "kind",
                "text_sha256",
            )
        ),
        frozen_rows(
            AnswerRevision.objects.filter(case_id__in=case_ids)
            .order_by("case_id", "revision")
            .values_list(
                "id",
                "case_id",
                "revision",
                "evidence_version",
                "text_sha256",
            )
        ),
        frozen_rows(
            TranscriptLink.objects.filter(case_id__in=case_ids)
            .order_by("pk")
            .values_list(
                "id",
                "case_id",
                "upload_id",
                "upload__sha256",
                "external_id",
                "evidence_id",
                "event_id",
                "question_sha256",
            )
        ),
        recordings,
    )


@dataclass(frozen=True)
class Document:
    kind: str
    source_id: str
    pin: dict
    text: str
    label: str

    @property
    def segment_url(self):
        if self.kind == "RECORDING_TRANSCRIPT":
            return (
                f"/casework/staff/recording-transcripts/{self.source_id}"
                f"/segments/{self.pin['segment_index']}/"
            )
        return ""

    @property
    def key(self):
        return digest(self.pin)

    @property
    def normalized(self):
        return normalize(self.text)

    def manifest_entry(self):
        return {
            "kind": self.kind,
            "source_id": self.source_id,
            "pin": self.pin,
            "derived_sha256": text_digest(self.normalized),
        }


def _document(case, kind, source_id, text, source_sha256, version, label, **extra):
    cases._text(text)
    pin = {
        "kind": kind,
        "case_id": str(case.pk),
        "source_id": str(source_id),
        "source_sha256": source_sha256,
        "text_sha256": text_digest(text),
        "version": version,
        **extra,
    }
    return Document(kind, str(source_id), pin, text, label)


def read(case, actor, provider, *, transcripts_available):
    source = CaseSource.objects.get(case=case)
    result = [
        _document(
            case,
            "QUESTION",
            case.pk,
            source.original_question,
            source.question_sha256,
            1,
            "السؤال الأصلي المحفوظ",
        )
    ]
    links = list(
        TranscriptLink.objects.filter(case=case)
        .select_related("upload")
        .order_by("evidence__version")
    )
    # Transcript attachment copies a question into CaseEvidence. That does not
    # turn it into an ordinary requester follow-up or bypass source text rights.
    linked_evidence = {row.evidence_id for row in links}
    for row in CaseEvidence.objects.filter(case=case, version__gt=1).order_by("version"):
        if row.pk not in linked_evidence:
            result.append(
                _document(
                    case,
                    "FOLLOWUP",
                    row.pk,
                    row.text,
                    row.text_sha256,
                    row.version,
                    "تعقيب محفوظ من وقائع القضية",
                )
            )
    answer = AnswerRevision.objects.filter(case=case).order_by("-revision").first()
    if answer and answer.evidence_version == case.evidence_version:
        approved = case.approved_answer_id == answer.pk
        result.append(
            _document(
                case,
                "ANSWER",
                answer.pk,
                answer.text,
                answer.text_sha256,
                answer.revision,
                "الجواب الحالي المعتمد بشريًا" if approved else "مسودة الجواب الحالية؛ غير معتمدة",
                evidence_version=answer.evidence_version,
                approved=approved,
            )
        )
    if transcripts_available:
        for row in links:
            resource = Resource(
                "TRANSCRIPT",
                str(row.pk),
                research._digest([row.upload.sha256, row.question_sha256]),
            )
            if not all(
                allowed(actor, provider, case, action, resource)
                for action in ("DISCOVER", "SEARCH_TEXT", "READ_TEXT")
            ):
                continue
            try:
                actual, entry = research._transcript(
                    case, actor, provider, str(row.pk), "READ_TEXT"
                )
            except cases.CaseConflict as exc:
                if str(exc) in {"knowledge_action_denied", "research_resource_not_authorized"}:
                    continue
                raise
            if actual != resource:
                raise cases.CaseConflict("search_source_changed")
            for label, segment in (("QUESTION", entry.question), ("ANSWER", entry.answer)):
                if segment is None:
                    continue
                result.append(
                    _document(
                        case,
                        "TRANSCRIPT",
                        row.pk,
                        segment.text,
                        resource.sha256,
                        1,
                        "نص من التفريغ المتاح؛ ليس جوابًا معتمدًا للقضية",
                        upload_id=str(row.upload_id),
                        upload_sha256=row.upload.sha256,
                        source_record_id=entry.source_id,
                        segment=label,
                        segment_id=segment.segment_id,
                        segment_sha256=segment.sha256,
                        start_ms=segment.start_ms,
                        end_ms=segment.end_ms,
                    )
                )
    if len(result) > MAX_DOCUMENTS:
        raise cases.CaseConflict("search_document_capacity")
    return result
