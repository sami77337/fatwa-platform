"""Offline V10 fixtures: one canonical case and one unresolved source receipt.

No helper resolves the ambiguity, authors an answer, approves a ruling, sends a
message, or grants a production permission. Those decisions stay in the browser
journey and explicitly configured synthetic authorities.
"""

import json
from dataclasses import dataclass, replace

from apps.source_case_intake import services as source_intake
from apps.source_case_intake import simulators
from tests.casework.test_v7_browser import BrowserDirectory

QUESTION = "سؤال اصطناعي من المصدر لرحلة V10 المتصلة، دون بيانات حقيقية."
AMBIGUOUS = "تعقيب اصطناعي بلا علاقة رد صريحة؛ يختار المراجع البشري ربطه."
DRAFT = "نص جواب بشري اصطناعي للتجربة فقط، مرتبط بمرجع وتسجيل تجريبي."
PUBLIC_TEXT = "نسخة تحريرية اصطناعية للمكتبة المغلقة، بلا بيانات المصدر الخاصة."
PRIVATE_NOTE = "سبب داخلي اصطناعي للمراجعة البشرية، لا يظهر للسائل أو المكتبة."


class V10Directory(BrowserDirectory):
    """The source-review scope belongs only to this test's primary Mufti."""

    def resolve(self, subject_id):
        identity = super().resolve(subject_id)
        if identity is None:
            return None
        scope = identity.case_keys
        if subject_id == "synthetic-mufti":
            scope = scope | {source_intake.REVIEW_SCOPE}
        return replace(identity, case_keys=frozenset(scope))


@dataclass(frozen=True)
class SourceJourney:
    case_id: str
    public_ref: str
    token: str
    original_receipt_id: str
    pending_receipt_id: str
    original_bytes: bytes
    pending_bytes: bytes


def prepare_source_journey():
    """Persist a first event and ambiguous followup, without resolving it."""
    first = json.loads(simulators.telegram(number=1))
    first["message"]["text"] = QUESTION
    second = json.loads(simulators.telegram(number=2))
    second["message"]["text"] = AMBIGUOUS
    original_bytes, pending_bytes = simulators.raw(first), simulators.raw(second)
    context = simulators.context("telegram", account="synthetic-v10-account")
    original = source_intake.ingest(
        raw=original_bytes, context=context, synthetic_fixtures_only=True
    )
    pending = source_intake.ingest(raw=pending_bytes, context=context, synthetic_fixtures_only=True)
    if original["status"] != "CREATED" or not original["token"]:
        raise AssertionError("synthetic first-source case was not created")
    if (
        pending["status"] != "NEEDS_REVIEW"
        or pending["reason"] != "unthreaded_message_requires_review"
    ):
        raise AssertionError("ambiguous fixture bypassed source review")
    return SourceJourney(
        case_id=original["case_id"],
        public_ref=original["public_ref"],
        token=original["token"],
        original_receipt_id=original["receipt_id"],
        pending_receipt_id=pending["receipt_id"],
        original_bytes=original_bytes,
        pending_bytes=pending_bytes,
    )


def canonical_evidence(case_id, private_root):
    """Read exact canonical identities and counters before and after recovery."""
    from pathlib import Path

    from apps.answer_media.models import AnswerManifest, AnswerPart, PrivateAnswerRelease
    from apps.case_attachments.models import CaseAttachment
    from apps.case_citations.models import AnswerCitation
    from apps.casework.models import AnswerRevision, Case, CaseEvidence
    from apps.composite_delivery.models import CompositeDelivery
    from apps.delivery_queue.models import DeliveryIntent
    from apps.experimental_publication.models import PublicationEdition
    from apps.knowledge_links.models import KnowledgeAction, KnowledgeRevision
    from apps.source_case_intake.models import EvidenceBinding
    from apps.transcript_case_links.models import TranscriptLink

    case = Case.objects.get(pk=case_id)
    attachment = CaseAttachment.objects.get(case=case)
    manifest = AnswerManifest.objects.get(answer=case.approved_answer)
    publication = PublicationEdition.objects.get(case=case)
    delivery = CompositeDelivery.objects.select_related("decision").get(decision__case=case)
    parts = list(AnswerPart.objects.filter(manifest=manifest).order_by("ordinal"))
    return {
        "case_id": str(case.pk),
        "approved_answer_id": str(case.approved_answer_id),
        "attachment_id": str(attachment.pk),
        "publication_id": str(publication.pk),
        "part_ids": [str(part.pk) for part in parts],
        "counts": {
            "cases": Case.objects.count(),
            "source_bindings": EvidenceBinding.objects.filter(case=case).count(),
            "evidence": CaseEvidence.objects.filter(case=case).count(),
            "evidence_version": case.evidence_version,
            "transcripts": TranscriptLink.objects.filter(case=case).count(),
            "answer_revisions": AnswerRevision.objects.filter(case=case).count(),
            "citations": AnswerCitation.objects.filter(answer=case.approved_answer).count(),
            "parts": len(parts),
            "private_releases": PrivateAnswerRelease.objects.filter(manifest=manifest).count(),
            "same_publication_answer": publication.answer_id == case.approved_answer_id,
            "same_delivery_answer": delivery.decision.answer_id == case.approved_answer_id,
            "delivery_intents": DeliveryIntent.objects.count(),
            "knowledge_links": KnowledgeRevision.objects.filter(publication=publication).count(),
            "knowledge_approvals": KnowledgeAction.objects.filter(action="APPROVE").count(),
            "external_objects": len(list(Path(private_root).rglob("*.blob"))),
            "attachment_external": attachment.original is None
            and attachment.storage_backend == "private-filesystem-v1",
            "audio_external": parts[-1].original is None
            and parts[-1].storage_backend == "private-filesystem-v1",
        },
    }


def verify_restored():
    """Called only after django.setup() in a new process, never reuses source DB."""
    import os
    import sys

    from django.db import connection
    from django.test import override_settings

    from apps.answer_media import services as answers
    from apps.case_attachments import services as attachments
    from apps.casework import services as cases
    from apps.experimental_publication import services as publications
    from apps.knowledge_links import services as knowledge
    from apps.knowledge_links.models import KnowledgeRevision
    from apps.private_media.filesystem import FileSystemStorage
    from apps.private_media.fixtures import synthetic_files
    from tests.casework.test_v7_browser import BrowserPublicationAuthority
    from tests.casework.test_v9_browser import KnowledgePolicy

    spec = json.load(sys.stdin)
    assert connection.settings_dict["NAME"] == spec["database"]
    assert connection.settings_dict["NAME"] != spec["source_database"]
    storage = FileSystemStorage(spec["private_root"], synthetic_fixtures_only=True)
    assert os.path.realpath(spec["private_root"]) != os.path.realpath(spec["source_private_root"])
    directory = V10Directory()
    directory.refs = frozenset({spec["public_ref"]})
    files = {name: raw for name, _, raw in synthetic_files()}
    with override_settings(
        FATWA_PRIVATE_MEDIA_STORAGE=storage,
        FATWA_CASE_ATTACHMENTS_ENABLED=True,
        FATWA_CASE_CITATIONS_ENABLED=True,
        FATWA_ANSWER_MEDIA_ENABLED=True,
        FATWA_ANSWER_MEDIA_PRIVATE_ENABLED=True,
        FATWA_EXPERIMENTAL_PUBLICATION_ENABLED=True,
        FATWA_KNOWLEDGE_LINKS_ENABLED=True,
        FATWA_CASEWORK_IDENTITY_PROVIDER=directory,
        FATWA_EXPERIMENTAL_PUBLICATION_AUTHORITY=BrowserPublicationAuthority(directory),
        FATWA_KNOWLEDGE_LINKS_AUTHORITY=KnowledgePolicy(directory),
    ):
        assert (
            canonical_evidence(spec["expected"]["case_id"], spec["private_root"])
            == spec["expected"]
        )
        package = answers.requester_snapshot(token=spec["token"], synthetic_fixtures_only=True)[
            "package"
        ]
        assert package["answer_id"] == spec["expected"]["approved_answer_id"]
        assert package["approved"]
        assert (
            attachments.requester_read(
                token=spec["token"],
                attachment_id=spec["expected"]["attachment_id"],
                synthetic_fixtures_only=True,
            )["raw"]
            == files["synthetic.txt"]
        )
        audio = next(part for part in package["parts"] if part["kind"] == "AUDIO")
        assert (
            answers.requester_read(
                token=spec["token"], part_id=audio["id"], synthetic_fixtures_only=True
            )["raw"]
            == files["synthetic.wav"]
        )
        visible = publications.library(
            subject_id="synthetic-publisher", provider=directory, synthetic_fixtures_only=True
        )
        assert [row["id"] for row in visible] == [spec["expected"]["publication_id"]]
        for relation in KnowledgeRevision.objects.all():
            assert knowledge.open_material(
                publication_id=str(relation.publication_id),
                revision_id=str(relation.pk),
                subject_id="synthetic-publisher",
                provider=directory,
                synthetic_fixtures_only=True,
            )
        for authority in (None, V10Directory()):
            with override_settings(FATWA_CASEWORK_IDENTITY_PROVIDER=authority):
                try:
                    answers.requester_snapshot(token=spec["token"], synthetic_fixtures_only=True)
                except cases.CaseConflict:
                    pass
                else:
                    raise AssertionError(
                        "restoration must not recreate an absent scope or identity"
                    )
    print("V10_RESTORED_IDENTITIES_BYTES_LINKS_AND_DENIALS_PASS")
