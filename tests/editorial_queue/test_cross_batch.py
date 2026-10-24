"""Cross-source triage uses real synthetic workbench services, without database IO."""

from dataclasses import replace
from hashlib import sha256
from unittest.mock import patch
from urllib.parse import parse_qs, urlsplit

from django.test import SimpleTestCase, override_settings
from django.urls import reverse

from apps.editorial_queue import services
from apps.editorial_workbench.services import WorkbenchDataError, build_prepared_workbench

from .test_views import NavigationParser


class CrossBatchServicesTests(SimpleTestCase):
    def test_queue_includes_both_manifests_and_preserves_prepared_cases_exactly(self):
        rows = services.build_queue()
        self.assertEqual(len(rows), 20)
        self.assertEqual(len({row.case.key for row in rows}), 20)
        self.assertEqual([row.case for row in rows[9:]], list(build_prepared_workbench().cases))
        self.assertEqual([row.batch_id for row in rows[:9]], ["original"] * 9)
        self.assertEqual(rows, services.build_queue())
        for row in rows[9:]:
            self.assertEqual(row.batch_id, row.case.batch_id)
            self.assertEqual(row.source_sha256, sha256(row.case.raw_source.encode()).hexdigest())
            self.assertEqual(bool(row.history), row.case.record is not None)
            if row.case.record:
                self.assertEqual(row.history[0].revision, row.case.record.current)

    def test_batch_counts_are_complete_even_for_malformed_input(self):
        catalog = services.build_queue_catalog()
        self.assertEqual(
            [(b.batch_id, b.total, b.ready, b.review, b.blocked) for b in catalog.batches],
            [
                ("original", 9, 1, 2, 6),
                ("synthetic-csv", 4, 1, 1, 2),
                ("synthetic-json", 4, 0, 1, 3),
                ("synthetic-jsonl", 3, 2, 0, 1),
                ("synthetic-malformed", 0, 0, 0, 0),
            ],
        )
        for summary, source in zip(catalog.batches[1:], build_prepared_workbench().batches):
            self.assertEqual(summary.source, source)
        self.assertEqual(catalog.batches[-1].source.error_code, "MALFORMED_INPUT")

    def test_duplicate_external_ids_do_not_merge_rows_or_borrow_drafts(self):
        rows = services.build_queue()
        duplicates = services.select_queue(rows, q="SYN-SHARED").rows
        self.assertEqual(
            [row.case.key for row in duplicates],
            ["batch-synthetic-csv-2", "batch-synthetic-json-1"],
        )
        for row in duplicates:
            self.assertEqual(row.case.status, "blocked")
            self.assertEqual(row.history, ())
        pending = services.select_queue(rows, status="review", batch="synthetic-csv").rows
        self.assertEqual([row.case.key for row in pending], ["batch-synthetic-csv-3"])
        self.assertEqual(pending[0].history, ())
        unresolved = services.select_queue(
            rows, batch="synthetic-json", status="review", refs="unresolved", q="SYN-JSON-2"
        ).rows
        self.assertEqual([row.case.key for row in unresolved], ["batch-synthetic-json-2"])
        self.assertEqual(len(unresolved[0].history), 1)

    def test_colliding_keys_across_sources_fail_closed(self):
        prepared = build_prepared_workbench()
        collision = replace(prepared.cases[0], key="history")
        with patch.object(
            services,
            "build_prepared_workbench",
            return_value=replace(prepared, cases=(collision, *prepared.cases[1:])),
        ):
            with self.assertRaisesRegex(WorkbenchDataError, "duplicate_case_key"):
                services.build_queue()

    def test_batch_identity_collisions_and_unlisted_members_fail_closed(self):
        prepared = build_prepared_workbench()
        for corrupted in (
            replace(
                prepared,
                batches=(replace(prepared.batches[0], batch_id="original"), *prepared.batches[1:]),
            ),
            replace(prepared, batches=(prepared.batches[0], *prepared.batches)),
            replace(
                prepared,
                cases=(replace(prepared.cases[0], batch_id="unknown"), *prepared.cases[1:]),
            ),
        ):
            with patch.object(services, "build_prepared_workbench", return_value=corrupted):
                with self.assertRaises(WorkbenchDataError):
                    services.build_queue_catalog()

    def test_immediate_neighbors_cross_source_boundary_without_losing_identity(self):
        rows = services.build_queue()
        selection = services.select_queue(rows, key="intake-8")
        self.assertEqual(selection.next.case.key, "batch-synthetic-csv-1")
        self.assertEqual(selection.position, 9)
        selection = services.select_queue(rows, key="batch-synthetic-csv-1")
        self.assertEqual(selection.previous.case.key, "intake-8")
        self.assertEqual(selection.position, 10)
        self.assertIsNone(services.select_queue(rows, key=rows[-1].case.key).next)

    def test_prepared_unicode_and_missing_references_remain_distinct_from_verified(self):
        rows = services.build_queue()
        csv = services.select_queue(rows, key="batch-synthetic-csv-1").selected
        title = services.select_queue(rows, key="batch-synthetic-jsonl-2").selected
        self.assertEqual(csv.case.question, "  سُؤَالٌ اصطناعي\r\nبسطرٍ وتشكيل e\u0301  ")
        self.assertEqual(title.case.question, "  عنوانٌ اصطناعي محفوظ  ")
        missing = services.select_queue(
            rows, batch="synthetic-jsonl", status="ready", refs="missing"
        )
        self.assertEqual([row.case.key for row in missing.rows], ["batch-synthetic-jsonl-1"])
        self.assertEqual(missing.rows[0].verified_count, 0)
        self.assertTrue(missing.rows[0].history)


@override_settings(ALLOWED_HOSTS=["localhost"])
class CrossBatchViewsTests(SimpleTestCase):
    def get(self, url, **extra):
        return self.client.get(url, HTTP_HOST="localhost", REMOTE_ADDR="127.0.0.1", **extra)

    def test_all_batch_counts_filter_and_malformed_recovery_are_navigable(self):
        index = reverse("editorial_queue:index")
        response = self.get(index)
        self.assertEqual(response.context["total"], 20)
        self.assertContains(response, 'for="batch"')
        for item in response.context["batch_rows"]:
            summary = item["summary"]
            filtered = self.get(item["url"])
            self.assertEqual(filtered.status_code, 200)
            self.assertEqual(len(filtered.context["rows"]), summary.total)
            self.assertEqual(filtered.context["selected_batch"], summary)
            self.assertEqual(filtered.context["batches"], response.context["batches"])
        malformed = self.get(index + "?batch=synthetic-malformed")
        self.assertContains(malformed, "MALFORMED_INPUT")
        self.assertContains(malformed, "لم تُنشأ سجلات")
        self.assertEqual(malformed.context["rows"], ())

    def test_combined_filters_survive_all_queue_navigation(self):
        filters = {"batch": "synthetic-csv", "status": "blocked", "refs": "unresolved", "q": "SYN"}
        response = self.get(reverse("editorial_queue:index"), data=filters)
        self.assertEqual(len(response.context["rows"]), 1)
        # Use two rejected rows to verify adjacent navigation as well.
        filters.pop("refs")
        response = self.get(reverse("editorial_queue:index"), data=filters)
        rows = response.context["rows"]
        self.assertEqual(len(rows), 2)
        for index, row in enumerate(rows):
            detail = self.get(row["url"])
            self.assertEqual(detail.context["selected"].case.key, row["item"].case.key)
            self.assertEqual(detail.context["selection"].position, index + 1)
            self.assertEqual(
                parse_qs(urlsplit(row["url"]).query), {k: [v] for k, v in filters.items()}
            )
            self.assertEqual(
                parse_qs(urlsplit(detail.context["return_url"]).query),
                {k: [v] for k, v in filters.items()},
            )
            self.assertEqual(
                detail.context["previous_url"], rows[index - 1]["url"] if index else None
            )
            self.assertEqual(
                detail.context["next_url"],
                rows[index + 1]["url"] if index + 1 < len(rows) else None,
            )
        outside = self.get(
            reverse("editorial_queue:detail", args=["history"]) + "?batch=synthetic-csv"
        )
        self.assertContains(outside, "هذا السجل خارج التصفية الحالية")
        self.assertIsNone(outside.context["selection"].position)

    def test_every_prepared_detail_opens_its_exact_workbench_record_and_revision(self):
        for case in build_prepared_workbench().cases:
            with self.subTest(key=case.key):
                detail = self.get(
                    reverse("editorial_queue:detail", args=[case.key]) + "?refs=unresolved"
                )
                self.assertEqual(detail.status_code, 200)
                self.assertEqual(detail.context["selected"].case, case)
                self.assertContains(detail, case.payload_sha256)
                workbench = self.get(detail.context["workbench_url"])
                self.assertEqual(workbench.status_code, 200)
                self.assertEqual(workbench.context["case"], case)
                self.assertNotIn("refs=", detail.context["workbench_url"])
                for row in detail.context["history_rows"]:
                    target = self.get(row["url"])
                    self.assertEqual(target.context["case"], case)
                    self.assertEqual(target.context["selected_revision"], row["entry"].revision)
                    parser = NavigationParser(target.content.decode())
                    self.assertIn(urlsplit(row["url"]).fragment, parser.ids)
                    self.assertIn(urlsplit(row["history_url"]).fragment, parser.ids)
                if case.record is None:
                    self.assertEqual(detail.context["history_rows"], ())
                    self.assertIsNone(detail.context["audit"])
                    self.assertNotContains(detail, "?revision=")
        csv = self.get(reverse("editorial_queue:detail", args=["batch-synthetic-csv-1"]))
        self.assertContains(csv, "  سُؤَالٌ اصطناعي\r\nبسطرٍ وتشكيل e\u0301  ")
        extra = self.get(reverse("editorial_queue:detail", args=["batch-synthetic-csv-4"]))
        self.assertContains(extra, "overflow-synthetic")

    def test_invalid_batch_filters_fail_safely_and_unknown_keys_do_not_fallback(self):
        index = reverse("editorial_queue:index")
        for query in (
            "batch=unknown",
            "batch=x&batch=y",
            "batch=%00",
            "batch=../x",
            "batch=" + "x" * 101,
        ):
            with self.subTest(query=query):
                self.assertEqual(self.get(index + "?" + query).status_code, 400)
        self.assertEqual(
            self.get(
                reverse("editorial_queue:detail", args=["batch-synthetic-csv-99"])
            ).status_code,
            404,
        )

    def test_malformed_batch_query_is_rejected_before_any_source_is_loaded(self):
        from apps.editorial_queue import views

        with patch.object(views, "build_queue_catalog") as build:
            for query in ("batch=x&batch=y", "batch=%00", "batch=../x", "batch=" + "x" * 101):
                self.assertEqual(
                    self.get(reverse("editorial_queue:index") + "?" + query).status_code, 400
                )
            build.assert_not_called()

    def test_prepared_detail_uses_existing_guards_and_safe_methods(self):
        url = reverse("editorial_queue:detail", args=["batch-synthetic-csv-1"])
        self.assertEqual(
            self.client.get(url, HTTP_HOST="localhost", REMOTE_ADDR="10.0.0.1").status_code, 404
        )
        with override_settings(FATWA_PRODUCTION=True):
            self.assertEqual(self.get(url).status_code, 404)
        for method in ("post", "put", "patch", "delete"):
            self.assertEqual(
                getattr(self.client, method)(url, HTTP_HOST="localhost").status_code, 405
            )
        head = self.client.head(url, HTTP_HOST="localhost", REMOTE_ADDR="127.0.0.1")
        self.assertEqual(head.status_code, 200)
        self.assertEqual(head.content, b"")
