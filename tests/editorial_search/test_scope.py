"""Synthetic case/revision scopes and round-trip reference navigation."""

from dataclasses import replace
from unittest.mock import patch
from urllib.parse import parse_qs, urlsplit

from django.test import SimpleTestCase, override_settings

from apps.editorial_queue.services import build_queue_catalog
from apps.editorial_search.services import search_catalog
from tests.editorial_search.test_views import SearchMarkup


class SearchScopeTests(SimpleTestCase):
    def setUp(self):
        self.catalog = build_queue_catalog()

    def test_case_scope_uses_exact_key_and_intersects_source_and_batch(self):
        result = search_catalog(
            self.catalog, q="اصطناعي", case_key="intake-1", source="question", batch="original"
        )
        self.assertEqual(len(result.hits), 1)
        self.assertEqual(result.hits[0].case_key, "intake-1")
        self.assertEqual(result.hits[0].source, "question")
        self.assertEqual(
            search_catalog(self.catalog, q="original", case_key="intake-1", source="batch").total, 0
        )
        self.assertEqual(search_catalog(self.catalog, q="", case_key="intake-1").total, 0)
        self.assertEqual(search_catalog(self.catalog, q="ـَ", case_key="intake-1").total, 0)

    def test_revision_scope_uses_actual_gapped_number_not_position(self):
        for number in (2, 4, 7, 9, 11):
            result = search_catalog(
                self.catalog, q="منقح", source="draft", case_key="history", revision=number
            )
            self.assertEqual(len(result.hits), 1)
            self.assertEqual(result.hits[0].revision, number)
            self.assertEqual(result.hits[0].anchor, "snapshot")

    def test_current_revision_scope_excludes_current_diagnostic_occurrences(self):
        result = search_catalog(
            self.catalog, q="SYN", source="reference", case_key="history", revision=11
        )
        self.assertTrue(result.hits)
        self.assertTrue(all(hit.reference_origin == "revision" for hit in result.hits))
        row = next(row for row in self.catalog.rows if row.case.key == "history")
        current = next(entry.revision for entry in row.history if entry.revision.number == 11)
        self.assertEqual(result.total, len(current.reference_links))
        self.assertEqual(
            search_catalog(
                self.catalog, q="اصطناعي", source="question", case_key="history", revision=11
            ).total,
            0,
        )

    def test_scope_validation_fails_even_for_empty_query(self):
        for params in (
            {"case_key": "unknown"},
            {"case_key": "history", "revision": 3},
            {"case_key": "intake-2", "revision": 1},
            {"case_key": "history", "batch": "synthetic-csv"},
            {"case_key": "history", "revision": True},
            {"revision": 11},
            {"case_key": "../history"},
            {"case_key": "x" * 101},
        ):
            with self.subTest(params=params), self.assertRaises(ValueError):
                search_catalog(self.catalog, q="", **params)

    def test_scope_is_applied_before_cap_and_pagination(self):
        row = self.catalog.rows[0]
        catalog = replace(
            self.catalog,
            rows=tuple(
                replace(row, case=replace(row.case, key=f"case-{i}", question="مشترك"))
                for i in range(205)
            ),
        )
        scoped = search_catalog(catalog, q="مشترك", source="question", case_key="case-204")
        self.assertEqual(scoped.total, 1)
        self.assertFalse(scoped.truncated)
        self.assertEqual(scoped.hits[0].case_key, "case-204")
        with self.assertRaises(ValueError):
            search_catalog(catalog, q="مشترك", source="question", case_key="case-204", page=2)

    def test_ambiguous_case_or_revision_is_rejected(self):
        row = next(row for row in self.catalog.rows if row.case.key == "history")
        with self.assertRaises(ValueError):
            search_catalog(replace(self.catalog, rows=(row, row)), q="SYN", case_key="history")
        duplicate = replace(row, history=(row.history[0], row.history[0]))
        with self.assertRaises(ValueError):
            search_catalog(
                replace(self.catalog, rows=(duplicate,)), q="SYN", case_key="history", revision=1
            )


@override_settings(ALLOWED_HOSTS=["localhost"])
class SearchScopeViewTests(SimpleTestCase):
    def get(self, url="/dev/editorial-search", **kwargs):
        return self.client.get(url, HTTP_HOST="localhost", REMOTE_ADDR="127.0.0.1", **kwargs)

    def test_form_exposes_real_revision_choices_and_clear_scope(self):
        response = self.get(
            data={
                "q": "منقح",
                "case_key": "history",
                "revision": 7,
                "source": "draft",
                "batch": "original",
            }
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'name="case_key" value="history"')
        self.assertContains(response, '<option value="7" selected>المراجعة 7</option>')
        self.assertNotContains(response, '<option value="3">المراجعة 3</option>')
        clear_url = response.context["clear_scope_url"]
        self.assertIn(clear_url, SearchMarkup(response.content.decode()).links)
        self.assertEqual(
            parse_qs(urlsplit(clear_url).query),
            {"q": ["منقح"], "source": ["draft"], "batch": ["original"], "page": ["1"]},
        )
        cleared = self.get(clear_url)
        self.assertEqual([row["hit"].revision for row in cleared.context["rows"]], [2, 4, 7, 9, 11])

    def test_result_link_scopes_to_its_case_without_stale_pagination(self):
        response = self.get(data={"q": "اصطناعي", "source": "question", "batch": "original"})
        row = response.context["rows"][0]
        scoped = self.get(row["case_search_url"])
        self.assertEqual(scoped.status_code, 200)
        self.assertEqual(scoped.context["filters"]["case_key"], row["hit"].case_key)
        self.assertEqual(scoped.context["filters"]["page"], 1)
        self.assertTrue(
            all(hit.case_key == row["hit"].case_key for hit in scoped.context["result"].hits)
        )

    def test_reference_card_keeps_scoped_return_and_uses_exact_revision_scope_link(self):
        response = self.get(
            data={"q": "SYN", "source": "reference", "case_key": "history", "revision": 9}
        )
        row = response.context["rows"][0]
        card = self.get(row["reference_url"])
        self.assertEqual(card.status_code, 200)
        self.assertEqual(card.context["card"].revision, 9)
        self.assertEqual(parse_qs(urlsplit(card.context["return_url"]).query)["revision"], ["9"])
        self.assertEqual(
            self.get(card.context["return_url"]).context["result"], response.context["result"]
        )
        scoped = self.get(card.context["revision_search_url"])
        self.assertEqual(scoped.context["filters"]["case_key"], "history")
        self.assertEqual(scoped.context["filters"]["revision"], 9)
        all_case = self.get(card.context["case_search_url"])
        self.assertNotIn("revision", all_case.context["filters"])

    def test_pagination_preserves_case_scope_through_card_return(self):
        first = self.get(data={"q": "SYN", "source": "reference", "case_key": "history"})
        second = self.get(first.context["next_url"])
        self.assertEqual(second.context["filters"]["case_key"], "history")
        self.assertEqual(second.context["filters"]["page"], 2)
        row = next(
            row for row in second.context["rows"] if row["hit"].reference_origin == "revision"
        )
        card = self.get(row["reference_url"])
        returned = self.get(card.context["return_url"])
        self.assertEqual(returned.context["result"], second.context["result"])

    def test_return_revision_does_not_override_card_path_identity(self):
        response = self.get(
            "/dev/editorial-search/references/history/revisions/9/1",
            data={"q": "SYN", "case_key": "history", "revision": 11},
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["card"].revision, 9)
        self.assertEqual(
            parse_qs(urlsplit(response.context["return_url"]).query)["revision"], ["11"]
        )
        self.assertEqual(
            parse_qs(urlsplit(response.context["revision_search_url"]).query)["revision"], ["9"]
        )

    def test_revision_scope_survives_pagination_and_duplicate_occurrence_card(self):
        catalog = build_queue_catalog()
        row = next(row for row in catalog.rows if row.case.key == "history")
        entry = row.history[0]
        revision = replace(
            entry.revision, reference_links=(entry.revision.reference_links[0],) * 12
        )
        scoped_row = replace(row, history=(replace(entry, revision=revision),))
        with patch(
            "apps.editorial_search.views.build_queue_catalog",
            return_value=replace(catalog, rows=(scoped_row,)),
        ):
            first = self.get(
                data={
                    "q": "SYN",
                    "source": "reference",
                    "case_key": "history",
                    "revision": revision.number,
                }
            )
            second = self.get(first.context["next_url"])
            self.assertEqual(second.context["filters"]["revision"], revision.number)
            self.assertEqual(second.context["filters"]["case_key"], "history")
            self.assertEqual(
                [hit.reference_ordinal for hit in second.context["result"].hits], [11, 12]
            )
            card = self.get(second.context["rows"][1]["reference_url"])
            self.assertEqual(card.context["card"].ordinal, 12)
            self.assertEqual(
                self.get(card.context["return_url"]).context["result"], second.context["result"]
            )

    def test_malformed_scope_rejected_before_loading_and_unknown_scope_fails_closed(self):
        with patch("apps.editorial_search.views.build_queue_catalog") as build:
            for query in (
                "case_key=a&case_key=b",
                "case_key=../private",
                "revision=1",
                "case_key=history&revision=01",
                "case_key=history&revision=0",
                "case_key=history&revision=1&revision=2",
                "case_key=history&revision=2147483648",
                "case_key=history&revision=١",
            ):
                with self.subTest(query=query):
                    self.assertEqual(self.get("/dev/editorial-search?" + query).status_code, 400)
            build.assert_not_called()
        for params in (
            {"case_key": "missing"},
            {"case_key": "history", "revision": 3},
            {"case_key": "history", "batch": "synthetic-csv"},
        ):
            with self.subTest(params=params):
                self.assertEqual(self.get(data=params).status_code, 400)
