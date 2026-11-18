"""V14 synthetic input/authorities and canonical inventory; never seeded decisions."""

import io
import json
import math
import struct
import wave
from dataclasses import replace
from hashlib import sha256
from pathlib import Path

from apps.arabic_search_eval.review import EvaluationAuthority
from apps.classification_review.authority import ClassificationAuthority, EditorialSimulationPolicy
from apps.experimental_publication.authority import PublicationAuthority
from tests.casework.v11_fixtures import Directory as PreviousDirectory
from tests.casework.v12_fixtures import APPROVED_TEXT as APPROVED_TEXT
from tests.casework.v13_fixtures import ExactRecordingRights as ExactRecordingRights

OUT = Path(".local/qa/v14/browser")
QUESTION = "سؤال صوتي اصطناعي لرحلة V14؛ لا صوت شخص حقيقي ولا حكم شرعي."
CLASSIFICATION_LABEL = "تصنيف V14 خاص للمراجعة"
CLASSIFICATION_REASON = "اقتراح اصطناعي من بيانات الفهرس، لا علاقة علمية من التشابه."
TIMED_REASON = "موضع بشري اصطناعي في أصل التسجيل، دون تفريغ أو اقتباس مولد."


class Directory(PreviousDirectory):
    """Fourth fixture actor has separate publication authority, never a new product role."""

    def resolve(self, subject_id):
        if subject_id == "synthetic-independent-publisher":
            return replace(super().resolve("synthetic-publisher"), subject_id=subject_id)
        return super().resolve(subject_id)

    def authenticate(self, credential):
        if credential == "N" * 64:
            return self.resolve("synthetic-independent-publisher")
        return super().authenticate(credential)


class PublicationPolicy(PublicationAuthority):
    def __init__(self, directory):
        self.directory = directory

    def permits(self, *, provider_id, subject_id, auth_epoch, case_ref, action):
        return (
            provider_id == self.directory.provider_id
            and subject_id in {"synthetic-publisher", "synthetic-independent-publisher"}
            and auth_epoch == "epoch-1"
            and case_ref in self.directory.refs
            and action in {"APPROVE", "WITHDRAW"}
        )


class EvaluationPolicy(EvaluationAuthority):
    def __init__(self, directory):
        self.directory = directory

    def permits(self, *, provider_id, subject_id, auth_epoch, case_ref, action):
        return (
            provider_id == self.directory.provider_id
            and auth_epoch == "epoch-1"
            and case_ref in self.directory.refs
            and (
                (subject_id == "synthetic-mufti" and action in {"VIEW", "PROPOSE"})
                or (subject_id == "synthetic-publisher" and action in {"VIEW", "APPROVE", "REJECT"})
            )
        )


class SimulationPolicy(EditorialSimulationPolicy):
    policy_id = "synthetic-v14-connected-classification-v1"

    def __init__(self, directory):
        self.directory = directory
        self.revision_ids = frozenset()

    def permits(self, *, provider_id, subject_id, auth_epoch, case_ref, revision_id, action):
        return (
            provider_id == self.directory.provider_id
            and auth_epoch == "epoch-1"
            and case_ref in self.directory.refs
            and revision_id in self.revision_ids
            and (
                (subject_id == "synthetic-mufti" and action in {"INSPECT", "PREPARE", "REVIEW"})
                or (
                    subject_id == "synthetic-independent-publisher"
                    and action in {"INSPECT", "APPROVE"}
                )
                or (subject_id == "synthetic-publisher" and action == "INSPECT")
            )
        )


def synthetic_files():
    """Two-page synthetic PDF with explicit printed labels; no real source material."""
    from pypdf import PdfWriter
    from pypdf.generic import DecodedStreamObject, DictionaryObject, NameObject

    from apps.private_media.fixtures import synthetic_files as previous_files

    writer = PdfWriter()
    for label in ("6", "7"):
        page = writer.add_blank_page(width=320, height=420)
        font = DictionaryObject(
            {
                NameObject("/Type"): NameObject("/Font"),
                NameObject("/Subtype"): NameObject("/Type1"),
                NameObject("/BaseFont"): NameObject("/Helvetica"),
            }
        )
        page[NameObject("/Resources")] = DictionaryObject(
            {NameObject("/Font"): DictionaryObject({NameObject("/F1"): writer._add_object(font)})}
        )
        stream = DecodedStreamObject()
        stream.set_data(
            ("BT /F1 16 Tf 30 360 Td (SYNTHETIC REVIEW PAGE " + label + ") Tj ET").encode("ascii")
        )
        page[NameObject("/Contents")] = writer._add_object(stream)
    output = io.BytesIO()
    writer.write(output)
    return [
        (name, mime, output.getvalue() if name == "synthetic.pdf" else raw)
        for name, mime, raw in previous_files()
    ]


def write_fake_microphone(path):
    """Only generated tones enter Chrome's fake audio device; never a real mic."""
    with wave.open(str(path), "wb") as sound:
        sound.setnchannels(1)
        sound.setsampwidth(2)
        sound.setframerate(48000)
        sound.writeframes(
            b"".join(
                struct.pack("<h", int(10000 * math.sin(i * 2 * math.pi * 440 / 48000)))
                for i in range(96000)
            )
        )


def bootstrap_catalog():
    """Catalog and fixture identities only: the browser must create the one case."""
    from apps.reference.ingest import ingest_catalog
    from apps.reference.models import ReferenceHeading
    from tests.reference.test_catalog import fixture

    spec, rows = fixture()
    spec = replace(spec, source_book_id="622")
    preview = ingest_catalog(spec, rows)
    edition = ingest_catalog(
        spec, rows, dry_run=False, expected_checksum=preview.checksum
    ).edition_id
    return edition, ReferenceHeading.objects.get(edition_id=edition, source_row_id=2).pk


class ClassificationPolicy(ClassificationAuthority):
    def __init__(self, directory):
        self.directory = directory

    def permits(self, *, provider_id, subject_id, auth_epoch, case_ref, action):
        return (
            provider_id == self.directory.provider_id
            and auth_epoch == "epoch-1"
            and case_ref in self.directory.refs
            and (
                (subject_id == "synthetic-mufti" and action in {"VIEW", "PROPOSE"})
                or (subject_id == "synthetic-independent-publisher" and action == "VIEW")
                or (
                    subject_id == "synthetic-publisher"
                    and action in {"VIEW", "APPROVE", "REJECT", "WITHDRAW"}
                )
            )
        )


def inventory(case_id):
    """One canonical case, every current/historical row, without a single-edition assumption.

    This is an isolated-test integrity inventory, not a public projection. No
    rights, answer or publication decision is created here. App-wide row hashes
    include all V14 review tables so a restore cannot omit review history merely
    because a visible current row still exists.
    """
    from django.apps import apps

    from apps.answer_media.models import AnswerManifest, AnswerPart, PrivateAnswerRelease
    from apps.arabic_search_eval.models import EvaluationDecision, EvaluationRevision
    from apps.case_attachments.models import CaseAttachment
    from apps.case_citations.models import AnswerCitation
    from apps.casework.models import AnswerRevision, Case, CaseEvidence
    from apps.classification_review.models import (
        ClassificationAction,
        ClassificationRevision,
        EditorialBinding,
    )
    from apps.composite_delivery.models import CompositeDelivery
    from apps.delivery_queue.models import DeliveryAttempt, DeliveryIntent, ProviderReceipt
    from apps.experimental_publication.models import PublicationAction, PublicationEdition
    from apps.knowledge_links.models import KnowledgeAction, KnowledgeRevision
    from apps.pdf_citations.models import PdfCitation, PdfCitationAction
    from apps.source_case_intake.models import EvidenceBinding, SourceReviewNote
    from apps.source_rights.models import RightsAction, RightsRevision, SourceRegistration
    from apps.timed_citations.models import TimedCitation, TimedCitationAction

    case = Case.objects.get(pk=case_id)
    assert Case.objects.count() == 1, "The connected journey must not create parallel cases"
    answer = case.approved_answer
    manifest = AnswerManifest.objects.get(answer=answer)
    publications = list(PublicationEdition.objects.filter(case=case).order_by("number"))
    assert publications, "An independently approved publication must exist before recovery"
    publication = publications[-1]
    delivery = CompositeDelivery.objects.select_related("decision").get(decision__case=case)
    assert publication.answer_id == delivery.decision.answer_id == answer.pk
    assert PrivateAnswerRelease.objects.get(manifest=manifest).decision_id == delivery.decision_id
    assert PublicationAction.objects.filter(edition=publication, action="APPROVE").exists()
    attachments = list(CaseAttachment.objects.filter(case=case).order_by("created_at"))
    parts = list(AnswerPart.objects.filter(manifest=manifest).order_by("ordinal"))
    historical = list(AnswerPart.objects.filter(manifest__answer__case=case).order_by("id"))
    assert all(p.original is None for p in historical if p.kind != "TEXT")
    assert all(a.original is None for a in attachments)

    def assets(rows):
        return [
            {
                "id": str(p.pk),
                "sha256": p.sha256,
                "storage_key": p.storage_key,
                "media_type": p.media_type,
            }
            for p in rows
        ]

    def ledger(model):
        return [
            {
                "id": str(row[model._meta.pk.attname]),
                "sha256": sha256(
                    json.dumps(row, sort_keys=True, default=str, separators=(",", ":")).encode()
                ).hexdigest(),
            }
            for row in model.objects.order_by(model._meta.pk.name).values()
        ]

    # Missing a required V14 app fails instead of silently dropping its tables.
    review_apps = (
        "source_case_intake",
        "source_rights",
        "timed_citations",
        "pdf_citations",
        "classification_review",
        "arabic_search_eval",
        "experimental_publication",
        "knowledge_links",
    )
    models = [model for label in review_apps for model in apps.get_app_config(label).get_models()]
    intents = DeliveryIntent.objects.filter(case_key=case.public_ref)
    return {
        "ledger": {model._meta.label: ledger(model) for model in models},
        "case_id": str(case.pk),
        "answer_id": str(answer.pk),
        "answer_revision": answer.revision,
        "evidence_version": case.evidence_version,
        "publication_id": str(publication.pk),
        "publications": [
            {
                "id": str(row.pk),
                "number": row.number,
                "category": row.category,
                "content_sha256": row.content_sha256,
            }
            for row in publications
        ],
        "attachments": assets(attachments),
        "parts": assets(parts),
        "historical_parts": assets(historical),
        "source_review": list(
            SourceReviewNote.objects.order_by("sequence").values_list("kind", flat=True)
        ),
        "timed": list(
            TimedCitation.objects.order_by("number").values(
                "number", "snapshot_sha256", "start_ms", "end_ms", "duration_ms"
            )
        ),
        "delivery": {
            "parts": list(intents.order_by("ordinal").values("ordinal", "state", "payload_sha256")),
            "attempts": DeliveryAttempt.objects.filter(intent__in=intents).count(),
            "receipts": ProviderReceipt.objects.filter(intent__in=intents).count(),
        },
        "counts": {
            "cases": Case.objects.count(),
            "evidence": CaseEvidence.objects.filter(case=case).count(),
            "source_bindings": EvidenceBinding.objects.filter(case=case).count(),
            "answers": AnswerRevision.objects.filter(case=case).count(),
            "citations": AnswerCitation.objects.filter(answer=answer).count(),
            "parts": len(parts),
            "attachments": len(attachments),
            "rights_sources": SourceRegistration.objects.filter(case=case).count(),
            "rights_revisions": RightsRevision.objects.filter(case=case).count(),
            "rights_approvals": RightsAction.objects.filter(action="APPROVE").count(),
            "source_review_notes": SourceReviewNote.objects.count(),
            "delivery_intents": intents.count(),
            "publications": len(publications),
            "publication_approvals": PublicationAction.objects.filter(
                edition__case=case, action="APPROVE"
            ).count(),
            "knowledge_links": KnowledgeRevision.objects.filter(publication__case=case).count(),
            "knowledge_approvals": KnowledgeAction.objects.filter(
                revision__publication__case=case, action="APPROVE"
            ).count(),
            "evaluation_revisions": EvaluationRevision.objects.count(),
            "evaluation_decisions": EvaluationDecision.objects.count(),
            "pdf_citations": PdfCitation.objects.count(),
            "pdf_confirmations": PdfCitationAction.objects.filter(action="CONFIRM").count(),
            "editorial_bindings": EditorialBinding.objects.count(),
            "timed_citations": TimedCitation.objects.count(),
            "timed_confirmations": TimedCitationAction.objects.filter(action="CONFIRM").count(),
            "classifications": ClassificationRevision.objects.count(),
            "classification_approvals": ClassificationAction.objects.filter(
                action="APPROVE"
            ).count(),
            "classification_rejections": ClassificationAction.objects.filter(
                action="REJECT"
            ).count(),
        },
    }
