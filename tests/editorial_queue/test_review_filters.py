"""Read-only review subsets retain the identity and navigation of each source row."""

from dataclasses import replace
from urllib.parse import parse_qs, urlsplit

from django.test import SimpleTestCase, override_settings
from django.urls import reverse

from apps.editorial_queue.services import build_queue, select_queue

from .test_views import NavigationParser


class ReviewFilterServicesTests(SimpleTestCase):
    def test_review_subsets_partition_existing_review_rows_without_changing_source_status(self):
        rows = build_queue()
        expected = {
            "review-with-draft": ["history", "batch-synthetic-json-2"],
            "review-without-draft": ["intake-2", "batch-synthetic-csv-3"],
            "review": ["history", "intake-2", "batch-synthetic-csv-3", "batch-synthetic-json-2"],
        }
        for status, keys in expected.items():
            with self.subTest(status=status):
                matches = select_queue(rows, status=status).rows
                self.assertEqual([row.case.key for row in matches], keys)
                self.assertTrue(all(row.case.status == "review" for row in matches))
                if status != "review":
                    self.assertTrue(
                        all(
                            (row.case.record is not None) == (status == "review-with-draft")
                            for row in matches
                        )
                    )

    def test_ambiguous_external_ids_cannot_transfer_draft_presence_between_review_rows(self):
        # Synthetic variants deliberately share an external ID but keep distinct keys.
        original = build_queue()[:3]
        rows = tuple(
            replace(row, case=replace(row.case, external_id="SYN-AMBIGUOUS-REVIEW"))
            for row in (original[0], original[2])
        )
        for status, key in (
            ("review-with-draft", "history"),
            ("review-without-draft", "intake-2"),
        ):
            with self.subTest(status=status):
                selection = select_queue(rows, q="syn-ambiguous-review", status=status, key=key)
                self.assertEqual([row.case.key for row in selection.rows], [key])
                self.assertEqual(selection.selected.case.key, key)
                self.assertEqual(selection.position, 1)
                self.assertIsNone(selection.previous)
                self.assertIsNone(selection.next)


@override_settings(ALLOWED_HOSTS=["localhost"])
class ReviewFilterViewsTests(SimpleTestCase):
    def get(self, url, **extra):
        return self.client.get(url, HTTP_HOST="localhost", REMOTE_ADDR="127.0.0.1", **extra)

    def test_review_choices_are_available_and_selected_in_existing_filter_form(self):
        index = reverse("editorial_queue:index")
        response = self.get(index)
        for status in ("review-with-draft", "review-without-draft"):
            with self.subTest(status=status):
                self.assertContains(response, f'<option value="{status}">')
                filtered = self.get(index, data={"status": status})
                self.assertEqual(filtered.status_code, 200)
                self.assertContains(filtered, f'<option value="{status}" selected>')
                self.assertEqual(filtered.context["total"], 20)
                self.assertEqual(filtered.context["batches"], response.context["batches"])

    def test_review_subset_neighbors_and_return_links_keep_all_active_filters(self):
        index = reverse("editorial_queue:index")
        for status, refs, keys in (
            ("review-with-draft", "unresolved", ["history", "batch-synthetic-json-2"]),
            ("review-without-draft", "", ["intake-2", "batch-synthetic-csv-3"]),
        ):
            with self.subTest(status=status):
                filters = {"status": status}
                if refs:
                    filters["refs"] = refs
                response = self.get(index, data=filters)
                self.assertEqual(response.status_code, 200)
                rows = response.context["rows"]
                self.assertEqual([row["item"].case.key for row in rows], keys)
                for position, row in enumerate(rows):
                    detail = self.get(row["url"])
                    self.assertEqual(detail.status_code, 200)
                    self.assertEqual(detail.context["selected"].case.key, keys[position])
                    self.assertEqual(detail.context["selection"].position, position + 1)
                    self.assertEqual(
                        parse_qs(urlsplit(row["url"]).query),
                        {key: [value] for key, value in filters.items()},
                    )
                    previous = rows[position - 1]["url"] if position else None
                    following = rows[position + 1]["url"] if position == 0 else None
                    self.assertEqual(detail.context["previous_url"], previous)
                    self.assertEqual(detail.context["next_url"], following)
                    parser = NavigationParser(detail.content.decode())
                    for link in (previous, following, detail.context["return_url"]):
                        if link:
                            self.assertIn(link, parser.links)
                    returned = self.get(detail.context["return_url"])
                    self.assertEqual(returned.context["filters"], filters)
                    self.assertEqual(
                        [row["item"].case.key for row in returned.context["rows"]], keys
                    )
                    if status == "review-without-draft":
                        self.assertEqual(detail.context["history_rows"], ())
                        self.assertIsNone(detail.context["audit"])
                        self.assertNotContains(detail, "?revision=")

    def test_review_subsets_combine_with_batch_search_and_references(self):
        for status, batch, refs, q, key in (
            (
                "review-with-draft",
                "synthetic-json",
                "unresolved",
                "syn-json-2",
                "batch-synthetic-json-2",
            ),
            (
                "review-without-draft",
                "synthetic-csv",
                "verified",
                "batch-synthetic-csv-3",
                "batch-synthetic-csv-3",
            ),
        ):
            with self.subTest(status=status):
                filters = {"status": status, "batch": batch, "refs": refs, "q": q}
                response = self.get(reverse("editorial_queue:index"), data=filters)
                self.assertEqual(response.status_code, 200)
                self.assertEqual([row["item"].case.key for row in response.context["rows"]], [key])
                detail = self.get(response.context["rows"][0]["url"])
                returned = self.get(detail.context["return_url"])
                self.assertEqual(returned.context["filters"], filters)
                self.assertIsNone(detail.context["previous_url"])
                self.assertIsNone(detail.context["next_url"])

    def test_outside_subset_does_not_select_another_case_with_a_draft(self):
        url = reverse("editorial_queue:detail", args=["intake-2"])
        response = self.get(url, data={"status": "review-with-draft"})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["selected"].case.key, "intake-2")
        self.assertIsNone(response.context["selection"].position)
        self.assertIsNone(response.context["previous_url"])
        self.assertIsNone(response.context["next_url"])
        self.assertContains(response, "هذا السجل خارج التصفية الحالية")

    def test_duplicate_external_ids_remain_blocked_in_both_review_subsets(self):
        index = reverse("editorial_queue:index")
        for status in ("review-with-draft", "review-without-draft"):
            with self.subTest(status=status):
                response = self.get(index, data={"status": status, "q": "SYN-SHARED"})
                self.assertEqual(response.status_code, 200)
                self.assertEqual(response.context["rows"], ())
        response = self.get(index, data={"status": "blocked", "q": "SYN-SHARED"})
        self.assertEqual(
            [row["item"].case.key for row in response.context["rows"]],
            ["batch-synthetic-csv-2", "batch-synthetic-json-1"],
        )

    def test_malformed_filter_recovery_can_return_to_a_working_review_subset(self):
        index = reverse("editorial_queue:index")
        for query in (
            "status=review-with-draft&status=review-without-draft",
            "status=review-with-draft%00",
            "status=review-approved",
            "status=review-with-draft&q=%00",
            "status=review-without-draft&batch=unknown",
        ):
            with self.subTest(query=query):
                response = self.get(index + "?" + query)
                self.assertEqual(response.status_code, 400)
                self.assertIn(index, NavigationParser(response.content.decode()).links)
                recovered = self.get(index)
                self.assertEqual(recovered.status_code, 200)
                filtered = self.get(index, data={"status": "review-without-draft"})
                self.assertEqual(filtered.status_code, 200)
                self.assertEqual(len(filtered.context["rows"]), 2)
        malformed = self.get(
            index, data={"status": "review-without-draft", "batch": "synthetic-malformed"}
        )
        self.assertEqual(malformed.status_code, 200)
        self.assertEqual(malformed.context["rows"], ())
        self.assertContains(malformed, "MALFORMED_INPUT")
