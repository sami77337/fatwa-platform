"""Real typed-reference seed/restore checks in the already inventoried answer tables."""

import uuid
from contextlib import contextmanager
from dataclasses import replace

from django.test import override_settings

from apps.casework import services as cases
from apps.experimental_publication.tests import Directory
from apps.research_library.test_support import bind_identity_snapshot

from . import services
from .models import AnswerManifest, AnswerPart

TABLES = (
    "answer_media_answermanifest",
    "answer_media_answerpart",
    "answer_media_privateanswerrelease",
)
FUNCTIONS = (
    "answer_media_manifest_guard",
    "answer_media_part_guard",
    "answer_media_metadata_guard",
    "answer_media_manifest_complete",
    "answer_media_release_guard",
)
TRIGGERS = FUNCTIONS
SOURCE_URL = "https://youtu.be/Recov3ry_01"


@contextmanager
def configuration(pins):
    directory = bind_identity_snapshot(Directory([pins["public_ref"]]))
    with override_settings(
        FATWA_ANSWER_MEDIA_ENABLED=True,
        FATWA_ANSWER_LINKS_ENABLED=True,
        FATWA_ANSWER_MEDIA_PRIVATE_ENABLED=True,
        FATWA_CASEWORK_IDENTITY_PROVIDER=directory,
    ):
        yield dict(
            case_id=pins["case_id"],
            subject_id="editor",
            provider=directory,
            synthetic_fixtures_only=True,
        )


def populate():
    identifier = "youtube-recovery-" + uuid.uuid4().hex
    receipt = cases.intake_case(
        original_question="سؤال استعادة اصطناعي",
        requester_id=identifier,
        source_event_id=identifier,
        idempotency_key=identifier,
        synthetic_fixtures_only=True,
    )
    pins = {key: str(receipt[key]) for key in ("case_id", "public_ref", "token")}
    with configuration(pins) as base:
        answer = services.save_multipart_answer(
            **base,
            text="مرجع خارجي اصطناعي",
            files=[],
            links=[{"url": SOURCE_URL, "label": "مرجع محفوظ لا يدعي إتاحة الفيديو"}],
            expected_revision=1,
            expected_evidence_version=1,
        )
        answer_id = answer["answers"][-1]["id"]
        cases.record_decision(
            **base,
            answer_id=answer_id,
            action="APPROVE",
            expected_revision=2,
            expected_evidence_version=1,
        )
        manifest = AnswerManifest.objects.get(answer_id=answer_id)
        services.release_private(
            **base,
            expected_revision=3,
            expected_evidence_version=1,
            manifest_sha256=manifest.sha256,
            confirmed=True,
        )
        part = AnswerPart.objects.get(manifest=manifest, kind="YOUTUBE_LINK")
        pins.update(
            answer_id=answer_id,
            manifest_sha256=manifest.sha256,
            part_id=str(part.pk),
            part_sha256=part.sha256,
            metadata=part.metadata,
        )
    return pins


def verify_restored(pins):
    denials = {}
    with configuration(pins) as base:
        manifest = AnswerManifest.objects.get(answer_id=pins["answer_id"])
        assert manifest.sha256 == pins["manifest_sha256"]
        result = services.requester_read(
            token=pins["token"], part_id=pins["part_id"], synthetic_fixtures_only=True
        )
        assert result["raw"] == SOURCE_URL.encode()
        assert result["sha256"] == pins["part_sha256"] and result["metadata"] == pins["metadata"]
        with override_settings(FATWA_CASEWORK_IDENTITY_PROVIDER=None):
            try:
                services.requester_read(
                    token=pins["token"], part_id=pins["part_id"], synthetic_fixtures_only=True
                )
                raise AssertionError("missing directory authorized a restored external reference")
            except cases.CaseConflict:
                denials["missing_authority"] = 1
        editor = base["provider"].identities["editor"]
        base["provider"].identities["editor"] = replace(editor, active=False)
        try:
            services.requester_read(
                token=pins["token"], part_id=pins["part_id"], synthetic_fixtures_only=True
            )
            raise AssertionError("inactive identity authorized a restored external reference")
        except cases.CaseConflict:
            denials["inactive_identity"] = 1
        finally:
            base["provider"].identities["editor"] = editor
        assert (
            services.staff_read(
                **{key: value for key, value in base.items() if key != "case_id"},
                part_id=pins["part_id"],
            )["raw"]
            == SOURCE_URL.encode()
        )
    return {
        "tables": TABLES,
        "denial_checks": denials,
        "denied_read_count": sum(denials.values()),
        "positive_reads_after_denial": True,
        "exact_external_reference_restored": True,
    }
