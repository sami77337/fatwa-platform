"""Closed source identities; never accept an arbitrary Django model from a form."""

import json
import uuid
from dataclasses import dataclass
from hashlib import sha256

from django.apps import apps

LEVELS = ("PUBLIC", "INTERNAL", "CONFIDENTIAL", "RESTRICTED")
ACTIONS = frozenset(
    {"READ", "SEARCH", "EXPORT", "PUBLISH", "AI", "VIEW_CLASSIFICATION", "CLASSIFY"}
)

# kind: (model, immutable original/version digest, optional canonical case path).
# A case label protects its private envelope. Child sources and public copies
# have their own labels; assigning PUBLIC to a case cannot classify a child.
TARGETS = {
    "CASE": ("casework.Case", "source__question_sha256", "pk"),
    "ANSWER": ("casework.AnswerRevision", "text_sha256", "case_id"),
    "ATTACHMENT": ("case_attachments.CaseAttachment", "sha256", "case_id"),
    "ANSWER_PART": ("answer_media.AnswerPart", "sha256", "manifest__answer__case_id"),
    "LIBRARY_VERSION": ("research_library.LibraryVersion", "digest", "item__case_id"),
    "SOURCE_VERSION": ("source_rights.SourceVersion", "sha256", "transcript__case_id"),
    "SOURCE_RECEIPT": ("source_case_intake.SourceReceipt", "sha256", "evidencebinding__case_id"),
    "TRANSCRIPT_LINK": ("transcript_case_links.TranscriptLink", "question_sha256", "case_id"),
    "RECORDING_TRANSCRIPT": ("public_answer_media.RecordingTranscript", "digest", "case_id"),
    "PUBLICATION": ("experimental_publication.PublicationEdition", "content_sha256", "case_id"),
    "PUBLIC_MEDIA": ("public_answer_media.PublicMediaEdition", "digest", "case_id"),
    "PUBLIC_KNOWLEDGE": ("public_knowledge.PublicRevision", "sha256", "series__case_id"),
    "PUBLIC_COLLECTION": ("public_collections.CollectionRevision", "sha256", "series__case_id"),
    "PUBLIC_TEACHING": ("public_teaching.TeachingVersion", "digest", "item__case_id"),
    "LESSON_VERSION": (
        "scholarly_links.LessonVersion",
        "sha256",
        "series_version__series__case_id",
    ),
    "KNOWLEDGE_REVISION": (
        "knowledge_links.KnowledgeRevision",
        "snapshot_sha256",
        "publication__case_id",
    ),
    "SERIES_VERSION": ("scholarly_links.SeriesVersion", "sha256", "series__case_id"),
}


def digest(value):
    return sha256(
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


@dataclass(frozen=True, slots=True)
class Target:
    kind: str
    identifier: str
    source_digest: str
    case_id: str | None
    case_ref: str


def locate(kind, identifier):
    """Resolve only original pins; callers authorize before returning metadata."""
    from apps.casework.services import CaseConflict

    try:
        if type(kind) is not str or kind not in TARGETS:
            raise ValueError
        identifier = str(uuid.UUID(str(identifier)))
        label, hash_field, case_field = TARGETS[kind]
        model = apps.get_model(label)
        row = model.objects.filter(pk=identifier).values_list(hash_field, case_field).first()
        if row is None or type(row[0]) is not str or len(row[0]) != 64:
            raise ValueError
        case_id = str(row[1]) if row[1] else None
        case_ref = ""
        if case_id:
            case_ref = apps.get_model("casework.Case").objects.get(pk=case_id).public_ref
        return Target(
            kind,
            identifier,
            digest([kind, identifier, row[0], case_id]),
            case_id,
            case_ref,
        )
    except (LookupError, ValueError, TypeError) as exc:
        raise CaseConflict("privacy_target_unavailable") from exc
