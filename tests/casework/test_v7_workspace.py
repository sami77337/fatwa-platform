"""Scoped text search and safe conversation history on the canonical case data."""

from django.test import Client, TransactionTestCase, override_settings

from apps.casework import services as cases
from apps.requester_access_review.services import requester_snapshot
from apps.team_workspace.presentation import queue, read_workspace_case
from apps.transcript_case_links import services as transcripts
from apps.transcript_case_links.tests import bundle
from tests.casework.delivery_fixtures import CaseDeliveryFixture
from tests.casework.test_http import WEB_SETTINGS, Directory, post


class WorkspaceHistoryTests(CaseDeliveryFixture, TransactionTestCase):
    def snapshot(self, **overrides):
        return requester_snapshot(self.a["token"], synthetic_fixtures_only=True, **overrides)

    def test_search_only_current_scope_without_result_snippets(self):
        other = self.intake("UNAUTHORIZED-NEEDLE")
        cases.add_followup(
            token=self.a["token"],
            text="Requester needle followup",
            expected_revision=1,
            synthetic_fixtures_only=True,
        )
        draft = cases.save_answer(
            **self.staff(),
            text="Draft needle answer",
            expected_revision=2,
            expected_evidence_version=2,
        )
        rows = cases.list_cases(
            subject_id="synthetic-mufti",
            provider=self.directory,
            synthetic_fixtures_only=True,
        )
        for term in ("REQUESTER NEEDLE", "draft needle", self.a["public_ref"], "سؤال"):
            result = queue(rows, "all", term)
            self.assertEqual([row["public_ref"] for row in result["rows"]], [self.a["public_ref"]])
        self.assertEqual(queue(rows, "all", "UNAUTHORIZED-NEEDLE")["rows"], [])
        self.assertEqual(queue(rows, "all", other["public_ref"])["rows"], [])
        self.assertEqual(queue(rows, "waiting", "needle")["rows"], [])
        self.assertEqual(draft["revision"], 3)

    def test_timeline_keeps_exact_evidence_answer_and_chronology(self):
        literal = "  <synthetic>\nمسودة بشرية حرفية  "
        cases.add_followup(
            token=self.a["token"],
            text="تعقيب حرفي  ",
            expected_revision=1,
            synthetic_fixtures_only=True,
        )
        cases.save_answer(
            **self.staff(),
            text=literal,
            expected_revision=2,
            expected_evidence_version=2,
        )
        timeline = read_workspace_case(**self.staff())["timeline"]
        self.assertEqual([event["sequence"] for event in timeline], [1, 2, 3])
        self.assertEqual(timeline[1]["text"], "تعقيب حرفي  ")
        self.assertEqual(timeline[2]["text"], literal)
        self.assertEqual(
            [event["created_at"] for event in timeline],
            sorted(event["created_at"] for event in timeline),
        )

    def test_requester_history_excludes_internal_import_draft_notes_and_other_case(self):
        self.intake("PRIVATE-OTHER-QUESTION")
        preview = transcripts.preview(**self.staff(), bundle=bundle())
        transcripts.attach(
            **self.staff(),
            upload_id=preview["upload_id"],
            external_id=preview["entries"][0].external_id,
        )
        cases.request_clarification(
            **self.staff(),
            text="PUBLIC CLARIFICATION",
            expected_revision=2,
            expected_evidence_version=2,
        )
        cases.add_followup(
            token=self.a["token"],
            text="MY FOLLOWUP",
            expected_revision=3,
            synthetic_fixtures_only=True,
        )
        draft = cases.save_answer(
            **self.staff(),
            text="PRIVATE DRAFT",
            expected_revision=4,
            expected_evidence_version=3,
        )
        cases.record_decision(
            **self.staff(),
            answer_id=draft["answers"][-1]["id"],
            action="RETURN_FOR_CHANGES",
            note="PRIVATE REVIEW NOTE",
            expected_revision=5,
            expected_evidence_version=3,
        )
        history = self.snapshot()["requester_history"]
        self.assertEqual(
            [item["kind"] for item in history], ["question", "clarification", "followup"]
        )
        self.assertEqual(history[-1]["text"], "MY FOLLOWUP")
        self.assertEqual(history[-1]["evidence_version"], 3)
        for forbidden in (
            "PRIVATE-OTHER-QUESTION",
            "PRIVATE DRAFT",
            "PRIVATE REVIEW NOTE",
            preview["entries"][0].question.text,
            "synthetic-mufti",
            "TRANSCRIPT:",
        ):
            self.assertNotIn(forbidden, str(history))
        self.assertTrue(
            all(
                set(item)
                == {"kind", "label", "text", "evidence_version", "answer_revision", "created_at"}
                for item in history
            )
        )

    def test_only_current_proven_private_answer_revision_enters_history(self):
        self.approve()
        self.assertEqual(len(self.snapshot(show_approved_answer=True)["requester_history"]), 1)
        self.stage()
        self.deliver()
        self.assertEqual(len(self.snapshot(verifier=self.channel_verifier)["requester_history"]), 1)
        history = self.snapshot(verifier=self.channel_verifier, show_approved_answer=True)[
            "requester_history"
        ]
        self.assertEqual(history[-1]["kind"], "answer")
        self.assertEqual(history[-1]["answer_revision"], 1)
        self.assertEqual(history[-1]["text"], "")
        current = cases.read_case(**self.staff())
        cases.add_followup(
            token=self.a["token"],
            text="NEW FACTS",
            expected_revision=current["revision"],
            synthetic_fixtures_only=True,
        )
        snapshot = self.snapshot(verifier=self.channel_verifier, show_approved_answer=True)
        self.assertIsNone(snapshot["private_answer"])
        self.assertNotIn("answer", [item["kind"] for item in snapshot["requester_history"]])


@override_settings(**{**WEB_SETTINGS, "ROOT_URLCONF": "config.campaign_urls"})
class WorkspaceSearchHTTPTests(TransactionTestCase):
    def test_text_filter_renders_authorized_identifiers_without_question_or_answer_snippets(self):
        receipt = cases.intake_case(
            original_question="PRIVATE ORIGINAL UNIQUE",
            requester_id="requester-search",
            source_event_id="website-search",
            idempotency_key="search",
            synthetic_fixtures_only=True,
        )
        directory = Directory()
        directory.grant(receipt["public_ref"])
        client = Client(enforce_csrf_checks=True, REMOTE_ADDR="127.0.0.1", HTTP_HOST="127.0.0.1")
        with override_settings(FATWA_CASEWORK_IDENTITY_PROVIDER=directory):
            page = client.get("/casework/staff/login/")
            response = post(
                client,
                "/casework/staff/login/",
                {
                    "credential": directory.credential,
                },
                page,
            )
            self.assertEqual(response.status_code, 303)
            page = client.get("/casework/staff/")
            response = post(
                client,
                "/casework/staff/",
                {
                    "action": "filter",
                    "state": "draft",
                    "query": "unique",
                },
                page,
            )
            self.assertContains(response, receipt["public_ref"])
            self.assertNotContains(response, "PRIVATE ORIGINAL UNIQUE")
            self.assertIn("no-store", response["Cache-Control"])
            response = post(
                client,
                "/casework/staff/",
                {
                    "action": "filter",
                    "state": "all",
                    "query": "x" * 41,
                },
                response,
            )
            self.assertEqual(response.status_code, 400)
