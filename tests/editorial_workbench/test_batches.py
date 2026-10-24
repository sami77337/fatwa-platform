"""Bridge contracts over real deterministic synthetic preparation services."""

from dataclasses import asdict
from hashlib import sha256
from unittest.mock import patch

from django.test import SimpleTestCase, override_settings
from django.urls import reverse


class BatchBridgeTests(SimpleTestCase):
    def bridge(self):
        from apps.editorial_workbench import services

        self.assertTrue(
            hasattr(services, "build_prepared_workbench"),
            "Workbench must consume the prepared multi-batch service",
        )
        return services.build_prepared_workbench()

    def test_every_batch_row_is_visible_with_separate_receipt_and_reference_states(self):
        result = self.bridge()
        self.assertEqual(len(result.batches), 4)
        self.assertEqual(len(result.cases), 11)
        self.assertEqual(
            [case.intake_state for case in result.cases],
            [
                "valid",
                "rejected",
                "pending",
                "rejected",
                "rejected",
                "pending",
                "rejected",
                "rejected",
                "valid",
                "valid",
                "rejected",
            ],
        )
        self.assertEqual(len({case.key for case in result.cases}), 11)
        self.assertEqual(result.batches[-1].error_code, "MALFORMED_INPUT")
        self.assertTrue(result.batches[-1].recovery)
        self.assertEqual(result.batches[-1].record_count, 0)

    def test_original_unicode_and_raw_file_provenance_survive_all_formats(self):
        result = self.bridge()
        self.assertEqual(result.cases[0].question, "  سُؤَالٌ اصطناعي\r\nبسطرٍ وتشكيل e\u0301  ")
        for batch in result.batches:
            self.assertEqual(sha256(batch.raw_source.encode()).hexdigest(), batch.input_sha256)
            for case in (c for c in result.cases if c.batch_id == batch.batch_id):
                self.assertEqual(case.payload_sha256, batch.input_sha256)
                self.assertIsNone(case.source_start)
                self.assertIn("تسلسل", case.fixture_label)
        self.assertEqual(
            result.cases[0].original["reference_links"],
            '[{"source_id":"W7-SOURCE","heading_id":"W7-HEADING-1"}]',
        )
        self.assertEqual(result.cases[3].csv_extra_cells, ("overflow-synthetic",))
        self.assertEqual(result.cases[9].question, "  عنوانٌ اصطناعي محفوظ  ")

    def test_rejected_rows_cannot_shift_draft_associations_or_borrow_history(self):
        result = self.bridge()
        for case in result.cases:
            if case.record:
                self.assertEqual(case.record.intake.external_id, case.external_id)
                self.assertEqual(case.record.intake.question, case.question)
                self.assertEqual(len(case.record.history), 1)
                self.assertEqual(case.record.current.action, "received")
                self.assertEqual(case.record.current.answer, "")
            if case.intake_state == "rejected":
                self.assertIsNone(case.record)
                self.assertTrue(case.reasons)
                self.assertTrue(all(reason.recovery for reason in case.reasons))
        duplicates = [c for c in result.cases if c.external_id == "SYN-SHARED"]
        self.assertEqual(len(duplicates), 2)
        self.assertNotEqual(duplicates[0].key, duplicates[1].key)
        self.assertTrue(all(c.intake_state == "rejected" for c in duplicates))
        self.assertTrue(all(any(r.code == "duplicate_id" for r in c.reasons) for c in duplicates))
        self.assertIsNone(result.cases[2].record)
        self.assertIsNotNone(result.cases[5].record)

    def test_references_keep_original_positions_and_never_invent_verification(self):
        cases = self.bridge().cases
        verified = cases[0].references[0]
        self.assertEqual(verified["status"], "verified")
        self.assertEqual(verified["verified_identity"]["source_id"], "wave7-title-1")
        unknown = cases[5].references[0]
        self.assertNotEqual(unknown["status"], "verified")
        self.assertEqual(unknown["verified_identity"], {})
        self.assertIsNone(unknown["evidence"])
        self.assertEqual(cases[8].references, ())
        self.assertEqual(cases[8].intake_state, "valid")
        self.assertTrue(cases[8].reference_review_required)
        self.assertEqual([r["reference_ordinal"] for r in cases[10].references], [1, 2])
        self.assertNotEqual(cases[10].references[0]["status"], "verified")
        self.assertEqual(cases[10].references[1]["original_identity"]["heading_id"], "W7-HEADING-2")

    def test_fresh_results_are_deterministic_and_require_no_external_io(self):
        first = self.bridge()
        with (
            patch("builtins.open", side_effect=AssertionError("file access")),
            patch("socket.socket", side_effect=AssertionError("network access")),
        ):
            second = self.bridge()
        self.assertEqual(first, second)
        first.cases[0].original["question"] = "modified"
        self.assertEqual(second, self.bridge())

    def test_misaligned_service_provenance_or_drafts_fail_closed(self):
        self.bridge()
        from apps.editorial_workbench import batches
        from apps.editorial_workbench.services import WorkbenchDataError

        real_prepare = batches.prepare_batches
        for corruption in ("hash", "original", "draft"):

            def corrupt(*args, **kwargs):
                result = real_prepare(*args, **kwargs)
                report = result.batches[0].batch.report
                if corruption == "hash":
                    report["input_sha256"] = "0" * 64
                elif corruption == "original":
                    report["items"][0]["original"]["question"] = "unrelated"
                else:
                    report["items"][0]["draft"] = asdict(result.batches[1].batch.drafts[0])
                return result

            with (
                self.subTest(corruption=corruption),
                patch.object(batches, "prepare_batches", corrupt),
            ):
                with self.assertRaises(WorkbenchDataError):
                    self.bridge()


@override_settings(ALLOWED_HOSTS=["localhost"])
class BatchNavigationTests(SimpleTestCase):
    def get(self, url):
        return self.client.get(url, HTTP_HOST="localhost", REMOTE_ADDR="127.0.0.1")

    def test_filter_select_and_follow_each_records_own_history(self):
        index = reverse("editorial_workbench:index")
        response = self.get(index + "?batch=synthetic-csv")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.context["cases"]), 4)
        self.assertContains(response, "synthetic-csv")
        self.assertContains(response, 'name="batch" id="batch"')
        self.assertContains(response, 'value="synthetic-csv" selected')
        for row in response.context["detail_rows"]:
            detail = self.get(row["url"])
            self.assertEqual(detail.status_code, 200)
            case = detail.context["case"]
            self.assertEqual(case.key, row["case"].key)
            self.assertIn("batch=synthetic-csv", detail.context["return_url"])
            if case.record:
                self.assertEqual(detail.context["selected_revision"], case.record.current)
                history = self.get(detail.context["history_rows"][0]["url"])
                self.assertEqual(history.context["case"].external_id, case.external_id)
            else:
                self.assertEqual(detail.context["history_rows"], ())
                self.assertEqual(self.get(row["url"] + "&revision=1").status_code, 400)
        ready = response.context["detail_rows"][0]["url"]
        self.assertEqual(self.get(ready + "&revision=7").status_code, 404)

    def test_batch_errors_recovery_navigation_and_filters_remain_read_only(self):
        index = reverse("editorial_workbench:index")
        response = self.get(index)
        self.assertContains(response, "MALFORMED_INPUT")
        self.assertContains(response, "معالجة")
        empty = self.get(index + "?batch=synthetic-malformed")
        self.assertEqual(empty.status_code, 200)
        self.assertEqual(empty.context["cases"], ())
        self.assertContains(empty, "MALFORMED_INPUT")
        for query in ("batch=unknown", "batch=synthetic-csv&batch=synthetic-json", "file=x"):
            self.assertEqual(self.get(index + "?" + query).status_code, 400)
        detail = self.get(reverse("editorial_workbench:detail", args=["batch-synthetic-csv-1"]))
        self.assertEqual(detail.status_code, 200)
        self.assertContains(detail, 'aria-label="التنقل بين سجلات الدفعة"')
        self.assertContains(detail, "SYN-SHARED")
        self.assertNotContains(detail, 'type="file"')
        self.assertEqual(self.client.post(index, HTTP_HOST="localhost").status_code, 405)
