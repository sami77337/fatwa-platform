"""Synthetic PostgreSQL tests; exercise canonical services, never real case data."""

import uuid
from dataclasses import replace
from unittest.mock import patch

from django.db import IntegrityError, transaction
from django.test import Client, TransactionTestCase, override_settings

from apps.case_citations import services as citations
from apps.case_citations.tests import source_fixture
from apps.casework import services as cases
from apps.casework.models import Case
from apps.experimental_publication import services as publications
from apps.experimental_publication.tests import Authority as PublicationAuthority
from apps.experimental_publication.tests import Directory
from apps.reference.models import ReferenceHeading
from apps.transcript_case_links import services as transcripts
from apps.transcript_case_links.tests import bundle
from tests.casework.test_http import WEB_SETTINGS, post

from . import services
from .authority import KnowledgeAuthority
from .models import KnowledgeAction, KnowledgeRevision

FEATURES = dict(
    FATWA_KNOWLEDGE_LINKS_ENABLED=True,
    FATWA_CASE_CITATIONS_ENABLED=True,
    FATWA_EXPERIMENTAL_PUBLICATION_ENABLED=True,
)


class Authority(KnowledgeAuthority):
    def __init__(self, ref):
        self.ref = ref
        self.allow_open = True

    def permits(self, **kwargs):
        return (
            kwargs["case_ref"] == self.ref
            and kwargs["auth_epoch"] == "epoch-1"
            and (
                (
                    kwargs["action"] in {"APPROVE", "WITHDRAW"}
                    and kwargs["subject_id"] == "publisher"
                )
                or (kwargs["action"] == "OPEN_TRANSCRIPT" and self.allow_open)
            )
        )


class Fixture:
    def setUp(self):
        super().setUp()
        self.catalog_id = source_fixture()
        self.heading = ReferenceHeading.objects.get(edition_id=self.catalog_id, source_row_id=2)
        self.receipt = cases.intake_case(
            original_question="PRIVATE QUESTION requester@example.test",
            source_event_id="knowledge-event",
            requester_id="knowledge-requester",
            idempotency_key="knowledge-intake",
            synthetic_fixtures_only=True,
        )
        self.directory = Directory([self.receipt["public_ref"]])
        self.common = dict(
            case_id=self.receipt["case_id"],
            subject_id="editor",
            provider=self.directory,
            synthetic_fixtures_only=True,
        )
        preview = transcripts.preview(**self.common, bundle=bundle())
        self.transcript = transcripts.attach(
            **self.common,
            upload_id=preview["upload_id"],
            external_id=preview["entries"][0].external_id,
        )
        self.transcript_text = preview["entries"][0].question.text
        self.transcript_source_id = preview["entries"][0].source_id
        source = citations.read_source(**self.common, edition_id=self.catalog_id, source_row_id=2)
        draft = citations.save_cited_answer(
            **self.common,
            text="PRIVATE ANSWER",
            selections=[
                dict(
                    edition_id=self.catalog_id,
                    source_row_id=2,
                    source_sha256=source["source_sha256"],
                    editorial_note="PRIVATE NOTE",
                )
            ],
            expected_revision=2,
            expected_evidence_version=2,
        )
        cases.record_decision(
            **self.common,
            answer_id=draft["answers"][-1]["id"],
            action="APPROVE",
            expected_revision=3,
            expected_evidence_version=2,
        )
        self.authority = Authority(self.receipt["public_ref"])
        self.policy = override_settings(
            FATWA_EXPERIMENTAL_PUBLICATION_AUTHORITY=PublicationAuthority(
                self.receipt["public_ref"]
            ),
            FATWA_KNOWLEDGE_LINKS_AUTHORITY=self.authority,
        )
        self.policy.enable()
        self.addCleanup(self.policy.disable)
        self.edition = self.new_publication()
        self.access = dict(
            publication_id=self.edition["id"],
            subject_id="editor",
            provider=self.directory,
            synthetic_fixtures_only=True,
        )

    def new_publication(self):
        case = Case.objects.get(pk=self.receipt["case_id"])
        edition = publications.create_edition(
            **self.common,
            expected_revision=case.revision,
            expected_evidence_version=case.evidence_version,
            title="عنوان تجريبي",
            category="تصنيف تجريبي",
            body="نص محرر مسموح",
        )
        publications.act(**self.common, edition_id=edition["id"], action="REVIEW", reviewed=True)
        publications.act(
            **{**self.common, "subject_id": "publisher"}, edition_id=edition["id"], action="APPROVE"
        )
        return edition

    def propose(self, kind="REFERENCE", **kwargs):
        return services.propose(
            **self.access,
            kind=kind,
            target_id=self.heading.pk if kind == "REFERENCE" else self.transcript["link_id"],
            reason="PRIVATE correction reason",
            **kwargs,
        )

    def approve(self, row):
        return services.act(
            **{**self.access, "subject_id": "publisher"},
            revision_id=row["id"],
            action="APPROVE",
            confirmed=True,
        )

    def browse(self, **kwargs):
        return services.browse(**self.access, **kwargs)


@override_settings(**FEATURES)
class KnowledgeTests(Fixture, TransactionTestCase):
    def test_real_reference_transcript_journey_with_safe_library_projection(self):
        ref, transcript = self.propose(), self.propose("TRANSCRIPT")
        self.assertEqual(self.browse()["links"], [])
        self.approve(ref)
        self.approve(transcript)
        result = self.browse()
        self.assertEqual(len(result["links"]), 2)
        for private in (
            "PRIVATE",
            "requester@example.test",
            self.receipt["public_ref"],
            self.receipt["case_id"],
            self.transcript_text,
            self.transcript_source_id,
            "subject_id",
            "editor",
            "question_sha256",
            "bundle_sha256",
        ):
            self.assertNotIn(private, str(result))
            self.assertEqual(self.browse(query=private[:80])["links"], [])
        found = self.browse(query="فرع")["links"]
        self.assertEqual(len(found), 1)
        source = services.open_material(**self.access, revision_id=ref["id"])["source"]
        self.assertEqual(source["printed_page"], 2)
        self.assertEqual(source["edition_id"], self.catalog_id)
        opened = services.open_material(**self.access, revision_id=transcript["id"])
        self.assertEqual(opened["material"]["text"], self.transcript_text)
        self.assertEqual(opened["material"]["start_ms"], 0)
        self.assertNotIn("answer", opened["material"])

    def test_explicit_independent_review_and_default_deny(self):
        row = self.propose()
        for extra in ({"confirmed": False}, {"subject_id": "editor"}):
            args = dict(
                self.access,
                subject_id="publisher",
                revision_id=row["id"],
                action="APPROVE",
                confirmed=True,
            )
            with self.assertRaises(cases.CaseConflict):
                services.act(**{**args, **extra})
        with override_settings(FATWA_KNOWLEDGE_LINKS_AUTHORITY=None):
            with self.assertRaises(cases.CaseConflict):
                self.approve(row)
        with override_settings(FATWA_KNOWLEDGE_LINKS_ENABLED=False):
            with self.assertRaises(cases.CaseConflict):
                self.browse()
        self.assertEqual(KnowledgeAction.objects.count(), 0)

    def test_correction_preserves_history_hides_old_and_requires_new_approval(self):
        first = self.propose()
        self.approve(first)
        second = self.propose("TRANSCRIPT", replaces_id=first["id"])
        self.assertEqual(second["number"], 2)
        self.assertEqual(self.browse()["links"], [])
        with self.assertRaises(cases.CaseConflict):
            services.open_material(**self.access, revision_id=first["id"])
        with self.assertRaises(cases.CaseConflict):
            self.propose(replaces_id=first["id"])
        self.approve(second)
        services.act(
            **{**self.access, "subject_id": "publisher"},
            revision_id=second["id"],
            action="WITHDRAW",
            confirmed=True,
        )
        self.assertEqual(self.browse()["links"], [])
        self.assertEqual(KnowledgeRevision.objects.count(), 2)
        self.assertEqual(KnowledgeAction.objects.count(), 3)
        history = services.desk(**self.access)["history"]
        self.assertEqual([r["number"] for r in history], [2, 1])
        self.assertEqual(history[0]["state"], "WITHDRAWN")

    def test_uncited_or_invented_reference_and_cross_case_transcript_rejected(self):
        uncited = ReferenceHeading.objects.get(edition_id=self.catalog_id, source_row_id=3)
        for kind, target in (
            ("REFERENCE", uncited.pk),
            ("REFERENCE", 999999),
            ("TRANSCRIPT", str(uuid.uuid4())),
        ):
            with self.assertRaises(cases.CaseConflict):
                services.propose(**self.access, kind=kind, target_id=target, reason="reason")
        other = cases.intake_case(
            original_question="other",
            source_event_id="other",
            requester_id="other",
            idempotency_key="other",
            synthetic_fixtures_only=True,
        )
        for key, identity in self.directory.identities.items():
            self.directory.identities[key] = replace(
                identity, case_keys=identity.case_keys | {other["public_ref"]}
            )
        other_args = {**self.common, "case_id": other["case_id"]}
        preview = transcripts.preview(**other_args, bundle=bundle())
        link = transcripts.attach(
            **other_args,
            upload_id=preview["upload_id"],
            external_id=preview["entries"][0].external_id,
        )
        with self.assertRaises(cases.CaseConflict):
            services.propose(
                **self.access, kind="TRANSCRIPT", target_id=link["link_id"], reason="wrong case"
            )
        self.assertEqual(KnowledgeRevision.objects.count(), 0)

    def test_new_evidence_closes_all_navigation_and_approval(self):
        ref = self.propose()
        transcript = self.propose("TRANSCRIPT")
        self.approve(transcript)
        cases.add_followup(
            token=self.receipt["token"],
            text="new facts",
            expected_revision=4,
            synthetic_fixtures_only=True,
        )
        for op in (
            self.browse,
            lambda: self.approve(ref),
            lambda: services.open_material(**self.access, revision_id=transcript["id"]),
        ):
            with self.assertRaises(cases.CaseConflict):
                op()

    def test_publication_correction_and_withdrawal_never_inherit_relationships(self):
        row = self.propose()
        self.approve(row)
        replacement = self.new_publication()
        with self.assertRaises(cases.CaseConflict):
            self.browse()
        new_access = {**self.access, "publication_id": replacement["id"]}
        self.assertEqual(services.browse(**new_access)["links"], [])
        with self.assertRaises(cases.CaseConflict):
            services.open_material(**new_access, revision_id=row["id"])
        publications.act(
            **{**self.common, "subject_id": "publisher"},
            edition_id=replacement["id"],
            action="WITHDRAW",
        )
        with self.assertRaises(cases.CaseConflict):
            services.browse(**new_access)

    def test_private_source_rights_rechecked_each_open(self):
        row = self.propose("TRANSCRIPT")
        self.approve(row)
        self.assertIn("material", services.open_material(**self.access, revision_id=row["id"]))
        self.authority.allow_open = False
        with self.assertRaises(cases.CaseConflict):
            services.open_material(**self.access, revision_id=row["id"])
        self.assertNotIn(self.transcript_text, str(self.browse()))

    def test_identity_scope_role_and_epoch_revocation(self):
        row = self.propose()
        for change in (
            dict(case_keys=frozenset()),
            dict(role="ORGANIZER_ADMIN"),
            dict(active=False),
        ):
            original = self.directory.identities["publisher"]
            self.directory.identities["publisher"] = replace(original, **change)
            try:
                with self.assertRaises(cases.CaseConflict):
                    self.approve(row)
            finally:
                self.directory.identities["publisher"] = original
        original_permit = self.authority.permits

        def revoke(**kwargs):
            allowed = original_permit(**kwargs)
            self.directory.identities["publisher"] = replace(
                self.directory.identities["publisher"], auth_epoch="revoked"
            )
            return allowed

        with patch.object(self.authority, "permits", side_effect=revoke):
            with self.assertRaises(cases.CaseConflict):
                self.approve(row)
        self.assertEqual(KnowledgeAction.objects.count(), 0)

    def test_snapshot_and_upstream_integrity_fail_closed(self):
        row = self.propose("TRANSCRIPT")
        self.approve(row)
        with patch.object(services, "_transcripts_locked", return_value=[]):
            self.assertEqual(self.browse()["links"], [])
            with self.assertRaises(cases.CaseConflict):
                services.open_material(**self.access, revision_id=row["id"])
        with patch.object(publications, "_citation_snapshot", return_value=[]):
            with self.assertRaises(cases.CaseConflict):
                self.browse()

    def test_database_immutable_rows_independent_approval_and_lineage(self):
        first = self.propose()
        row = KnowledgeRevision.objects.get(pk=first["id"])
        for op in (
            lambda: KnowledgeRevision.objects.filter(pk=row.pk).update(reason="erase"),
            lambda: KnowledgeRevision.objects.filter(pk=row.pk).delete(),
            lambda: KnowledgeAction.objects.create(
                revision=row,
                action="APPROVE",
                subject_id="editor",
                provider_id=row.provider_id,
                auth_epoch="epoch-1",
            ),
        ):
            with self.assertRaises(IntegrityError), transaction.atomic():
                op()
        self.approve(first)
        for op in (
            lambda: KnowledgeAction.objects.all().update(action="WITHDRAW"),
            lambda: KnowledgeAction.objects.all().delete(),
        ):
            with self.assertRaises(IntegrityError), transaction.atomic():
                op()
        values = {
            f.name: getattr(row, f.name)
            for f in row._meta.fields
            if f.name not in {"id", "created_at"}
        }
        for update in (
            {"number": 3},
            {
                "series": uuid.uuid4(),
                "number": 1,
                "heading": ReferenceHeading.objects.get(
                    edition_id=self.catalog_id, source_row_id=3
                ),
            },
        ):
            with self.assertRaises(IntegrityError), transaction.atomic():
                KnowledgeRevision.objects.create(**{**values, **update})
        self.assertEqual(KnowledgeRevision.objects.count(), 1)

    @override_settings(**{**WEB_SETTINGS, "ROOT_URLCONF": "apps.knowledge_links.urls"})
    def test_http_auth_csrf_strict_forms_search_return_and_private_source(self):
        reference, transcript = self.propose(), self.propose("TRANSCRIPT")
        self.approve(reference)
        self.approve(transcript)
        client = Client(enforce_csrf_checks=True, REMOTE_ADDR="127.0.0.1", HTTP_HOST="127.0.0.1")
        with override_settings(FATWA_CASEWORK_IDENTITY_PROVIDER=self.directory):
            fields = dict(action="knowledge_browse", publication_id=self.edition["id"], query="فرع")
            self.assertEqual(client.post("/casework/staff/", fields).status_code, 403)
            page = client.get("/casework/staff/login/")
            post(
                client,
                "/casework/staff/login/",
                {"credential": "synthetic-editor-credential-32-characters"},
                page,
            )
            page = client.get("/casework/staff/")
            page = post(client, "/casework/staff/", fields, page)
            self.assertEqual(page.status_code, 200, page.content)
            self.assertContains(page, "فَرْعٌ تَجْرِيبِيّ")
            self.assertNotContains(page, "PRIVATE")
            self.assertIn("no-store", page["Cache-Control"])
            material = post(
                client,
                "/casework/staff/",
                {**fields, "action": "knowledge_open", "revision_id": reference["id"]},
                page,
            )
            self.assertContains(material, 'name="query" value="فرع"')
            self.assertContains(material, "الصفحة المطبوعة")
            self.assertNotContains(material, self.receipt["public_ref"])
            self.assertEqual(
                post(
                    client, "/casework/staff/", {**fields, "subject_id": "publisher"}, page
                ).status_code,
                400,
            )
            self.authority.allow_open = False
            denied = post(
                client,
                "/casework/staff/",
                {**fields, "action": "knowledge_open", "revision_id": transcript["id"]},
                material,
            )
            self.assertEqual(denied.status_code, 404)
            self.assertNotContains(denied, self.transcript_text, status_code=404)

    def test_private_preview_and_history_survive_withdrawal_without_library_leak(self):
        row = self.propose("TRANSCRIPT")
        preview = services.preview_material(**self.access, revision_id=row["id"])
        self.assertEqual(preview["state"], "PROPOSED")
        self.assertEqual(preview["material"]["text"], self.transcript_text)
        with self.assertRaises(cases.CaseConflict):
            services.open_material(**self.access, revision_id=row["id"])
        self.assertEqual(self.browse()["links"], [])
        self.approve(row)
        publications.act(
            **{**self.common, "subject_id": "publisher"},
            edition_id=self.edition["id"],
            action="WITHDRAW",
        )
        with self.assertRaises(cases.CaseConflict):
            self.browse()
        history = services.history(**self.access)
        self.assertEqual(history["history"][0]["reason"], "PRIVATE correction reason")
        self.assertEqual(history["history"][0]["actions"][0]["action"], "APPROVE")
        self.directory.identities["editor"] = replace(
            self.directory.identities["editor"], case_keys=frozenset({"other"})
        )
        with self.assertRaises(cases.CaseConflict):
            services.history(**self.access)

    def test_concurrent_review_commits_only_one_action(self):
        from concurrent.futures import ThreadPoolExecutor

        from django.db import connections

        row = self.propose()

        def approve():
            try:
                return self.approve(row)["state"]
            except cases.CaseConflict:
                return "CONFLICT"
            finally:
                connections.close_all()

        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(lambda _: approve(), range(2)))
        self.assertCountEqual(results, ["APPROVED", "CONFLICT"])
        self.assertEqual(KnowledgeAction.objects.count(), 1)

    def test_input_bounds_and_missing_target_do_not_create_records(self):
        for target in (None, True, "2", -1, 2**64):
            with self.assertRaises(cases.CaseConflict):
                services.propose(**self.access, kind="REFERENCE", target_id=target, reason="reason")
        for query in ("x" * 81, "\x00"):
            with self.assertRaises(cases.CaseConflict):
                self.browse(query=query)
        self.assertEqual(KnowledgeRevision.objects.count(), 0)

    @override_settings(**{**WEB_SETTINGS, "ROOT_URLCONF": "apps.knowledge_links.urls"})
    def test_http_proposal_preview_independent_approval_and_withdrawal(self):
        client = Client(enforce_csrf_checks=True, REMOTE_ADDR="127.0.0.1", HTTP_HOST="127.0.0.1")
        with override_settings(FATWA_CASEWORK_IDENTITY_PROVIDER=self.directory):
            page = client.get("/casework/staff/login/")
            post(
                client,
                "/casework/staff/login/",
                {"credential": "synthetic-editor-credential-32-characters"},
                page,
            )
            page = client.get("/casework/staff/")
            base = dict(publication_id=self.edition["id"], query="")
            page = post(client, "/casework/staff/", {**base, "action": "knowledge_desk"}, page)
            self.assertEqual(page.status_code, 200)
            page = post(
                client,
                "/casework/staff/",
                {
                    **base,
                    "action": "knowledge_propose",
                    "kind": "TRANSCRIPT",
                    "target_id": self.transcript["link_id"],
                    "reason": "PRIVATE review note",
                    "replaces_id": "",
                },
                page,
            )
            self.assertEqual(page.status_code, 200, page.content)
            row = KnowledgeRevision.objects.get()
            detail = post(
                client,
                "/casework/staff/",
                {**base, "action": "knowledge_preview", "revision_id": str(row.pk)},
                page,
            )
            self.assertContains(detail, "PROPOSED")
            self.assertContains(detail, self.transcript_text)
            self.assertEqual(self.browse()["links"], [])
            publisher = Client(
                enforce_csrf_checks=True, REMOTE_ADDR="127.0.0.1", HTTP_HOST="127.0.0.1"
            )
            login = publisher.get("/casework/staff/login/")
            with patch.object(
                self.directory, "authenticate", return_value=self.directory.resolve("publisher")
            ):
                post(
                    publisher,
                    "/casework/staff/login/",
                    {"credential": "synthetic-publisher-credential-32-characters"},
                    login,
                )
            review = publisher.get("/casework/staff/")
            review = post(
                publisher,
                "/casework/staff/",
                {
                    **base,
                    "action": "knowledge_approve",
                    "revision_id": str(row.pk),
                    "confirm": "yes",
                },
                review,
            )
            self.assertEqual(review.status_code, 200, review.content)
            self.assertEqual(len(self.browse()["links"]), 1)
            review = post(
                publisher,
                "/casework/staff/",
                {
                    **base,
                    "action": "knowledge_withdraw",
                    "revision_id": str(row.pk),
                    "confirm": "yes",
                },
                review,
            )
            self.assertEqual(review.status_code, 200)
            self.assertEqual(self.browse()["links"], [])
            history = post(
                publisher, "/casework/staff/", {**base, "action": "knowledge_history"}, review
            )
            self.assertContains(history, "WITHDRAWN")
            self.assertContains(history, "PRIVATE review note")

    def test_identity_revoked_during_source_read_does_not_return_material(self):
        row = self.propose("TRANSCRIPT")
        self.approve(row)
        original = services._transcripts_locked

        def revoke(edition):
            output = original(edition)
            self.directory.identities["editor"] = replace(
                self.directory.identities["editor"], auth_epoch="revoked"
            )
            return output

        with patch.object(services, "_transcripts_locked", side_effect=revoke):
            with self.assertRaises(cases.CaseConflict):
                services.open_material(**self.access, revision_id=row["id"])
