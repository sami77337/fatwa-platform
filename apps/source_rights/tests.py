"""PostgreSQL rights history and actual canonical correction workflows."""

from dataclasses import replace
from datetime import timedelta
from unittest.mock import patch

from django.db import IntegrityError, connection, transaction
from django.test import Client, TransactionTestCase, override_settings
from django.utils import timezone

from apps.case_citations import services as citations
from apps.casework import services as cases
from apps.casework.models import AnswerRevision, Case
from apps.knowledge_links import services as knowledge
from apps.knowledge_links.models import KnowledgeRevision
from apps.knowledge_links.tests import FEATURES, Fixture
from apps.reference.models import ReferenceHeading
from tests.casework.test_http import post

from . import services
from .authority import SourceRightsAuthority
from .models import RightsAction, RightsRevision, SourceRegistration, SourceVersion

ENABLED = {**FEATURES, "FATWA_SOURCE_RIGHTS_ENABLED": True}


class Authority(SourceRightsAuthority):
    def __init__(self, ref):
        self.ref = ref

    def permits(self, **kwargs):
        return (
            kwargs["case_ref"] == self.ref
            and kwargs["auth_epoch"] == "epoch-1"
            and (
                kwargs["action"] in {"VIEW", "REGISTER", "PROPOSE"}
                or kwargs["subject_id"] == "publisher"
            )
        )


class RightsFixture(Fixture):
    def setUp(self):
        super().setUp()
        self.rights_authority = Authority(self.receipt["public_ref"])
        overlay = override_settings(FATWA_SOURCE_RIGHTS_AUTHORITY=self.rights_authority)
        overlay.enable()
        self.addCleanup(overlay.disable)
        self.source = self.register_heading(self.heading)

    def register_heading(self, heading):
        return services.register(**self.common, kind="TOC_METADATA", target_id=heading.pk)

    def proposal(self, source=None, uses=None, number=0):
        return services.propose(
            **self.common,
            source_id=(source or self.source)["id"],
            expected_number=number,
            uses=["READ", "CITE", "RELATE", "PREVIEW_METADATA"] if uses is None else uses,
            basis="Synthetic rights document explicitly reviewed",
            note="PRIVATE rights note",
            ttl_minutes=60,
        )

    def decision(self, revision, action="APPROVE", subject="publisher"):
        return services.review(
            **{**self.common, "subject_id": subject},
            revision_id=revision["id"],
            action=action,
            confirmed=True,
            note="PRIVATE independent review",
        )

    def allow(self, heading=None):
        source = self.register_heading(heading) if heading is not None else self.source
        proposal = self.proposal(source)
        self.decision(proposal)
        return proposal

    def permitted(self, usage="CITE", case_id=None):
        with transaction.atomic():
            case = Case.objects.select_for_update().get(pk=case_id or self.receipt["case_id"])
            source = citations._source(self.catalog_id, 2)
            return services.permits_reference_for_locked_case(case=case, source=source, usage=usage)


@override_settings(**ENABLED)
class RightsTests(RightsFixture, TransactionTestCase):
    def test_registration_is_not_permission_and_independent_review_is_required(self):
        self.assertEqual(self.source["state"], "UNKNOWN")
        self.assertFalse(self.permitted())
        proposal = self.proposal()
        self.assertFalse(self.permitted())
        with self.assertRaises(cases.CaseConflict):
            self.decision(proposal, subject="editor")
        self.decision(proposal)
        self.assertTrue(self.permitted())
        self.assertFalse(self.permitted("PUBLISH"))
        self.assertFalse(self.permitted("FULL_TEXT"))
        state = services.desk(**self.common)["records"][0]
        self.assertEqual(state["kind"], "TOC_METADATA")
        self.assertEqual(state["state"], "ALLOWED")
        self.assertEqual(
            state["history"][0]["basis"], "Synthetic rights document explicitly reviewed"
        )

    def test_new_revision_blocks_old_grant_preserves_history_and_revocation(self):
        first = self.allow()
        second = self.proposal(number=1, uses=["READ"])
        self.assertFalse(self.permitted())
        with self.assertRaises(cases.CaseConflict):
            self.decision(first, "REVOKE")
        self.decision(second)
        self.assertTrue(self.permitted("READ"))
        self.assertFalse(self.permitted("CITE"))
        self.decision(second, "REVOKE")
        self.assertFalse(self.permitted("READ"))
        history = services.desk(**self.common)["records"][0]["history"]
        self.assertEqual([r["number"] for r in history], [2, 1])
        self.assertEqual(RightsAction.objects.count(), 3)
        self.assertEqual(RightsRevision.objects.count(), 2)

    def test_restriction_rejection_expiry_and_disabled_authority_close_rights(self):
        denied = self.proposal(uses=[])
        self.decision(denied)
        self.assertFalse(self.permitted("READ"))
        second = self.proposal(number=1)
        self.decision(second, "REJECT")
        self.assertFalse(self.permitted())
        third = self.proposal(number=2)
        self.decision(third)
        with patch.object(
            services.timezone, "now", return_value=timezone.now() + timedelta(hours=2)
        ):
            self.assertFalse(self.permitted())
        for settings in (
            {"FATWA_SOURCE_RIGHTS_ENABLED": False},
            {"FATWA_SOURCE_RIGHTS_AUTHORITY": None},
        ):
            with override_settings(**settings):
                self.assertFalse(self.permitted())
                with self.assertRaises(cases.CaseConflict):
                    services.desk(**self.common)

    def test_existing_citation_correction_creates_canonical_revision_and_clears_approval(self):
        self.allow()
        replacement = ReferenceHeading.objects.get(edition_id=self.catalog_id, source_row_id=3)
        self.allow(replacement)
        before = citations.read_citations(**self.common)[0]
        result = services.correct_citation(
            **self.common,
            citation_id=before["id"],
            target_id=replacement.pk,
            note="Human corrected exact position",
            expected_revision=4,
            expected_evidence_version=2,
        )
        self.assertEqual(result["status"], "UNDER_REVIEW")
        self.assertIsNone(result["approved_answer_id"])
        self.assertEqual(AnswerRevision.objects.count(), 2)
        self.assertEqual(citations.read_citations(**self.common)[0]["source"]["source_row_id"], 3)
        old = citations.read_citations(**self.common, answer_id=before["answer_id"])
        self.assertEqual(old[0]["source"]["source_row_id"], 2)
        self.assertEqual(AnswerRevision.objects.order_by("revision").last().text, "PRIVATE ANSWER")
        with self.assertRaises(cases.CaseConflict):
            knowledge.browse(**self.access)

    def test_uncertain_or_revoked_rights_prevent_citation_write_and_release_session_lock(self):
        before = citations.read_citations(**self.common)[0]
        for _ in range(2):
            with self.assertRaises(cases.CaseConflict):
                services.correct_citation(
                    **self.common,
                    citation_id=before["id"],
                    target_id=self.heading.pk,
                    note="note",
                    expected_revision=4,
                    expected_evidence_version=2,
                )
        self.assertEqual(AnswerRevision.objects.count(), 1)
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT count(*) FROM pg_locks WHERE pid=pg_backend_pid() AND locktype='advisory'"
            )
            self.assertEqual(cursor.fetchone()[0], 0)

    def test_relationship_review_and_correction_use_existing_knowledge_service(self):
        self.allow()
        first = services.propose_relation(
            **self.common,
            publication_id=self.edition["id"],
            kind="REFERENCE",
            target_id=self.heading.pk,
            reason="Existing source relation",
        )
        services.act_on_relation(
            **{**self.common, "subject_id": "publisher"},
            publication_id=self.edition["id"],
            relation_id=first["id"],
            action="APPROVE",
            confirmed=True,
        )
        self.assertEqual(len(knowledge.browse(**self.access)["links"]), 1)
        corrected = services.propose_relation(
            **self.common,
            publication_id=self.edition["id"],
            kind="REFERENCE",
            target_id=self.heading.pk,
            replaces_id=first["id"],
            reason="Corrected relation review",
        )
        self.assertEqual(knowledge.browse(**self.access)["links"], [])
        rights = RightsRevision.objects.get()
        self.decision({"id": str(rights.pk)}, "REVOKE")
        with self.assertRaises(cases.CaseConflict):
            services.act_on_relation(
                **{**self.common, "subject_id": "publisher"},
                publication_id=self.edition["id"],
                relation_id=corrected["id"],
                action="APPROVE",
                confirmed=True,
            )
        services.act_on_relation(
            **{**self.common, "subject_id": "publisher"},
            publication_id=self.edition["id"],
            relation_id=corrected["id"],
            action="WITHDRAW",
            confirmed=True,
        )
        self.assertEqual(KnowledgeRevision.objects.count(), 2)

    def test_private_transcript_never_acquires_publication_or_citation_rights(self):
        source = services.register(
            **self.common, kind="PRIVATE_TRANSCRIPT", target_id=self.transcript["link_id"]
        )
        for uses in (["CITE"], ["PREVIEW_METADATA"], ["PUBLISH"]):
            with self.assertRaises(cases.CaseConflict):
                self.proposal(source, uses=uses)
        rights = self.proposal(source, uses=["READ", "RELATE"])
        self.decision(rights)
        with transaction.atomic():
            case = Case.objects.select_for_update().get(pk=self.receipt["case_id"])
            self.assertTrue(
                services.permits_transcript_for_locked_case(
                    case=case, transcript_id=self.transcript["link_id"], usage="READ"
                )
            )
            self.assertFalse(
                services.permits_transcript_for_locked_case(
                    case=case, transcript_id=self.transcript["link_id"], usage="PREVIEW_METADATA"
                )
            )
        row = services.propose_relation(
            **self.common,
            publication_id=self.edition["id"],
            kind="TRANSCRIPT",
            target_id=self.transcript["link_id"],
            reason="private source",
        )
        self.assertEqual(row["state"], "PROPOSED")
        self.assertNotIn(self.transcript_text, str(services.desk(**self.common)["records"]))

    def test_rights_are_case_scoped_and_sources_must_be_real(self):
        self.allow()
        other = cases.intake_case(
            original_question="other",
            source_event_id="other",
            requester_id="other",
            idempotency_key="other",
            synthetic_fixtures_only=True,
        )
        self.assertFalse(self.permitted(case_id=other["case_id"]))
        with self.assertRaises(cases.CaseConflict):
            services.register(**self.common, kind="ORIGINAL_BOOK_TEXT", target_id=self.heading.pk)
        with self.assertRaises(cases.CaseConflict):
            services.register(**self.common, kind="TOC_METADATA", target_id=999999)
        self.directory.identities["editor"] = replace(
            self.directory.identities["editor"], case_keys=frozenset({other["public_ref"]})
        )
        with self.assertRaises(cases.CaseConflict):
            services.desk(**self.common)

    def test_database_immutable_history_binding_and_self_approval(self):
        proposed = self.proposal()
        revision = RightsRevision.objects.get(pk=proposed["id"])
        for operation in (
            lambda: SourceVersion.objects.all().update(kind="ORIGINAL_BOOK_TEXT"),
            lambda: SourceRegistration.objects.all().delete(),
            lambda: RightsRevision.objects.all().update(note="erase"),
            lambda: RightsRevision.objects.all().delete(),
            lambda: RightsAction.objects.create(
                revision=revision,
                action="APPROVE",
                note="forged",
                subject_id=revision.subject_id,
                provider_id=revision.provider_id,
                auth_epoch=revision.auth_epoch,
            ),
        ):
            with self.assertRaises(IntegrityError), transaction.atomic():
                operation()
        self.decision(proposed)
        with self.assertRaises(IntegrityError), transaction.atomic():
            RightsAction.objects.all().delete()
        self.assertEqual(RightsAction.objects.count(), 1)

    def test_actor_revocation_mid_review_rolls_back(self):
        proposed = self.proposal()
        original = self.rights_authority.permits

        def revoke(**kwargs):
            allowed = original(**kwargs)
            self.directory.identities["publisher"] = replace(
                self.directory.identities["publisher"], auth_epoch="revoked"
            )
            return allowed

        with patch.object(self.rights_authority, "permits", side_effect=revoke):
            with self.assertRaises(cases.CaseConflict):
                self.decision(proposed)
        self.assertEqual(RightsAction.objects.count(), 0)

    @override_settings(FATWA_CASEWORK_WEB_ENABLED=True)
    def test_http_forms_real_review_csrf_and_no_identity_fields(self):
        client = Client(enforce_csrf_checks=True, REMOTE_ADDR="127.0.0.1", HTTP_HOST="127.0.0.1")
        with override_settings(FATWA_CASEWORK_IDENTITY_PROVIDER=self.directory):
            fields = {
                "action": "rights_desk",
                "case_ref": self.receipt["public_ref"],
                "query": "",
                "edition_id": "",
            }
            self.assertEqual(client.post("/casework/staff/", fields).status_code, 403)
            login = client.get("/casework/staff/login/")
            post(
                client,
                "/casework/staff/login/",
                {"credential": "synthetic-editor-credential-32-characters"},
                login,
            )
            page = client.get("/casework/staff/")
            page = post(client, "/casework/staff/", fields, page)
            self.assertEqual(page.status_code, 200, page.content)
            self.assertContains(page, "UNKNOWN")
            proposal = {
                "action": "rights_propose",
                "case_ref": self.receipt["public_ref"],
                "source_id": self.source["id"],
                "expected_number": "0",
                "uses": "CITE",
                "basis": "Synthetic rights basis",
                "note": "note",
                "ttl_minutes": "30",
            }
            page = post(client, "/casework/staff/", proposal, page)
            self.assertEqual(page.status_code, 200, page.content)
            self.assertContains(page, "PENDING")
            self.assertIn("no-store", page["Cache-Control"])
            self.assertEqual(
                post(
                    client, "/casework/staff/", {**fields, "subject_id": "publisher"}, page
                ).status_code,
                400,
            )
            self.assertEqual(
                client.get("/casework/staff/", REMOTE_ADDR="192.0.2.1").status_code, 403
            )

    def test_registration_of_uncited_heading_remains_visible_without_search(self):
        heading = ReferenceHeading.objects.get(edition_id=self.catalog_id, source_row_id=3)
        source = self.register_heading(heading)
        desk = services.desk(**self.common)
        self.assertIn(source["id"], {row["id"] for row in desk["records"]})
        self.assertEqual(SourceRegistration.objects.count(), 2)
        self.assertEqual(self.register_heading(heading)["id"], source["id"])
        self.assertEqual(SourceRegistration.objects.count(), 2)

    def test_changed_source_snapshot_and_invalid_uses_fail_closed(self):
        self.allow()
        original = services._reference

        def changed(identity):
            snapshot, target = original(identity)
            return {**snapshot, "changed": True}, target

        with patch.object(services, "_reference", side_effect=changed):
            self.assertFalse(self.permitted())
        for uses in (["CITE", "CITE"], ["EXPORT"], [True]):
            with self.assertRaises(cases.CaseConflict):
                self.proposal(uses=uses, number=1)
        self.assertEqual(RightsRevision.objects.count(), 1)

    def test_concurrent_review_commits_once(self):
        from concurrent.futures import ThreadPoolExecutor

        from django.db import connections

        proposed = self.proposal()

        def decide():
            try:
                return self.decision(proposed)["state"]
            except cases.CaseConflict:
                return "CONFLICT"
            finally:
                connections.close_all()

        with ThreadPoolExecutor(max_workers=2) as pool:
            outcomes = list(pool.map(lambda _: decide(), range(2)))
        self.assertCountEqual(outcomes, ["ALLOWED", "CONFLICT"])
        self.assertEqual(RightsAction.objects.count(), 1)

    def test_revocation_waits_for_delegated_canonical_write_then_blocks_next_write(self):
        from concurrent.futures import ThreadPoolExecutor
        from threading import Event

        from django.db import connections

        allowed = self.allow()
        old_citation = citations.read_citations(**self.common)[0]
        saving, revoke_started = Event(), Event()
        original = citations.save_cited_answer

        def observed_save(**kwargs):
            saving.set()
            self.assertTrue(revoke_started.wait(5))
            return original(**kwargs)

        def correction():
            try:
                return services.correct_citation(
                    **self.common,
                    citation_id=old_citation["id"],
                    target_id=self.heading.pk,
                    note="serialized correction",
                    expected_revision=4,
                    expected_evidence_version=2,
                )
            finally:
                connections.close_all()

        def revocation():
            try:
                self.assertTrue(saving.wait(5))
                revoke_started.set()
                return self.decision(allowed, "REVOKE")
            finally:
                connections.close_all()

        with (
            patch.object(citations, "save_cited_answer", side_effect=observed_save),
            ThreadPoolExecutor(max_workers=2) as pool,
        ):
            first, second = pool.submit(correction), pool.submit(revocation)
            self.assertEqual(first.result()["status"], "UNDER_REVIEW")
            self.assertEqual(second.result()["state"], "REVOKED")
        self.assertFalse(self.permitted())
        self.assertEqual(AnswerRevision.objects.count(), 2)

    def test_another_imported_edition_does_not_inherit_source_rights(self):
        from apps.reference.ingest import ingest_catalog
        from tests.reference.test_catalog import fixture

        self.allow()
        spec, rows = fixture()
        spec = replace(spec, source_book_id="622", edition_key="second-synthetic-edition")
        preview = ingest_catalog(spec, rows)
        second = ingest_catalog(spec, rows, dry_run=False, expected_checksum=preview.checksum)
        second_heading = ReferenceHeading.objects.get(edition_id=second.edition_id, source_row_id=2)
        registered = self.register_heading(second_heading)
        self.assertNotEqual(registered["sha256"], self.source["sha256"])
        self.assertEqual(registered["state"], "UNKNOWN")
        with transaction.atomic():
            case = Case.objects.select_for_update().get(pk=self.receipt["case_id"])
            self.assertFalse(
                services.permits_reference_for_locked_case(
                    case=case, source=citations._source(second.edition_id, 2), usage="CITE"
                )
            )
