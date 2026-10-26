from dataclasses import asdict, replace

from django.test import SimpleTestCase

from apps.editorial_queue.services import QueueCatalog, build_queue_catalog


class SearchTests(SimpleTestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.catalog = build_queue_catalog()

    def search(self, q, **kwargs):
        from apps.editorial_search.services import search_catalog

        return search_catalog(self.catalog, q=q, **kwargs)

    def test_arabic_matching_preserves_exact_original_and_catalog(self):
        from apps.editorial_search.services import search_catalog

        row = self.catalog.rows[0]
        original = "\n  إِجَابَةٌ عَـلَى سؤال\r\n\tﻻ <script>  "
        catalog = QueueCatalog((replace(row, case=replace(row.case, question=original)),), ())
        before = asdict(catalog)
        result = search_catalog(catalog, q="اجابة علي لا", source="question")
        self.assertEqual(result.total, 1)
        self.assertEqual(result.hits[0].fields[0].text, original)
        self.assertEqual(asdict(catalog), before)

    def test_draft_matches_link_actual_gapped_revision_numbers(self):
        result = self.search("منقح", source="draft")
        self.assertEqual([hit.revision for hit in result.hits], [2, 4, 7, 9, 11])
        self.assertTrue(all(hit.case_key == "history" for hit in result.hits))
        self.assertEqual(self.search("منقح", source="question").total, 0)

    def test_exact_question_precedes_partial_matches_without_losing_them(self):
        result = self.search("سُؤَالٌ اصطناعي", source="question")
        self.assertEqual(result.total, 12)
        self.assertEqual(
            [hit.case_key for hit in result.hits[:5]],
            ["intake-3", "history", "intake-1", "intake-2", "intake-7"],
        )

    def test_exact_technical_status_precedes_unverified_substrings(self):
        result = self.search("verified", source="reference")
        self.assertEqual(result.hits[0].case_key, "intake-1")
        self.assertIn("verified", [field.text for field in result.hits[0].fields])
        self.assertEqual(self.search("verified missing-evidence-xyz", source="reference").total, 0)

    def test_unified_ranking_keeps_source_and_batch_filters(self):
        result = self.search("سؤال اصطناعي")
        self.assertEqual((result.hits[0].source, result.hits[0].case_key), ("question", "intake-3"))
        filtered = self.search("سؤال اصطناعي", source="question", batch="synthetic-csv")
        self.assertEqual(
            [hit.case_key for hit in filtered.hits],
            ["batch-synthetic-csv-1", "batch-synthetic-csv-3", "batch-synthetic-csv-4"],
        )

    def test_exact_draft_field_ranks_before_distributed_terms_and_preserves_bytes(self):
        from apps.editorial_search.services import search_catalog

        row = self.catalog.rows[0]
        original = "\n  إِجَابَةٌ عَـلَى ﻻ e\u0301\r\n"
        history = tuple(
            replace(
                entry,
                revision=replace(
                    entry.revision,
                    title="إجابة",
                    answer="على لا e\u0301",
                    reviewer_notes=original if entry.revision.number in (4, 9) else "",
                    editorial_note="",
                ),
            )
            for entry in row.history
        )
        catalog = replace(self.catalog, rows=(replace(row, history=history),))
        before = asdict(catalog)
        result = search_catalog(catalog, q="اجابة علي لا é", source="draft")
        self.assertEqual([hit.revision for hit in result.hits], [4, 9, 1, 2, 7, 11])
        self.assertEqual(result.hits[0].fields[2].text.encode("utf-8"), original.encode("utf-8"))
        self.assertEqual(asdict(catalog), before)
        self.assertEqual(result, search_catalog(catalog, q="اجابة علي لا é", source="draft"))
        for q in ("اجابة غيرموجود", "إجابة علي لا è", "َـ"):
            with self.subTest(q=q):
                self.assertEqual(search_catalog(catalog, q=q, source="draft").total, 0)

    def test_exact_match_after_cap_is_retained_with_stable_pages(self):
        from apps.editorial_search.services import search_catalog

        row = self.catalog.rows[0]
        catalog = replace(
            self.catalog,
            rows=tuple(
                replace(row, case=replace(row.case, key=f"partial-{i}", question="سؤال مشترك"))
                for i in range(210)
            )
            + (replace(row, case=replace(row.case, key="exact", question="مُشْتَرَك")),),
        )
        first = search_catalog(catalog, q="مشترك", source="question")
        last = search_catalog(catalog, q="مشترك", source="question", page=20)
        self.assertEqual((first.total, first.pages, first.truncated), (200, 20, True))
        self.assertEqual(
            [hit.case_key for hit in first.hits],
            ["exact", *(f"partial-{i}" for i in range(9))],
        )
        self.assertEqual(
            [hit.case_key for hit in last.hits], [f"partial-{i}" for i in range(189, 199)]
        )

    def test_exactly_full_result_cap_is_not_truncated(self):
        from apps.editorial_search.services import search_catalog

        row = self.catalog.rows[0]
        catalog = replace(
            self.catalog,
            rows=tuple(
                replace(row, case=replace(row.case, key=f"exact-{i}", question="مشترك"))
                for i in range(200)
            ),
        )
        result = search_catalog(catalog, q="مشترك", source="question", page=20)
        self.assertEqual((result.total, result.pages, result.truncated), (200, 20, False))
        self.assertEqual(
            [hit.case_key for hit in result.hits], [f"exact-{i}" for i in range(190, 200)]
        )

    def test_historical_reference_is_not_assigned_current_revision(self):
        result = self.search("SYN-REMOVE", source="reference")
        revisions = {hit.revision for hit in result.hits if hit.revision is not None}
        self.assertEqual(revisions, {1, 9, 11})

    def test_batch_record_status_and_reference_evidence_are_searchable(self):
        for q, source in [("history", "record"), ("review", "status"), ("باب", "reference")]:
            with self.subTest(source=source):
                self.assertGreater(self.search(q, source=source).total, 0)
        batch = self.catalog.batches[1].batch_id
        self.assertGreater(self.search(batch, source="batch").total, 0)
        result = self.search("اصطناعي", batch=batch)
        self.assertGreater(result.total, 0)
        self.assertTrue(all(hit.batch_id == batch for hit in result.hits))

    def test_blank_no_match_and_invalid_parameters(self):
        for q in ["", "  ", "َـ", "nothing-matches-xyz"]:
            self.assertEqual(self.search(q).total, 0)
        for kwargs in [
            dict(q="a" * 81),
            dict(q="x\x00"),
            dict(q="x\u0085"),
            dict(q="x\ud800"),
            dict(q="x", source="unknown"),
            dict(q="x", batch="unknown"),
            dict(q="x", page=0),
            dict(q="x", page=True),
            dict(q="x", page=999999),
        ]:
            with self.subTest(kwargs=kwargs), self.assertRaises(ValueError):
                self.search(**kwargs)

    def test_pagination_is_stable_bounded_and_reports_cap(self):
        from apps.editorial_search.services import search_catalog

        row = self.catalog.rows[0]
        catalog = QueueCatalog(
            tuple(
                replace(row, case=replace(row.case, key=f"case-{i}", question="مشترك"))
                for i in range(210)
            ),
            self.catalog.batches,
        )
        first = search_catalog(catalog, q="مشترك", source="question")
        second = search_catalog(catalog, q="مشترك", source="question", page=2)
        self.assertEqual((len(first.hits), first.total, first.pages), (10, 200, 20))
        self.assertTrue(first.truncated)
        self.assertTrue(
            {h.case_key for h in first.hits}.isdisjoint(h.case_key for h in second.hits)
        )
        self.assertEqual(first, search_catalog(catalog, q="مشترك", source="question"))

    def test_rejected_record_has_no_revision_and_does_not_borrow_external_id(self):
        result = self.search("intake-2", source="record")
        self.assertEqual(result.total, 1)
        self.assertIsNone(result.hits[0].revision)
        self.assertEqual(result.hits[0].case_key, "intake-2")
