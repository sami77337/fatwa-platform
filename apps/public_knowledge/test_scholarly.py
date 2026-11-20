"""Actual two-case approved links, exact public grants and full render revocation."""

import uuid
from dataclasses import replace
from hashlib import sha256
from unittest.mock import patch

from django.test import TransactionTestCase, override_settings

from apps.answer_media import services as media
from apps.answer_media.models import AnswerPart
from apps.answer_media.tests import audio_fixture
from apps.casework import services as cases
from apps.casework.models import AnswerRevision, Case, CaseEvent
from apps.experimental_publication import services as publication
from apps.experimental_publication.models import PublicationEdition
from apps.experimental_publication.tests import Authority as PublicationAuthority
from apps.library_preview.policy import PublicationGrant
from apps.scholarly_links import services as links
from apps.scholarly_links.authority import ScholarlyAuthority
from apps.scholarly_links.models import CaseRelation, LinkDecision
from tests.casework.test_http import post

from . import services, views
from .tests import FEATURES, CurationFixture, FixtureAuthority

INTEGRATED = {**FEATURES, "FATWA_SCHOLARLY_LINKS_ENABLED": True, "FATWA_ANSWER_MEDIA_ENABLED": True}


class LinkAuthority(ScholarlyAuthority):
    def __init__(self, refs):
        self.refs, self.denied = set(refs), set()

    def projection_epoch(self):
        return sha256(repr((sorted(self.refs), sorted(self.denied))).encode()).hexdigest()

    def permits(self, **values):
        return (
            values["provider_id"] == "synthetic-publication-directory"
            and values["subject_id"] in {"editor", "other", "publisher"}
            and values["auth_epoch"] == "epoch-1"
            and values["case_ref"] in self.refs
            and values["target_case_ref"] in self.refs
            and (values["action"], values["kind"]) not in self.denied
        )


class IntegratedFixture(CurationFixture):
    def setUp(self):
        super().setUp()
        self.second = cases.intake_case(
            original_question="PRIVATE second related case",
            source_event_id="public-related-event",
            requester_id="public-related-requester",
            idempotency_key="public-related-key",
            synthetic_fixtures_only=True,
        )
        for key, value in self.directory.identities.items():
            self.directory.identities[key] = replace(
                value, case_keys=value.case_keys | {self.second["public_ref"]}
            )
        self.link_authority = LinkAuthority([self.receipt["public_ref"], self.second["public_ref"]])
        configured = override_settings(FATWA_SCHOLARLY_LINKS_AUTHORITY=self.link_authority)
        configured.enable()
        self.addCleanup(configured.disable)
        common = self.second_common()
        saved = media.save_multipart_answer(
            **common,
            **self.pins(self.second),
            text="PRIVATE second answer",
            files=[audio_fixture()],
        )
        cases.record_decision(
            **{**common, "subject_id": "other"},
            **self.pins(self.second),
            answer_id=saved["answers"][-1]["id"],
            action="APPROVE",
        )
        self.part = AnswerPart.objects.get(
            manifest__answer__case_id=self.second["case_id"], ordinal=2
        )
        with override_settings(
            FATWA_EXPERIMENTAL_PUBLICATION_AUTHORITY=PublicationAuthority(self.second["public_ref"])
        ):
            self.second_publication = publication.create_edition(
                **common,
                **self.pins(self.second),
                title="فتوى ثانية مصرح بها",
                body="نص عام للفتوى الثانية",
                category="تصنيف اختباري",
            )
            publication.act(
                **common, edition_id=self.second_publication["id"], action="REVIEW", reviewed=True
            )
            publication.act(
                **{**common, "subject_id": "publisher"},
                edition_id=self.second_publication["id"],
                action="APPROVE",
            )
        second_edition = PublicationEdition.objects.get(pk=self.second_publication["id"])
        self.preview_policy = replace(
            self.preview_policy,
            publications=self.preview_policy.publications
            + (PublicationGrant(str(second_edition.pk), second_edition.content_sha256),),
        )
        configured = override_settings(FATWA_LIBRARY_PREVIEW_POLICY=self.preview_policy)
        configured.enable()
        self.addCleanup(configured.disable)
        self.public_url = f"/library-preview/knowledge/publications/{self.edition['id']}/ar/"

    def second_common(self):
        return {**self.common, "case_id": self.second["case_id"]}

    def pins(self, receipt=None):
        case = Case.objects.get(pk=(receipt or self.receipt)["case_id"])
        return dict(
            expected_revision=case.revision, expected_evidence_version=case.evidence_version
        )

    def relation(self):
        target = Case.objects.get(pk=self.second["case_id"])
        row = links.propose_relation(
            **self.common,
            **self.pins(),
            target_case_id=target.pk,
            target_answer_id=target.approved_answer_id,
            expected_target_revision=target.revision,
            expected_target_evidence_version=target.evidence_version,
            kind="REFERRED_BY_SHEIKH",
            reason="PRIVATE deliberate relation reason",
            command_id=uuid.uuid4(),
        )
        self.review_link(row)
        return row

    def review_link(self, row, action="APPROVE"):
        target = Case.objects.get(pk=self.second["case_id"])
        return links.review_link(
            **self.common,
            **self.pins(),
            link_id=row.pk,
            link_kind="RELATION" if isinstance(row, CaseRelation) else "LESSON",
            action=action,
            note="PRIVATE link review",
            command_id=uuid.uuid4(),
            expected_sequence=row.decisions.count(),
            expected_target_revision=target.revision,
            expected_target_evidence_version=target.evidence_version,
        )

    def presentation(self, relation=None):
        return self.release_record(
            self.save_record(
                "PRESENTATION",
                payload={
                    "title": "عنوان تجريبي",
                    "question": "",
                    "body": "",
                    "description": "",
                    "scholar_id": "",
                    "topic_ids": [],
                    "relation_ids": [str(relation.pk)] if relation else [],
                },
            )
        )

    def lesson(self):
        common = self.second_common()
        series = links.save_series(
            **common,
            **self.pins(self.second),
            title="PRIVATE series title",
            teachers=[
                {
                    "name": "PRIVATE teacher name",
                    "provider_id": self.directory.provider_id,
                    "subject_id": "editor",
                }
            ],
            command_id=uuid.uuid4(),
        )
        category = links.create_category(
            **common,
            **self.pins(self.second),
            label="PRIVATE lesson classification",
            command_id=uuid.uuid4(),
        )
        version = links.save_lesson(
            **common,
            **self.pins(self.second),
            series_id=series.series_id,
            expected_series_version=1,
            title="PRIVATE lesson title",
            category_id=category.pk,
            source_part_id=self.part.pk,
            provenance="PRIVATE original lesson provenance",
            command_id=uuid.uuid4(),
        )
        target = Case.objects.get(pk=self.second["case_id"])
        link = links.propose_lesson_link(
            **self.common,
            **self.pins(),
            lesson_version_id=version.pk,
            expected_target_revision=target.revision,
            expected_target_evidence_version=target.evidence_version,
            reason="PRIVATE source timestamp reason",
            start_ms=10,
            end_ms=50,
            command_id=uuid.uuid4(),
        )
        self.review_link(link)
        return version, link

    def lesson_record(self, version, *, scholar_ids=None):
        return services.save(
            **self.common,
            **self.pins(),
            publication_id=self.edition["id"],
            kind="LESSON",
            expected_version=0,
            payload={
                "title": "درس مصرح بعرضه",
                "summary": "ملخص عام كتبه إنسان",
                "lesson_public_id": str(version.lesson.public_id),
                "lesson_version": version.number,
                "lesson_sha256": version.sha256,
                "scholar_ids": scholar_ids or [],
                "topic_ids": [],
            },
            request_key=str(uuid.uuid4()),
        )


@override_settings(**INTEGRATED)
class ScholarlyPublicTests(IntegratedFixture, TransactionTestCase):
    def test_scholar_aggregation_follows_recorded_author_not_the_other_answer_approver(self):
        second = PublicationEdition.objects.select_related("answer", "decision").get(
            pk=self.second_publication["id"]
        )
        self.assertEqual(second.answer.subject_id, "editor")
        self.assertEqual(second.decision.subject_id, "other")
        author_profile = self.release_record(self.save_record())
        third = cases.intake_case(
            original_question="PRIVATE third author",
            requester_id="public-third",
            source_event_id="public-third",
            idempotency_key="public-third",
            synthetic_fixtures_only=True,
        )
        for key, value in self.directory.identities.items():
            self.directory.identities[key] = replace(
                value, case_keys=value.case_keys | {third["public_ref"]}
            )
        self.link_authority.refs.add(third["public_ref"])
        common = {**self.common, "case_id": third["case_id"], "subject_id": "other"}
        saved = cases.save_answer(
            **common, **self.pins(third), text="PRIVATE third author's answer"
        )
        cases.record_decision(
            **{**common, "subject_id": "editor"},
            **self.pins(third),
            answer_id=saved["answers"][-1]["id"],
            action="APPROVE",
        )
        with override_settings(
            FATWA_EXPERIMENTAL_PUBLICATION_AUTHORITY=PublicationAuthority(third["public_ref"])
        ):
            created = publication.create_edition(
                **common,
                **self.pins(third),
                title="محتوى مستقل للكاتب الآخر",
                body="نص عام ثالث",
                category="تصنيف تجريبي",
            )
            publication.act(**common, edition_id=created["id"], action="REVIEW", reviewed=True)
            publication.act(
                **{**common, "subject_id": "publisher"}, edition_id=created["id"], action="APPROVE"
            )
        edition = PublicationEdition.objects.get(pk=created["id"])
        refs = {self.receipt["public_ref"], third["public_ref"]}

        class BothAuthors(FixtureAuthority):
            def permits(self, **values):
                return values["case_ref"] in refs and super().permits(
                    **{**values, "case_ref": self.ref}
                )

        policy = replace(
            self.preview_policy,
            publications=self.preview_policy.publications
            + (PublicationGrant(str(edition.pk), edition.content_sha256),),
        )
        with override_settings(
            FATWA_PUBLIC_KNOWLEDGE_AUTHORITY=BothAuthors(self.receipt["public_ref"]),
            FATWA_LIBRARY_PREVIEW_POLICY=policy,
        ):
            other_profile = services.save(
                **common,
                **self.pins(third),
                publication_id=str(edition.pk),
                kind="SCHOLAR",
                expected_version=0,
                payload={"name": "اسم الكاتب الآخر", "bio": ""},
                request_key=str(uuid.uuid4()),
            )
            for action, actor in (
                ("REVIEW", "editor"),
                ("APPROVE", "publisher"),
                ("RELEASE", "publisher"),
            ):
                other_profile = services.act(
                    **{**common, "subject_id": actor},
                    **self.pins(third),
                    revision_id=other_profile["id"],
                    expected_actions=other_profile["action_count"],
                    action=action,
                    request_key=str(uuid.uuid4()),
                    note="مراجعة بشرية",
                    minutes=15 if action == "RELEASE" else 0,
                    confirmed=True,
                )
            author_page, other_page = self.page(author_profile), self.page(other_profile)
            self.assertContains(author_page, "عنوان تجريبي")
            self.assertContains(author_page, "فتوى ثانية مصرح بها")
            self.assertNotContains(author_page, "محتوى مستقل للكاتب الآخر")
            self.assertContains(other_page, "محتوى مستقل للكاتب الآخر")
            self.assertNotContains(other_page, "فتوى ثانية مصرح بها")
            self.assertNotContains(other_page, "عنوان تجريبي")

    def test_relationship_requires_explicit_reviewed_public_selection_and_both_exact_grants(self):
        relation = self.relation()
        self.assertNotContains(self.client.get(self.public_url), "فتوى ثانية مصرح بها")
        record = self.presentation(relation)
        response = self.client.get(self.public_url)
        self.assertContains(response, "فتوى ثانية مصرح بها")
        self.assertContains(response, "أحال إليها الشيخ")
        self.assertNotContains(response, "PRIVATE")
        self.assertNotContains(response, str(relation.pk))
        self.assertNotContains(response, self.second["public_ref"])
        with override_settings(
            FATWA_LIBRARY_PREVIEW_POLICY=replace(self.preview_policy, publications=(self.grant,))
        ):
            self.assertNotContains(self.client.get(self.public_url), "فتوى ثانية مصرح بها")
        self.decision(record, "REVOKE")
        self.assertNotContains(self.client.get(self.public_url), "فتوى ثانية مصرح بها")

    def test_exact_lesson_metadata_lease_requires_source_read_and_preserves_private_originals(self):
        originals = (
            list(AnswerRevision.objects.values()),
            list(CaseEvent.objects.values()),
            self.part.sha256,
        )
        version, link = self.lesson()
        profile = self.release_record(self.save_record())
        record = self.lesson_record(version, scholar_ids=[profile["id"]])
        self.assertNotContains(self.client.get(self.public_url), "درس مصرح بعرضه")
        record = self.release_record(record)
        response = self.client.get(self.public_url)
        self.assertContains(response, "درس مصرح بعرضه")
        for value in (
            "PRIVATE",
            str(version.pk),
            version.sha256,
            str(self.part.pk),
            self.second["public_ref"],
        ):
            self.assertNotContains(response, value)
        lesson_page = self.page(record, "lessons")
        self.assertContains(lesson_page, "ملخص عام كتبه إنسان")
        self.assertNotContains(lesson_page, "<audio")
        self.assertContains(self.page(profile), "درس مصرح بعرضه")
        self.assertEqual(
            originals,
            (
                list(AnswerRevision.objects.values()),
                list(CaseEvent.objects.values()),
                self.part.sha256,
            ),
        )
        self.link_authority.denied.add(("READ_LESSON", "LESSON"))
        refused = self.client.get(self.public_url)
        self.assertEqual(refused.status_code, 404)
        self.assertNotContains(refused, "درس مصرح بعرضه", status_code=404)

    def test_final_html_link_withdrawal_discards_the_entire_assembled_page(self):
        relation = self.relation()
        self.presentation(relation)
        original = views.render

        def withdraw(*args, **kwargs):
            response = original(*args, **kwargs)
            self.review_link(relation, "WITHDRAW")
            return response

        before = LinkDecision.objects.count()
        with patch.object(views, "render", side_effect=withdraw):
            response = self.client.get(self.public_url)
        self.assertEqual(response.status_code, 404)
        self.assertNotContains(response, "فتوى ثانية مصرح بها", status_code=404)
        self.assertEqual(LinkDecision.objects.count(), before)

    def test_final_html_scholarly_read_revocation_discards_cards_and_counts(self):
        relation = self.relation()
        self.presentation(relation)
        original = views.render

        def revoke(*args, **kwargs):
            response = original(*args, **kwargs)
            self.link_authority.denied.add(("READ_LINK", "REFERRED_BY_SHEIKH"))
            return response

        with patch.object(views, "render", side_effect=revoke):
            response = self.client.get(self.public_url)
        self.assertEqual(response.status_code, 404)
        self.assertNotContains(response, "فتوى ثانية مصرح بها", status_code=404)

    def test_final_public_authority_callback_cannot_revoke_an_earlier_lesson_read(self):
        version, _ = self.lesson()
        self.release_record(self.lesson_record(version))
        original_render, original_permit = views.render, self.curation_authority.permits
        rendered = False

        def remember(*args, **kwargs):
            nonlocal rendered
            response = original_render(*args, **kwargs)
            rendered = True
            return response

        def revoke(**values):
            allowed = original_permit(**values)
            if rendered:
                self.link_authority.denied.add(("READ_LESSON", "LESSON"))
            return allowed

        with (
            patch.object(views, "render", side_effect=remember),
            patch.object(self.curation_authority, "permits", side_effect=revoke),
        ):
            response = self.client.get(self.public_url)
        self.assertEqual(response.status_code, 404)
        self.assertNotContains(response, "درس مصرح بعرضه", status_code=404)

    def test_value_equal_replacement_scholarly_authority_is_still_a_changed_configuration(self):
        from django.conf import settings

        class EqualAuthority(LinkAuthority):
            def __eq__(self, other):
                return True

        relation = self.relation()
        self.presentation(relation)
        original = views.render

        def replace_policy(*args, **kwargs):
            response = original(*args, **kwargs)
            settings.FATWA_SCHOLARLY_LINKS_AUTHORITY = EqualAuthority(self.link_authority.refs)
            return response

        with (
            override_settings(FATWA_SCHOLARLY_LINKS_AUTHORITY=self.link_authority),
            patch.object(views, "render", side_effect=replace_policy),
        ):
            response = self.client.get(self.public_url)
        self.assertEqual(response.status_code, 404)
        self.assertNotContains(response, "فتوى ثانية مصرح بها", status_code=404)

    def test_missing_other_case_scope_denies_save_and_existing_released_relation(self):
        relation = self.relation()
        self.presentation(relation)
        for subject in ("editor", "publisher"):
            old = self.directory.identities[subject]
            self.directory.identities[subject] = replace(
                old, case_keys=frozenset({self.receipt["public_ref"]})
            )
        self.assertEqual(self.client.get(self.public_url).status_code, 404)
        with self.assertRaises(cases.CaseConflict):
            self.save_record(
                "PRESENTATION",
                language="en",
                payload={
                    "title": "Explicit related translation",
                    "question": "",
                    "body": "Reviewed candidate",
                    "description": "",
                    "scholar_id": "",
                    "topic_ids": [],
                    "relation_ids": [str(relation.pk)],
                },
            )

    def test_native_forms_offer_exact_authorized_relations_and_versioned_lessons(self):
        relation = self.relation()
        version, _ = self.lesson()
        client, login = self.staff_client()
        page = post(
            client,
            "/casework/staff/",
            {"action": "pk_open", "case_ref": self.receipt["public_ref"]},
            login,
        )
        self.assertContains(page, f'name="relation_ids" value="{relation.pk}"')
        self.assertContains(page, f"{version.lesson.public_id}|1|{version.sha256}")
        response = post(
            client,
            "/casework/staff/",
            {
                "action": "pk_save_lesson",
                "case_ref": self.receipt["public_ref"],
                "publication_id": self.edition["id"],
                "series_id": "",
                "expected_version": "0",
                "revision": "4",
                "evidence_version": "2",
                "request_key": str(uuid.uuid4()),
                "title": "درس من الواجهة",
                "summary": "وصف من الواجهة",
                "lesson_choice": f"{version.lesson.public_id}|1|{version.sha256}",
            },
            page,
        )
        self.assertEqual(response.status_code, 200, response.content)
        self.assertContains(response, "درس من الواجهة")
