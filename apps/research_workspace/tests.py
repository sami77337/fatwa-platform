"""Real PostgreSQL contracts for rights, provenance and canonical citation writes."""

from dataclasses import replace
from unittest.mock import patch

from django.test import Client, TransactionTestCase, override_settings

from apps.answer_media import services as media
from apps.answer_media.models import AnswerPart
from apps.answer_media.tests import audio_fixture
from apps.case_attachments import services as attachments
from apps.case_citations import services as citations
from apps.casework import services as cases
from apps.casework.models import AnswerRevision, Case
from apps.knowledge_links import services as knowledge
from apps.knowledge_links import tests as fixtures
from tests.casework.test_http import WEB_SETTINGS, hidden, post

from . import services
from .rights import ResearchRights, Resource

SETTINGS = {
    **WEB_SETTINGS,
    **fixtures.FEATURES,
    "ROOT_URLCONF": "apps.research_workspace.urls",
    "FATWA_RESEARCH_WORKSPACE_ENABLED": True,
    "FATWA_ANSWER_MEDIA_ENABLED": True,
    "FATWA_CASE_ATTACHMENTS_ENABLED": True,
}


class SyntheticRights(ResearchRights):
    """Explicit fixture-only grant restricted to the fixture identity and case."""

    def __init__(self, ref):
        self.ref = ref
        self.denied = set()
        self.calls = []

    def permits(self, **kw):
        self.calls.append(kw)
        return (
            kw["provider_id"] == "synthetic-publication-directory"
            and kw["subject_id"] == "editor"
            and kw["auth_epoch"] == "epoch-1"
            and kw["case_ref"] == self.ref
            and (kw["resource"].kind, kw["action"]) not in self.denied
        )

    def projection_epoch(self):
        # Synthetic in-memory policy only; production adapters must supply an
        # atomic revision covering every external authorization input.
        return repr((self.ref, sorted(self.denied)))


class ResearchFixture(fixtures.Fixture):
    def setUp(self):
        super().setUp()
        self.rights = SyntheticRights(self.receipt["public_ref"])
        configured = override_settings(
            FATWA_RESEARCH_WORKSPACE_RIGHTS=self.rights,
            FATWA_CASEWORK_IDENTITY_PROVIDER=self.directory,
        )
        configured.enable()
        self.addCleanup(configured.disable)

    def search(self, **kw):
        return services.search(**self.common, **kw)

    def source(self, row=3):
        source = citations.read_source(**self.common, edition_id=self.catalog_id, source_row_id=row)
        return services._source_resource(source["source"], source["source_sha256"])

    def add(self, **kw):
        case = Case.objects.get(pk=self.receipt["case_id"])
        args = dict(
            resource=self.source(),
            note="ملاحظة بشرية اصطناعية",
            expected_revision=case.revision,
            expected_evidence_version=case.evidence_version,
        )
        return services.add_citation(**self.common, **{**args, **kw})

    def with_media(self):
        case = Case.objects.get(pk=self.receipt["case_id"])
        return media.save_multipart_answer(
            **self.common,
            text="جواب محفوظ اصطناعي",
            files=[audio_fixture()],
            expected_revision=case.revision,
            expected_evidence_version=case.evidence_version,
        )


@override_settings(**SETTINGS)
class ResearchTests(ResearchFixture, TransactionTestCase):
    def test_arabic_normalization_exact_location_and_index_not_book_text(self):
        rows = self.search(
            kind="REFERENCE", query="فرع", edition_id=self.catalog_id, printed_page=2
        )["results"]
        self.assertEqual(len(rows), 1)
        source = rows[0]
        self.assertIn("ليس متن", source["label"])
        self.assertEqual(source["source"]["source_row_id"], 2)
        resource = Resource(**source["resource"])
        with patch.object(services, "bridge_reference", wraps=services.bridge_reference) as bridge:
            opened = services.open_resource(**self.common, resource=resource)
        self.assertEqual(bridge.call_count, 1)
        self.assertEqual(opened["source"]["printed_page"], 2)
        self.assertEqual(resource.source_archive_sha256, "a" * 64)
        self.assertEqual(resource.source_input_sha256, "b" * 64)
        self.assertNotIn("text", opened)
        self.assertEqual(
            self.search(
                kind="REFERENCE", query="فرع", edition_id=self.catalog_id, printed_page=999
            )["results"],
            [],
        )

    def test_default_deny_and_independent_discover_open_cite_rights(self):
        source = self.source()
        with override_settings(FATWA_RESEARCH_WORKSPACE_RIGHTS=None):
            result = self.search()
            self.assertEqual(result["editions"], [])
            self.assertEqual(result["results"], [])
            with self.assertRaises(cases.CaseConflict):
                services.open_resource(**self.common, resource=source)
        self.rights.denied.add(("REFERENCE", "READ_METADATA"))
        self.assertTrue(
            self.search(kind="REFERENCE", query="فرع", edition_id=self.catalog_id)["results"]
        )
        with self.assertRaises(cases.CaseConflict):
            services.open_resource(**self.common, resource=source)
        self.rights.denied.add(("REFERENCE", "CITE"))
        before = AnswerRevision.objects.count()
        with self.assertRaises(cases.CaseConflict):
            self.add()
        self.assertEqual(AnswerRevision.objects.count(), before)

    def test_actual_transcript_exact_text_and_independent_permission(self):
        result = self.search(kind="TRANSCRIPT", query=self.transcript_text[:30])
        self.assertEqual(len(result["results"]), 1)
        resource = Resource(**result["results"][0]["resource"])
        opened = services.open_resource(**self.common, resource=resource)
        self.assertEqual(opened["question"]["text"], self.transcript_text)
        self.assertEqual(opened["question"]["start_ms"], 0)
        self.rights.denied.add(("TRANSCRIPT", "READ_TEXT"))
        with self.assertRaises(cases.CaseConflict):
            services.open_resource(**self.common, resource=resource)
        self.rights.denied.add(("TRANSCRIPT", "SEARCH_TEXT"))
        self.assertEqual(
            self.search(kind="TRANSCRIPT", query=self.transcript_text[:30])["results"], []
        )
        self.rights.denied.clear()
        self.authority.allow_open = False
        self.assertEqual(self.search(kind="TRANSCRIPT")["results"], [])
        with self.assertRaises(cases.CaseConflict):
            services.open_resource(**self.common, resource=resource)

    def test_only_approved_knowledge_and_underlying_source_rights(self):
        proposed = self.propose()
        self.assertEqual(self.search(kind="KNOWLEDGE")["results"], [])
        self.approve(proposed)
        row = self.search(kind="KNOWLEDGE")["results"][0]
        resource = Resource(**row["resource"])
        opened = services.open_resource(**self.common, resource=resource)
        self.assertEqual(opened["source"]["source_row_id"], 2)
        self.rights.denied.add(("REFERENCE", "READ_METADATA"))
        with self.assertRaises(cases.CaseConflict):
            services.open_resource(**self.common, resource=resource)
        self.rights.denied.add(("REFERENCE", "DISCOVER"))
        self.assertEqual(self.search(kind="KNOWLEDGE")["results"], [])
        self.rights.denied.clear()
        knowledge.act(
            **{**self.access, "subject_id": "publisher"},
            revision_id=proposed["id"],
            action="WITHDRAW",
            confirmed=True,
        )
        self.assertEqual(self.search(kind="KNOWLEDGE")["results"], [])
        with self.assertRaises(cases.CaseConflict):
            services.open_resource(**self.common, resource=resource)

    def test_knowledge_transcript_cannot_bypass_text_right(self):
        row = self.propose("TRANSCRIPT")
        self.approve(row)
        resource = Resource(**self.search(kind="KNOWLEDGE")["results"][0]["resource"])
        self.rights.denied.add(("TRANSCRIPT", "READ_TEXT"))
        with self.assertRaises(cases.CaseConflict):
            services.open_resource(**self.common, resource=resource)

    def test_append_citation_preserves_saved_answer_audio_and_resets_approval(self):
        saved = self.with_media()
        original = AnswerPart.objects.get(manifest__answer_id=saved["answers"][-1]["id"], ordinal=2)
        case = Case.objects.get(pk=self.receipt["case_id"])
        cases.record_decision(
            **self.common,
            action="APPROVE",
            answer_id=saved["answers"][-1]["id"],
            expected_revision=case.revision,
            expected_evidence_version=case.evidence_version,
        )
        added = self.add()
        case.refresh_from_db()
        latest = case.answers.order_by("-revision").first()
        self.assertIsNone(case.approved_answer_id)
        self.assertEqual(latest.revision, added["answer_revision"])
        self.assertEqual(latest.text, "جواب محفوظ اصطناعي")
        self.assertEqual(
            AnswerPart.objects.get(manifest__answer=latest, ordinal=2).sha256, original.sha256
        )
        self.assertEqual(
            [c["source"]["source_row_id"] for c in citations.citations_for_locked_answer(latest)],
            [2, 3],
        )
        resource = Resource(**self.search(kind="MEDIA")["results"][0]["resource"])
        self.assertEqual(
            services.open_resource(**self.common, resource=resource)["raw"], audio_fixture()["raw"]
        )
        self.rights.denied.add(("ANSWER_MEDIA", "READ_MEDIA"))
        with self.assertRaises(cases.CaseConflict):
            services.open_resource(**self.common, resource=resource)

    def test_stale_revision_resource_scope_and_bridge_mismatch_closed(self):
        source = self.source()
        for wrong in (
            replace(source, sha256="0" * 64),
            replace(source, source_input_sha256="0" * 64),
        ):
            with self.assertRaises(cases.CaseConflict):
                services.open_resource(**self.common, resource=wrong)
        with patch.object(services, "bridge_reference") as bridge:
            bridge.return_value.status = "unresolved"
            with self.assertRaises(cases.CaseConflict):
                services.open_resource(**self.common, resource=source)
        with self.assertRaises(cases.CaseConflict):
            self.add(expected_revision=1)
        self.directory.identities["editor"] = replace(
            self.directory.identities["editor"], case_keys=frozenset({"another-case"})
        )
        with self.assertRaises(Exception) as raised:
            services.open_resource(**self.common, resource=source)
        self.assertIn(type(raised.exception).__name__, {"IdentityUnavailable", "CaseConflict"})

    def test_rights_revoked_after_write_rolls_back_canonical_revision(self):
        original = citations.save_cited_answer
        before = AnswerRevision.objects.count()

        def revoke(**kw):
            result = original(**kw)
            self.rights.denied.add(("REFERENCE", "CITE"))
            return result

        with patch.object(citations, "save_cited_answer", side_effect=revoke):
            with self.assertRaises(cases.CaseConflict):
                self.add()
        self.assertEqual(AnswerRevision.objects.count(), before)

    def test_attachment_reader_and_new_evidence_close_old_answer_media_and_append(self):
        self.with_media()
        case = Case.objects.get(pk=self.receipt["case_id"])
        attachments.upload(
            token=self.receipt["token"],
            raw=b"synthetic researcher attachment",
            filename="research.txt",
            media_type="text/plain",
            expected_revision=case.revision,
            synthetic_fixtures_only=True,
        )
        result = self.search(kind="MEDIA")["results"]
        self.assertEqual([r["kind"] for r in result], ["ATTACHMENT"])
        resource = Resource(**result[0]["resource"])
        self.assertEqual(
            services.open_resource(**self.common, resource=resource)["raw"],
            b"synthetic researcher attachment",
        )
        before = AnswerRevision.objects.count()
        with self.assertRaisesMessage(cases.CaseConflict, "research_current_saved_answer_required"):
            self.add()
        self.assertEqual(AnswerRevision.objects.count(), before)
        self.rights.denied.add(("ATTACHMENT", "READ_MEDIA"))
        with self.assertRaises(cases.CaseConflict):
            services.open_resource(**self.common, resource=resource)

    def test_media_and_transcript_rights_revoked_before_return(self):
        self.with_media()
        resource = Resource(**self.search(kind="MEDIA")["results"][0]["resource"])
        original = media.staff_read

        def revoke(**kw):
            result = original(**kw)
            self.rights.denied.add(("ANSWER_MEDIA", "READ_MEDIA"))
            return result

        with patch.object(media, "staff_read", side_effect=revoke):
            with self.assertRaises(cases.CaseConflict):
                services.open_resource(**self.common, resource=resource)
        transcript = Resource(**self.search(kind="TRANSCRIPT")["results"][0]["resource"])
        check = services.transcripts._check_link

        def revoke_text(*args):
            result = check(*args)
            self.rights.denied.add(("TRANSCRIPT", "READ_TEXT"))
            return result

        with patch.object(services.transcripts, "_check_link", side_effect=revoke_text):
            with self.assertRaises(cases.CaseConflict):
                services.open_resource(**self.common, resource=transcript)

    def test_rights_errors_feature_off_and_query_bounds_fail_closed(self):
        source = self.source()
        with override_settings(FATWA_RESEARCH_WORKSPACE_ENABLED=False):
            with self.assertRaises(cases.CaseConflict):
                self.search()
        with patch.object(self.rights, "permits", side_effect=RuntimeError("backend unavailable")):
            with self.assertRaisesMessage(cases.CaseConflict, "research_rights_unavailable"):
                services.open_resource(**self.common, resource=source)
        for bad in (
            {"query": "x" * 81},
            {"edition_id": True},
            {"printed_page": -1},
            {"printed_part": "x" * 101},
            {"kind": "unknown"},
        ):
            with self.assertRaises(cases.CaseConflict):
                self.search(**bad)


@override_settings(**SETTINGS)
class ResearchHTTPTests(ResearchFixture, TransactionTestCase):
    def login(self, client=None):
        client = client or Client(
            enforce_csrf_checks=True, REMOTE_ADDR="127.0.0.1", HTTP_HOST="127.0.0.1"
        )
        page = client.get("/casework/staff/login/")
        logged = post(
            client,
            "/casework/staff/login/",
            {"credential": "synthetic-editor-credential-32-characters"},
            page,
        )
        self.assertEqual(logged.status_code, 303)
        return client, client.get("/casework/staff/")

    def send(self, client, page, action, **kw):
        return post(
            client,
            "/casework/staff/",
            {"action": action, "case_ref": self.receipt["public_ref"], **kw},
            page,
        )

    def test_signed_browser_bound_search_open_back_citation_and_stale(self):
        client, landing = self.login()
        self.assertContains(landing, "البحث في مصادر القضية")
        page = self.send(
            client,
            landing,
            "research_search",
            query="فرع",
            kind="REFERENCE",
            edition_id=self.catalog_id,
            printed_part="",
            printed_page="2",
        )
        self.assertEqual(page.status_code, 200)
        state = hidden(page, "state")
        opened = self.send(client, page, "research_view", state=state)
        self.assertContains(opened, "لا يوجد متن كتاب")
        back = self.send(client, opened, "research_back", state=opened.context["back_state"])
        self.assertEqual(back.context["filters"]["printed_page"], 2)
        self.assertEqual(back.context["filters"]["query"], "فرع")
        self.assertNotIn(self.transcript_text, back.content.decode())
        self.assertIn("no-store", back["Cache-Control"])
        second, landing2 = self.login()
        denied = self.send(second, landing2, "research_view", state=state)
        self.assertEqual(denied.status_code, 400)
        self.assertEqual(
            self.send(client, opened, "research_view", state=state + "broken").status_code, 400
        )
        # A canonical revision change invalidates the original open/back state.
        self.add()
        stale = self.send(client, opened, "research_back", state=opened.context["back_state"])
        self.assertEqual(stale.status_code, 409)

    def test_csrf_rights_revocation_and_scope_no_source_echo(self):
        client, landing = self.login()
        self.assertEqual(
            client.post(
                "/casework/staff/",
                {"action": "research_open", "case_ref": self.receipt["public_ref"]},
            ).status_code,
            403,
        )
        page = self.send(
            client,
            landing,
            "research_search",
            query="",
            kind="TRANSCRIPT",
            edition_id="",
            printed_part="",
            printed_page="",
        )
        state = hidden(page, "state")
        self.rights.denied.add(("TRANSCRIPT", "READ_TEXT"))
        closed = self.send(client, page, "research_view", state=state)
        self.assertEqual(closed.status_code, 409)
        self.assertNotIn(self.transcript_text, closed.content.decode())
        self.directory.identities["editor"] = replace(
            self.directory.identities["editor"], case_keys=frozenset({"other"})
        )
        self.assertEqual(self.send(client, page, "research_view", state=state).status_code, 403)

    def test_revocation_during_return_search_does_not_echo_previously_read_text(self):
        client, landing = self.login()
        page = self.send(
            client,
            landing,
            "research_search",
            query="",
            kind="TRANSCRIPT",
            edition_id="",
            printed_part="",
            printed_page="",
        )
        original = services.search

        def revoke(**kw):
            result = original(**kw)
            self.rights.denied.add(("TRANSCRIPT", "READ_TEXT"))
            return result

        with patch.object(services, "search", side_effect=revoke):
            closed = self.send(client, page, "research_view", state=hidden(page, "state"))
        self.assertEqual(closed.status_code, 409)
        self.assertNotIn(self.transcript_text, closed.content.decode())
