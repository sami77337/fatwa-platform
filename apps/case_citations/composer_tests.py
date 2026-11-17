"""Real native forms retain one unsaved answer while selecting several sources."""

from dataclasses import replace

from django.test import Client, TransactionTestCase, override_settings

from apps.casework import services as cases
from apps.casework.models import AnswerRevision, Case
from apps.reference.ingest import ingest_catalog
from tests.casework.test_http import Directory, hidden, post
from tests.reference.test_catalog import fixture

from . import services
from .models import AnswerCitation
from .tests import source_fixture


@override_settings(
    FATWA_CASE_CITATIONS_ENABLED=True,
    FATWA_CASEWORK_WEB_ENABLED=True,
    ROOT_URLCONF="apps.case_citations.urls",
)
class ComposerTests(TransactionTestCase):
    def setUp(self):
        self.edition = source_fixture()
        self.receipt = cases.intake_case(
            original_question="سؤال اصطناعي متعدد الإحالات",
            source_event_id="multi-source",
            requester_id="multi-requester",
            idempotency_key="multi-intake",
            synthetic_fixtures_only=True,
        )
        self.directory = Directory()
        self.directory.grant(self.receipt["public_ref"])
        setting = override_settings(FATWA_CASEWORK_IDENTITY_PROVIDER=self.directory)
        setting.enable()
        self.addCleanup(setting.disable)
        self.client = Client(
            enforce_csrf_checks=True, REMOTE_ADDR="127.0.0.1", HTTP_HOST="127.0.0.1"
        )
        login = self.client.get("/casework/staff/login/")
        response = post(
            self.client, "/casework/staff/login/", {"credential": self.directory.credential}, login
        )
        self.assertEqual(response.status_code, 303)
        self.page = self.open()
        self.common = dict(
            case_id=self.receipt["case_id"],
            subject_id="fixture-mufti",
            provider=self.directory,
            synthetic_fixtures_only=True,
        )

    def open(self):
        page = self.client.get("/casework/staff/")
        page = post(
            self.client,
            "/casework/staff/",
            dict(action="citations", case_ref=self.receipt["public_ref"]),
            page,
        )
        self.assertEqual(page.status_code, 200, page.content)
        return page

    def submit(self, command, form_page=None, **changes):
        page = form_page or self.page
        fields = dict(
            action="citation_compose",
            case_ref=self.receipt["public_ref"],
            workspace=hidden(page, "workspace"),
            text="  مسودة بشرية\r\nمحفوظة أثناء البحث  ",
            query="",
            edition_id=self.edition,
            part="",
            page="",
            editorial_note="تعليق أول",
            command=command,
        )
        fields.update(changes)
        response = post(self.client, "/casework/staff/", fields, page)
        return response

    def test_location_search_select_multiple_preserves_text_and_saves_complete_list(self):
        self.page = self.submit("search", part="مقدمة", page="2")
        self.assertEqual(self.page.status_code, 200, self.page.content)
        self.assertContains(self.page, f"add:{self.edition}:2")
        self.assertNotContains(self.page, f"add:{self.edition}:3")
        self.page = self.submit(f"add:{self.edition}:2", part="مقدمة", page="2")
        self.assertContains(self.page, "مسودة بشرية")
        self.page = self.submit("search", page="3")
        self.assertContains(self.page, "تعليق أول")
        self.page = self.submit(f"add:{self.edition}:3", page="3", editorial_note="تعليق ثانٍ")
        self.assertContains(self.page, "(2/12)")
        self.assertEqual(AnswerRevision.objects.count(), 0)
        self.page = self.submit("note:0", editorial_note="تعليق محرر <x>")
        self.assertContains(self.page, "تعليق محرر &lt;x&gt;")
        saved = self.submit("save", confirm="yes")
        self.assertEqual(saved.status_code, 200, saved.content)
        answer = AnswerRevision.objects.get()
        self.assertEqual(answer.text, "  مسودة بشرية\r\nمحفوظة أثناء البحث  ")
        links = services.read_citations(**self.common)
        self.assertEqual([link["source"]["source_row_id"] for link in links], [2, 3])
        self.assertEqual(links[0]["editorial_note"], "تعليق محرر <x>")
        self.assertEqual(links[1]["editorial_note"], "تعليق ثانٍ")
        self.assertEqual(AnswerCitation.objects.count(), 2)
        self.assertIn("no-store", saved["Cache-Control"])

    def test_remove_and_revise_existing_list_invalidates_approval_without_touching_old(self):
        self.page = self.submit(f"add:{self.edition}:2")
        self.page = self.submit(f"add:{self.edition}:3")
        saved = self.submit("save", confirm="yes")
        self.assertEqual(saved.status_code, 200)
        original = AnswerRevision.objects.get()
        cases.record_decision(
            **self.common,
            answer_id=original.pk,
            action="APPROVE",
            expected_revision=2,
            expected_evidence_version=1,
        )
        self.page = self.open()
        self.assertContains(self.page, "(2/12)")
        self.page = self.submit("remove:0")
        self.assertContains(self.page, "(1/12)")
        saved = self.submit("save", confirm="yes", text="جواب محرر")
        self.assertEqual(saved.status_code, 200, saved.content)
        self.assertIsNone(Case.objects.get().approved_answer_id)
        self.assertEqual(AnswerRevision.objects.count(), 2)
        self.assertEqual(AnswerCitation.objects.filter(answer=original).count(), 2)
        self.assertEqual(len(services.read_citations(**self.common)), 1)

    def test_stale_evidence_retains_draft_and_original_pins_without_creating_answer(self):
        self.page = self.submit(f"add:{self.edition}:2")
        cases.add_followup(
            token=self.receipt["token"],
            text="وقائع جديدة",
            expected_revision=1,
            synthetic_fixtures_only=True,
        )
        failed = self.submit("save", confirm="yes", text="نسخة غير محفوظة يجب ألا تضيع")
        self.assertEqual(failed.status_code, 409)
        self.assertContains(failed, "نسخة غير محفوظة يجب ألا تضيع", status_code=409)
        self.assertContains(failed, "إصدار الوقائع 1", status_code=409)
        self.assertEqual(AnswerRevision.objects.count(), 0)
        retried = self.submit("save", form_page=failed, confirm="yes")
        self.assertEqual(retried.status_code, 409)
        self.assertEqual(AnswerRevision.objects.count(), 0)

    def test_tampered_cross_case_and_cross_browser_states_rejected(self):
        self.page = self.submit(f"add:{self.edition}:2")
        denied = self.submit("save", confirm="yes", workspace=hidden(self.page, "workspace") + "x")
        self.assertEqual(denied.status_code, 400)
        other = cases.intake_case(
            original_question="قضية أخرى",
            source_event_id="other-source",
            requester_id="other",
            idempotency_key="other",
            synthetic_fixtures_only=True,
        )
        self.directory.grant(self.receipt["public_ref"], other["public_ref"])
        denied = self.submit("save", confirm="yes", case_ref=other["public_ref"])
        self.assertEqual(denied.status_code, 400)
        old = self.page
        login = self.client.get("/casework/staff/login/")
        post(
            self.client, "/casework/staff/login/", {"credential": self.directory.credential}, login
        )
        self.page = self.open()
        denied = self.submit("save", confirm="yes", workspace=hidden(old, "workspace"))
        self.assertEqual(denied.status_code, 400)
        self.assertEqual(AnswerRevision.objects.count(), 0)

    def test_duplicate_extra_and_invalid_fields_and_missing_confirmation_never_write(self):
        self.page = self.submit(f"add:{self.edition}:2")
        duplicate = self.submit(f"add:{self.edition}:2")
        self.assertContains(duplicate, "(1/12)")
        self.assertEqual(self.submit("save").status_code, 400)
        self.assertEqual(
            self.submit("save", confirm="yes", invented_source="fake").status_code, 400
        )
        self.assertEqual(self.submit("save", confirm="yes", query="x" * 101).status_code, 409)
        self.assertEqual(self.submit("save", confirm="yes", page="0").status_code, 400)
        self.assertEqual(AnswerRevision.objects.count(), 0)

    def test_search_filters_exact_edition_part_and_page_without_normalizing_source(self):
        found = services.search_sources(
            **self.common, edition_id=self.edition, printed_part="مقدمة", printed_page=2
        )
        self.assertEqual([row["source"]["source_row_id"] for row in found["results"]], [2])
        self.assertEqual(found["results"][0]["source"]["heading_title"], "فَرْعٌ تَجْرِيبِيّ")
        self.assertEqual(
            services.search_sources(
                **self.common, edition_id=self.edition, query="فصل", printed_page=2
            )["results"],
            [],
        )
        self.assertEqual(
            services.search_sources(
                **self.common, edition_id=self.edition, printed_part="غير موجود", printed_page=2
            )["results"],
            [],
        )

    def test_twelve_source_capacity_keeps_constant_form_size_and_refuses_thirteenth(self):
        editions = [self.edition]
        for key in ("second", "third"):
            spec, rows = fixture()
            spec = replace(spec, source_book_id="622", edition_key=key)
            preview = ingest_catalog(spec, rows)
            editions.append(
                ingest_catalog(
                    spec, rows, dry_run=False, expected_checksum=preview.checksum
                ).edition_id
            )
        for edition in editions:
            for row in range(1, 5):
                self.page = self.submit(f"add:{edition}:{row}", edition_id=edition)
                self.assertEqual(self.page.status_code, 200, self.page.content)
        self.assertContains(self.page, "(12/12)")
        blocked = self.submit(f"add:{self.edition}:5")
        self.assertEqual(blocked.status_code, 409)
        self.assertContains(blocked, "(12/12)", status_code=409)
        saved = self.submit("save", confirm="yes")
        self.assertEqual(saved.status_code, 200, saved.content)
        self.assertEqual(AnswerRevision.objects.count(), 1)
        self.assertEqual(AnswerCitation.objects.count(), 12)
