"""Real reviewed citations remain live through the complete recording response."""

import uuid
from dataclasses import replace
from datetime import timedelta
from unittest.mock import patch

from django.test import Client, TransactionTestCase, override_settings
from django.utils import timezone

from apps.answer_media.models import AnswerPart
from apps.casework import services as cases
from apps.experimental_publication import services as publication
from apps.experimental_publication.models import PublicationEdition
from apps.library_preview import services as preview
from apps.library_preview.policy import PreviewPolicy, PublicationGrant
from apps.precise_citations import services as citations
from apps.precise_citations import sources
from apps.precise_citations.boundary import scope
from apps.precise_citations.test_support import FixtureAuthority as CitationAuthority

from . import public, views
from .test_support import FEATURES, MediaFixture, audio


@override_settings(**{**FEATURES, "FATWA_PRECISE_CITATIONS_ENABLED": True})
class MediaCitationTests(MediaFixture, TransactionTestCase):
    def setUp(self):
        super().setUp()
        key = uuid.uuid4().hex
        self.other_case = cases.intake_case(
            original_question="مصدر إحالة اصطناعي مستقل",
            source_event_id=key,
            requester_id="private-" + key,
            idempotency_key=key,
            synthetic_fixtures_only=True,
        )
        for subject, actor in self.directory.identities.items():
            self.directory.identities[subject] = replace(
                actor, case_keys=actor.case_keys | {self.other_case["public_ref"]}
            )
        other = {**self.common, "case_id": self.other_case["case_id"]}
        saved = cases.save_answer(
            **other, text="مرجع جواب اصطناعي", expected_revision=1, expected_evidence_version=1
        )
        target = saved["answers"][-1]["id"]
        cases.record_decision(
            **other,
            answer_id=target,
            action="APPROVE",
            expected_revision=2,
            expected_evidence_version=1,
        )
        self.citation_authority = CitationAuthority(
            self.receipt["public_ref"], self.other_case["public_ref"]
        )
        configured = override_settings(FATWA_PRECISE_CITATIONS_AUTHORITY=self.citation_authority)
        configured.enable()
        self.addCleanup(configured.disable)
        with scope(**self.common) as guard:
            pin, _ = sources.select(
                guard,
                "ANSWER:" + target,
                owner_case_id=self.common["case_id"],
                location=sources.locator("TEXT", 0, 5),
            )
        text = "جواب جديد مع إحالة موثقة وصوت أصلي محفوظ"
        record = citations.save(
            **self.common,
            text=text,
            selections=[citations.anchor(text, start=0, end=5, phrase=text[:5], source=pin)],
            expected_revision=3,
            expected_evidence_version=1,
            request_key=uuid.uuid4(),
            confirmed=True,
        )
        citations.review(
            **{**self.common, "subject_id": "other"},
            set_id=record["id"],
            action="APPROVE",
            note="راجعت الإحالة إلى الأصل المحدد",
            expected_revision=4,
            expected_evidence_version=1,
            request_key=uuid.uuid4(),
            confirmed=True,
        )
        self.answer_id = record["answer_id"]
        cases.record_decision(
            **self.common,
            answer_id=self.answer_id,
            action="APPROVE",
            expected_revision=4,
            expected_evidence_version=1,
        )
        self.part = AnswerPart.objects.get(manifest__answer_id=self.answer_id, kind="AUDIO")
        self.rights.pins.add(("ANSWER_MEDIA", str(self.part.pk), self.part.sha256))
        edition = publication.create_edition(
            **self.common,
            title="جواب منشور بإحالة موثقة",
            category="اصطناعي",
            body="النص العام المعتمد مع مصدر محمي مستقل.",
            expected_revision=5,
            expected_evidence_version=1,
        )
        publication.act(
            **{**self.common, "subject_id": "other"},
            edition_id=edition["id"],
            action="REVIEW",
            reviewed=True,
        )
        publication.act(
            **{**self.common, "subject_id": "publisher"},
            edition_id=edition["id"],
            action="APPROVE",
        )
        self.publication = PublicationEdition.objects.get(pk=edition["id"])
        self.preview_policy = PreviewPolicy(
            (PublicationGrant(str(self.publication.pk), self.publication.content_sha256),),
            (),
            timezone.now() + timedelta(minutes=30),
            True,
        )
        configured = override_settings(FATWA_LIBRARY_PREVIEW_POLICY=self.preview_policy)
        configured.enable()
        self.addCleanup(configured.disable)
        self.pins = dict(self.common, expected_revision=5, expected_evidence_version=1)
        self.released = self.release(self.review(self.save()))

    def test_cross_case_citation_and_recording_keep_exact_original_available(self):
        with public.recording_projection(self.released["id"]) as result:
            self.assertEqual(result["file"]["raw"], audio())
            self.assertEqual(result["publication"]["body"], self.publication.body)
        self.citation_authority.denied.add("READ_SOURCE")
        with self.assertRaises(preview.PreviewUnavailable):
            with public.publication_projection(self.publication.pk, include_media=False):
                self.fail("A denied citation must also deny the independently guarded text.")

    def test_final_citation_callback_cannot_revoke_previously_checked_recording(self):
        checked, callbacks = public._check_optional, []

        def after_last_media_bytes(guard, **options):
            checked(guard, **options)
            if not options.get("callbacks") and not options.get("pure"):

                def revoke(values):
                    callbacks.append(values["action"])
                    self.authority.denied.add("PUBLIC_AUDIO")

                self.citation_authority.hook = revoke

        with (
            patch.object(public, "_check_optional", side_effect=after_last_media_bytes),
            self.assertRaises(public.OptionalMediaUnavailable),
        ):
            with public.publication_projection(self.publication.pk) as result:
                self.assertEqual(len(result["recordings"]), 1)
        self.assertTrue(callbacks, "The actual final citation authority callback must run.")

    def test_native_late_source_revocation_denies_whole_page(self):
        original = views.render

        def render_and_revoke(request, template, context):
            result = original(request, template, context)
            self.citation_authority.denied.add("READ_SOURCE")
            return result

        client = Client(REMOTE_ADDR="127.0.0.1", HTTP_HOST="127.0.0.1")
        with patch.object(views, "render", side_effect=render_and_revoke):
            response = client.get(
                f"/library-preview/publications/{self.publication.pk}/recordings/"
            )
        self.assertEqual(response.status_code, 404)
        self.assertNotContains(response, self.publication.body, status_code=404)
