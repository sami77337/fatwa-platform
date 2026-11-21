"""Real cross-case precise citations survive through the last operational callbacks."""

import uuid
from dataclasses import replace

from django.test import TransactionTestCase, override_settings

from apps.answer_media.models import AnswerPart
from apps.casework import services as cases
from apps.precise_citations import services as citations
from apps.precise_citations import sources
from apps.precise_citations.authority import CitationAuthority
from apps.precise_citations.boundary import scope
from apps.precise_citations.models import CitationAnchor
from apps.public_answer_media.models import RecordingTranscript

from . import transcripts
from .boundary import digest
from .test_support import Directory, intake
from .transcript_test_support import (
    TRANSCRIPT_FEATURES,
    TranscriptFixture,
    grant_transcripts,
)


class ExactCitationAuthority(CitationAuthority):
    def __init__(self, refs):
        self.refs, self.denied, self.hook = set(refs), set(), None

    def projection_epoch(self):
        return digest((sorted(self.refs), sorted(self.denied)))

    def permits(self, **values):
        if self.hook:
            self.hook(values)
        return (
            values["provider_id"] == Directory.provider_id
            and values["subject_id"] in {"mufti", "citation-reviewer"}
            and values["auth_epoch"] == "epoch-1"
            and values["case_ref"] in self.refs
            and values["action"] in {"READ", "EDIT", "REVIEW", "CITE_SOURCE", "READ_SOURCE"}
            and values["action"] not in self.denied
        )


@override_settings(**{**TRANSCRIPT_FEATURES, "FATWA_PRECISE_CITATIONS_ENABLED": True})
class OperationalTranscriptSourceTests(TranscriptFixture, TransactionTestCase):
    def setUp(self):
        super().setUp()
        self.source = intake("organizer-transcript-exact-citation")
        self.receipts["citation_source"] = {
            key: self.source[key] for key in ("case_id", "public_ref")
        }
        for subject, actor in self.directory.identities.items():
            self.directory.identities[subject] = replace(
                actor, case_keys=actor.case_keys | {self.source["public_ref"]}
            )
        self.directory.identities["citation-reviewer"] = replace(
            self.directory.identities["mufti"], subject_id="citation-reviewer"
        )
        self.citations = ExactCitationAuthority(
            [self.target["public_ref"], self.source["public_ref"]]
        )
        configured = override_settings(FATWA_PRECISE_CITATIONS_AUTHORITY=self.citations)
        configured.enable()
        self.addCleanup(configured.disable)
        common = dict(
            case_id=self.source["case_id"],
            subject_id="mufti",
            provider=self.directory,
            synthetic_fixtures_only=True,
        )
        saved = cases.save_answer(
            **common,
            text="مرجع جواب اصطناعي محفوظ",
            expected_revision=1,
            expected_evidence_version=1,
        )
        source_answer = saved["answers"][-1]["id"]
        cases.record_decision(
            **common,
            answer_id=source_answer,
            action="APPROVE",
            expected_revision=2,
            expected_evidence_version=1,
        )
        common["case_id"] = self.target["case_id"]
        with scope(**common) as guard:
            pin, _ = sources.select(
                guard,
                "ANSWER:" + source_answer,
                owner_case_id=self.target["case_id"],
                location=sources.locator("TEXT", 0, 5),
            )
        text = "جواب جديد بإحالة موثقة وصوت أصلي محفوظ"
        result = citations.save(
            **common,
            text=text,
            selections=[citations.anchor(text, start=0, end=5, phrase=text[:5], source=pin)],
            expected_revision=3,
            expected_evidence_version=1,
            request_key=uuid.uuid4(),
            confirmed=True,
        )
        citations.review(
            **{**common, "subject_id": "citation-reviewer"},
            set_id=result["id"],
            action="APPROVE",
            note="مراجعة مستقلة للموضع والمصدر",
            expected_revision=4,
            expected_evidence_version=1,
            request_key=uuid.uuid4(),
            confirmed=True,
        )
        cases.record_decision(
            **common,
            answer_id=result["answer_id"],
            action="APPROVE",
            expected_revision=4,
            expected_evidence_version=1,
        )
        self.part = AnswerPart.objects.get(manifest__answer_id=result["answer_id"], kind="AUDIO")
        grant_transcripts(self.authority, self.domain, self.rights, self.target, self.part)
        self.originals, self.transcript_originals = (
            self.state(),
            self.immutable_transcript_sources(),
        )

    def save_values(self, **changes):
        return super().save_values(**{"expected_revision": 5, **changes})

    def test_real_reviewed_cross_case_citation_allows_actual_organizer_derivative(self):
        self.assertTrue(
            CitationAnchor.objects.filter(
                citation_set__answer_id=self.part.manifest.answer_id
            ).exists()
        )
        result = self.save_transcript()
        self.assertEqual(result["role"], "ORGANIZER")
        self.assertEqual(result["parts"][0]["id"], str(self.part.pk))
        self.assertEqual(self.immutable_transcript_sources(), self.transcript_originals)
        self.citations.denied.add("READ_SOURCE")
        with self.assertRaises(cases.CaseConflict):
            self.save_transcript()
        self.assertEqual(RecordingTranscript.objects.filter(part=self.part).count(), 1)

    def test_last_operational_callback_cannot_revoke_already_checked_citation(self):
        called = []
        with self.assertRaises(cases.CaseConflict):
            with transcripts.save(**self.common, **self.save_values()):

                def revoke(values):
                    called.append(values["action"])
                    self.citations.denied.add("READ_SOURCE")

                self.authority.hook = revoke
        self.authority.hook = None
        self.assertTrue(called)
        self.assertEqual(self.state(), self.originals)

    def test_final_citation_callback_cannot_revoke_previously_assembled_recording(self):
        called = []
        with self.assertRaises(cases.CaseConflict):
            with transcripts.audio_projection(
                **self.common,
                case_ref=self.target["public_ref"],
                part_id=self.part.pk,
                part_sha256=self.part.sha256,
            ) as result:
                self.assertTrue(result["raw"])

                def revoke(values):
                    called.append(values["action"])
                    self.rights.denied.add("operator")

                self.citations.hook = revoke
        self.citations.hook = None
        self.assertTrue(called)
        self.assertEqual(self.state(), self.originals)
