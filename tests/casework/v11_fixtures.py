"""V11 synthetic bootstrap and canonical recovery inventory; no seeded approvals."""

import json
from dataclasses import replace
from hashlib import sha256
from pathlib import Path

from apps.pilot_workbench.fixtures import FixtureOperatorAuthority
from apps.source_rights.authority import SourceRightsAuthority
from tests.casework.v10_fixtures import V10Directory

QUESTION = "سؤال اصطناعي لرحلة V11؛ لا بيانات حقيقية أو حكم شرعي."
REPLY = "رد اصطناعي على الاستيضاح مع مرفق محفوظ في العملية نفسها."
DRAFT = "صياغة بشرية اصطناعية لرحلة V11، وليست فتوى أو نصًا من المرجع."
PRIVATE = "ملاحظة داخلية اصطناعية عن مراجعة المصدر والحقوق."
PUBLIC = "مادة تحريرية اصطناعية للمكتبة التجريبية فقط."
OUT = Path(".local/qa/v11/browser")


class Directory(V10Directory):
    def resolve(self, subject_id):
        if subject_id == "synthetic-outsider":
            return replace(
                super().resolve("synthetic-publisher"),
                subject_id=subject_id,
                case_keys=frozenset({"unrelated-synthetic-case"}),
            )
        return super().resolve(subject_id)

    def authenticate(self, credential):
        return (
            self.resolve("synthetic-outsider")
            if credential == "U" * 64
            else super().authenticate(credential)
        )


class RightsAuthority(SourceRightsAuthority):
    def __init__(self, directory):
        self.directory = directory
        self.enabled = True

    def permits(self, *, provider_id, subject_id, auth_epoch, case_ref, action, source_sha256):
        return (
            self.enabled
            and provider_id == self.directory.provider_id
            and case_ref in self.directory.refs
            and auth_epoch == "epoch-1"
            and (
                (subject_id == "synthetic-mufti" and action in {"VIEW", "REGISTER", "PROPOSE"})
                or (
                    subject_id == "synthetic-publisher"
                    and action in {"VIEW", "APPROVE", "REJECT", "REVOKE"}
                )
            )
        )


class OperatorAuthority(FixtureOperatorAuthority):
    def __init__(self, directory):
        self.directory = directory

    def permits(self, *, provider_id, subject_id, auth_epoch, case_ref, action):
        return (
            provider_id == self.directory.provider_id
            and subject_id == "synthetic-mufti"
            and auth_epoch == "epoch-1"
            and case_ref in self.directory.refs
            and action in {"OPEN", "AUTHORIZE_RETURN", "REPORT_PROVIDER"}
        )


def bootstrap():
    from apps.reference.ingest import ingest_catalog
    from apps.reference.models import ReferenceHeading
    from apps.source_case_intake import services, simulators
    from tests.reference.test_catalog import fixture

    raw = json.loads(simulators.telegram(number=1))
    raw["message"]["text"] = QUESTION
    source = services.ingest(
        raw=simulators.raw(raw),
        context=simulators.context("telegram"),
        synthetic_fixtures_only=True,
    )
    spec, rows = fixture()
    spec = replace(spec, source_book_id="622")
    preview = ingest_catalog(spec, rows)
    edition = ingest_catalog(
        spec, rows, dry_run=False, expected_checksum=preview.checksum
    ).edition_id
    return source, edition, ReferenceHeading.objects.get(edition_id=edition, source_row_id=2).pk


def inventory(case_id):
    """Stable logical IDs/hashes/order, including historical assets and new source audit."""
    from apps.answer_media.models import AnswerManifest, AnswerPart, PrivateAnswerRelease
    from apps.case_attachments.models import CaseAttachment
    from apps.case_citations.models import AnswerCitation
    from apps.casework.models import AnswerRevision, Case, CaseEvidence
    from apps.composite_delivery.models import CompositeDelivery
    from apps.delivery_queue.models import DeliveryIntent
    from apps.experimental_publication.models import PublicationAction, PublicationEdition
    from apps.knowledge_links.models import KnowledgeAction, KnowledgeRevision
    from apps.source_case_intake.models import EvidenceBinding, SourceReviewNote
    from apps.source_rights.models import (
        RightsAction,
        RightsRevision,
        SourceRegistration,
        SourceVersion,
    )

    case = Case.objects.get(pk=case_id)
    answer = case.approved_answer
    manifest = AnswerManifest.objects.get(answer=answer)
    publication = PublicationEdition.objects.get(case=case)
    delivery = CompositeDelivery.objects.select_related("decision").get(decision__case=case)
    attachments = list(CaseAttachment.objects.filter(case=case).order_by("created_at"))
    current_parts = list(AnswerPart.objects.filter(manifest=manifest).order_by("ordinal"))
    all_parts = list(AnswerPart.objects.filter(manifest__answer__case=case).order_by("id"))
    assert publication.answer_id == delivery.decision.answer_id == answer.pk
    assert PrivateAnswerRelease.objects.get(manifest=manifest).decision_id == delivery.decision_id
    assert all(p.original is None for p in all_parts if p.kind != "TEXT")
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
                "id": str(row["id"]),
                "sha256": sha256(
                    json.dumps(row, sort_keys=True, default=str, separators=(",", ":")).encode()
                ).hexdigest(),
            }
            for row in model.objects.order_by("id").values()
        ]

    return {
        "ledger": {
            model._meta.label: ledger(model)
            for model in (
                SourceReviewNote,
                SourceVersion,
                SourceRegistration,
                RightsRevision,
                RightsAction,
            )
        },
        "case_id": str(case.pk),
        "answer_id": str(answer.pk),
        "answer_revision": answer.revision,
        "evidence_version": case.evidence_version,
        "publication_id": str(publication.pk),
        "attachments": assets(attachments),
        "parts": assets(current_parts),
        "historical_parts": assets(all_parts),
        "source_review": list(
            SourceReviewNote.objects.order_by("sequence").values_list("kind", flat=True)
        ),
        "counts": {
            "cases": Case.objects.count(),
            "evidence": CaseEvidence.objects.filter(case=case).count(),
            "source_bindings": EvidenceBinding.objects.filter(case=case).count(),
            "answers": AnswerRevision.objects.filter(case=case).count(),
            "citations": AnswerCitation.objects.filter(answer=answer).count(),
            "parts": len(current_parts),
            "attachments": len(attachments),
            "rights_sources": SourceRegistration.objects.filter(case=case).count(),
            "rights_revisions": RightsRevision.objects.filter(case=case).count(),
            "rights_approvals": RightsAction.objects.filter(action="APPROVE").count(),
            "source_review_notes": SourceReviewNote.objects.count(),
            "delivery_intents": DeliveryIntent.objects.count(),
            "publication_approvals": PublicationAction.objects.filter(action="APPROVE").count(),
            "knowledge_links": KnowledgeRevision.objects.filter(publication=publication).count(),
            "knowledge_approvals": KnowledgeAction.objects.filter(action="APPROVE").count(),
        },
    }
