"""New history explorer contracts only; accepted comparison suites are not rerun."""

import os
from dataclasses import asdict, replace
from unittest.mock import patch

from django.test import RequestFactory, SimpleTestCase, override_settings
from django.urls import resolve

from apps.editorial_demo.revision_comparison import compare_revisions
from apps.editorial_demo.revision_fixtures import COMPARISON_RECORD
from apps.fatwa_drafts.intake import serialize_intake
from tests.editorial_demo.test_revision_compare import PageStructure


class HistoryServiceTests(SimpleTestCase):
    def setUp(self):
        from apps.editorial_demo.revision_fixtures import REVISION_HISTORY_RECORD
        from apps.editorial_demo.revision_history import build_history, select_revisions

        self.record = REVISION_HISTORY_RECORD
        self.build = build_history
        self.select = select_revisions

    def test_chronological_order_does_not_depend_on_tuple_position(self):
        shuffled = replace(self.record, history=self.record.history[::-1])
        rows = self.build(shuffled)
        self.assertEqual([row.revision.number for row in rows], [1, 2, 4, 7, 9, 11])
        self.assertEqual([row.previous_number for row in rows], [None, 1, 2, 4, 7, 9])
        self.assertEqual(shuffled.history[0].number, 11)

    def test_summaries_derive_text_reference_and_position_changes(self):
        rows = {row.revision.number: row for row in self.build(self.record)}
        self.assertEqual(rows[2].changed_fields,
                         ("العنوان", "نص المسودة — حقل التحرير البشري", "ملاحظات المراجع"))
        self.assertEqual((rows[2].references_added, rows[2].references_removed), (1, 1))
        self.assertEqual(rows[4].changed_fields, ("العنوان", "نص المسودة — حقل التحرير البشري"))
        self.assertEqual(rows[7].changed_fields, ())
        self.assertEqual(rows[7].reference_positions_changed, 2)
        self.assertEqual(rows[9].changed_fields, ("ملاحظات المراجع",))
        self.assertEqual(rows[9].references_added, 1)
        self.assertEqual(rows[11].changed_fields, ())
        self.assertFalse(rows[11].content_changed)
        self.assertEqual(rows[1].action_label, "لقطة اصطناعية ثابتة")

    def test_selection_uses_identities_and_preserves_requested_direction(self):
        entries = self.build(self.record)
        before, after = self.select(entries, "11", "4")
        self.assertIs(before, self.record.history[-1])
        self.assertEqual(after.number, 4)
        self.assertEqual(self.select(entries, "7", "7")[0].number, 7)

    def test_invalid_or_absent_identities_are_rejected(self):
        from apps.editorial_demo.revision_history import InvalidRevisionId, UnknownRevisionId

        entries = self.build(self.record)
        for value in (None, "", "01", "-1", "0", "1.0", "١", " 1", "1\n", 1, True,
                      "1" * 1000):
            for first in (True, False):
                with self.subTest(value=value, first=first), self.assertRaises(InvalidRevisionId):
                    self.select(entries, value if first else "1", "1" if first else value)
        for value in ("3", "999999"):
            with self.assertRaises(UnknownRevisionId):
                self.select(entries, value, "1")

    def test_invalid_history_cannot_produce_ambiguous_selection(self):
        from apps.editorial_demo.revision_history import HistoryDataError

        first = self.record.history[0]
        for history in ((), [], (None,), (first, first), (replace(first, number=True),),
                        (replace(first, number=0),), (replace(first, number=1000000),),
                        (replace(first, human_editor=None),), (first,) * 101):
            with self.subTest(history=history), self.assertRaises(HistoryDataError):
                self.build(replace(self.record, history=history))

    def test_source_and_accepted_two_revision_fixture_are_unchanged(self):
        original = asdict(self.record)
        source_bytes = serialize_intake((self.record.intake,))
        entries = self.build(self.record)
        before, after = self.select(entries, "1", "11")
        compare_revisions(before, after)
        self.assertEqual(asdict(self.record), original)
        self.assertEqual(serialize_intake((self.record.intake,)), source_bytes)
        self.assertIs(self.record.intake, COMPARISON_RECORD.intake)
        self.assertEqual(self.record.history[:2], COMPARISON_RECORD.history)
        self.assertEqual(len(COMPARISON_RECORD.history), 2)
        self.assertEqual(entries, self.build(self.record))


class HistoryRouteTests(SimpleTestCase):
    url = "/dev/editorial-preview/revision-history"

    def get(self, query=None, **kwargs):
        return self.client.get(self.url, data=query or {}, HTTP_HOST="localhost", **kwargs)

    def test_history_browsing_is_available_without_a_comparison(self):
        response = self.get()
        self.assertEqual(response.status_code, 200)
        self.assertEqual(resolve(self.url).url_name, "editorial_revision_history")
        self.assertContains(response, '<html lang="ar" dir="rtl">')
        self.assertIsNone(response.context["comparison"])
        self.assertContains(response, "اختر مراجعتين لعرض المقارنة")
        self.assertNotContains(response, 'id="change-title"')
        structure = PageStructure(response.content.decode())
        ids = [attrs["id"] for tag, attrs in structure.elements
               if tag == "li" and attrs.get("id", "").startswith("revision-")]
        self.assertEqual(ids, ["revision-1", "revision-2", "revision-4", "revision-7",
                               "revision-9", "revision-11"])

    def test_all_available_pairs_can_be_selected(self):
        numbers = (1, 2, 4, 7, 9, 11)
        for before in numbers:
            for after in numbers:
                with self.subTest(before=before, after=after):
                    response = self.get({"before": str(before), "after": str(after)})
                    self.assertEqual(response.status_code, 200)
                    self.assertEqual(response.context["before_revision"].number, before)
                    self.assertEqual(response.context["after_revision"].number, after)
                    self.assertEqual(response.context["selection_url"],
                                     self.url + f"?before={before}&after={after}")

    def test_url_state_is_deterministic_and_preserved_in_timeline_links(self):
        response = self.get({"after": "7", "before": "4"})
        self.assertEqual(response.context["selection_url"], self.url + "?before=4&after=7")
        row = next(row for row in response.context["history_rows"]
                   if row["entry"].revision.number == 9)
        self.assertEqual(row["before_url"], self.url + "?before=9&after=7#selected-comparison")
        self.assertEqual(row["after_url"], self.url + "?before=4&after=9#selected-comparison")
        self.assertEqual(row["previous_url"], self.url + "?before=7&after=9#selected-comparison")
        structure = PageStructure(response.content.decode())
        self.assertIn(("form", {"method": "get", "action": self.url + "#selected-comparison",
                                "aria-label": "اختيار مراجعتين من التاريخ"}), structure.elements)
        self.assertEqual([attrs["value"] for tag, attrs in structure.elements
                          if tag == "option" and "selected" in attrs], ["4", "7"])

    def test_incomplete_invalid_duplicate_and_unknown_inputs_fail_closed(self):
        for query in ({"before": "1"}, {"after": "2"}, {"before": "", "after": "2"},
                      {"before": "01", "after": "2"}, {"before": "١", "after": "2"},
                      {"before": "0", "after": "2"}, {"before": "1", "after": "-2"},
                      {"before": ["1", "2"], "after": "4"}, {"unknown": "x"},
                      {"before": "<script>x</script>", "after": "2"}):
            with self.subTest(query=query):
                response = self.get(query)
                self.assertEqual(response.status_code, 400)
                self.assertNotIn(b"<script>", response.content)
        for query in ({"before": "3", "after": "2"}, {"before": "1", "after": "999999"}):
            self.assertEqual(self.get(query).status_code, 404)
        self.assertEqual(self.client.head(self.url + "?before=1", HTTP_HOST="localhost").status_code,
                         400)

    def test_unchanged_same_identity_and_distinct_snapshots(self):
        for before, after in (("4", "4"), ("9", "11")):
            response = self.get({"before": before, "after": after})
            self.assertFalse(response.context["comparison"].changed)
            self.assertContains(response, "لا توجد فروق")
        self.assertContains(self.get(), "لم يتغير محتوى المقارنة")

    def test_selected_text_and_reference_order_match_immutable_snapshots(self):
        response = self.get({"before": "1", "after": "9"})
        result = response.context["comparison"]
        for field in result.fields:
            self.assertEqual("".join(p.text for p in field.before),
                             getattr(response.context["before_revision"], field.key))
            self.assertEqual("".join(p.text for p in field.after),
                             getattr(response.context["after_revision"], field.key))
        self.assertEqual([entry.reference.source_id for entry in result.after_references],
                         ["SYN-ADD", "SYN-REMOVE", "SYN-KEEP"])
        self.assertContains(response, "␍")
        self.assertContains(response, "⇥")
        changed = self.get({"before": "1", "after": "2"}).context["comparison"]
        self.assertEqual([entry.kind for entry in changed.before_references], ["unchanged", "removed"])
        self.assertEqual([entry.kind for entry in changed.after_references], ["unchanged", "added"])
        moved = self.get({"before": "4", "after": "7"})
        self.assertContains(moved, "الموضع في النسخة المقابلة 2")

    def test_xss_is_escaped_in_timeline_metadata_and_shared_comparison(self):
        from apps.editorial_demo.revision_fixtures import REVISION_HISTORY_RECORD

        payload = '<script>alert("synthetic")</script>'
        record = replace(REVISION_HISTORY_RECORD, history=tuple(
            replace(revision, action=payload, human_editor=payload, editorial_note=payload,
                    title=payload, answer=payload, reviewer_notes=payload)
            for revision in REVISION_HISTORY_RECORD.history
        ))
        with patch("apps.editorial_demo.views.REVISION_HISTORY_RECORD", record):
            response = self.get({"before": "1", "after": "11"})
        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, payload)
        self.assertContains(response, "&lt;script&gt;")
        structure = PageStructure(response.content.decode())
        self.assertFalse(any(tag in {"script", "iframe", "textarea"} for tag, _ in structure.elements))

    def test_keyboard_navigation_labels_and_targets_exist(self):
        response = self.get({"before": "1", "after": "11"})
        structure = PageStructure(response.content.decode())
        ids = {attrs["id"]: attrs for _, attrs in structure.elements if "id" in attrs}
        self.assertEqual(ids["selected-comparison"].get("tabindex"), "-1")
        for tag, attrs in structure.elements:
            if tag == "a" and attrs.get("href", "").startswith("#"):
                self.assertIn(attrs["href"][1:], ids)
            if attrs.get("id", "").startswith("revision-"):
                self.assertEqual(attrs.get("tabindex"), "-1")
        self.assertTrue({"before", "after"} <= {
            attrs.get("for") for tag, attrs in structure.elements if tag == "label"})
        self.assertTrue(any(tag == "nav" and attrs.get("aria-label") == "التنقل في سجل المراجعات"
                            for tag, attrs in structure.elements))

    def test_difference_shortcuts_skip_unchanged_fields(self):
        for before, after, count, first, last in (
            ("1", "2", 4, "change-title", "change-references"),
            ("4", "7", 1, "change-references", None),
            ("7", "9", 2, "change-reviewer_notes", "change-references"),
        ):
            with self.subTest(before=before, after=after):
                response = self.get({"before": before, "after": after})
                structure = PageStructure(response.content.decode())
                elements = {attrs["id"]: (tag, attrs) for tag, attrs in structure.elements
                            if "id" in attrs}
                self.assertContains(response, f"مجموعات الفروق: {count}")
                self.assertEqual(elements["comparison-first-difference"][0], "a")
                self.assertEqual(elements["comparison-first-difference"][1]["href"], "#" + first)
                self.assertEqual(elements[first][1].get("tabindex"), "-1")
                if last is None:
                    self.assertNotIn("comparison-last-difference", elements)
                else:
                    self.assertEqual(elements["comparison-last-difference"][0], "a")
                    self.assertEqual(elements["comparison-last-difference"][1]["href"], "#" + last)
                    self.assertEqual(elements[last][1].get("tabindex"), "-1")
                self.assertEqual(elements["comparison-change-index"][1]["href"], "#changes")

    def test_comparison_context_distinguishes_reverse_and_same_identity(self):
        for before, after, direction in (
            ("1", "11", "باتجاه ترتيب السجل"),
            ("11", "4", "بعكس ترتيب السجل"),
            ("4", "4", "المراجعة نفسها في طرفي المقارنة"),
        ):
            with self.subTest(before=before, after=after):
                response = self.get({"before": before, "after": after})
                self.assertContains(response, direction)
                structure = PageStructure(response.content.decode())
                elements = {attrs["id"]: (tag, attrs) for tag, attrs in structure.elements
                            if "id" in attrs}
                self.assertEqual(elements["selected-comparison"][1]["aria-labelledby"],
                                 "selected-comparison-heading")
                self.assertEqual(elements["comparison-tools"][1]["aria-describedby"],
                                 "comparison-summary comparison-direction")
                self.assertEqual(elements["comparison-edit-selection"][1]["href"], "#selection")
                if before == after:
                    self.assertNotIn("comparison-reverse", elements)
                else:
                    self.assertEqual(elements["comparison-reverse"][1]["href"], self.url
                                     + f"?before={after}&after={before}#selected-comparison")

    def test_no_difference_shortcuts_for_equal_or_unselected_content(self):
        for query in ({}, {"before": "4", "after": "4"}, {"before": "9", "after": "11"}):
            with self.subTest(query=query):
                response = self.get(query)
                structure = PageStructure(response.content.decode())
                ids = {attrs["id"] for _, attrs in structure.elements if "id" in attrs}
                self.assertFalse({"comparison-first-difference", "comparison-last-difference",
                                  "comparison-change-index"} & ids)
                if query:
                    self.assertContains(response, "مجموعات الفروق: 0")
                    self.assertContains(response, "لا يتغير محتوى المقارنة")
                else:
                    self.assertNotIn("comparison-tools", ids)

    def test_selection_help_is_connected_to_native_keyboard_controls(self):
        response = self.get({"before": "4", "after": "7"})
        structure = PageStructure(response.content.decode())
        elements = {attrs["id"]: (tag, attrs) for tag, attrs in structure.elements if "id" in attrs}
        self.assertIn("selection-help", elements)
        for name in ("before", "after"):
            self.assertEqual(elements[name][0], "select")
            self.assertEqual(elements[name][1].get("aria-describedby"), "selection-help")
        for name in ("comparison-first-difference", "comparison-change-index",
                     "comparison-edit-selection", "comparison-reverse"):
            tag, attrs = elements[name]
            self.assertEqual(tag, "a")
            self.assertNotIn("tabindex", attrs)
            self.assertNotIn("onclick", attrs)
        self.assertFalse(any(tag == "script" for tag, _ in structure.elements))

    def test_get_head_unsafe_methods_and_headers(self):
        from apps.editorial_demo.views import revision_history

        for suffix in ("", "?before=1&after=11"):
            response = self.client.head(self.url + suffix, HTTP_HOST="localhost")
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.content, b"")
            self.assertEqual(response["Cache-Control"], "no-store")
        for method in ("post", "put", "patch", "delete", "options", "trace"):
            response = getattr(self.client, method)(self.url, HTTP_HOST="localhost")
            self.assertEqual(response.status_code, 405)
            self.assertEqual(response["Allow"], "GET, HEAD")
            request = getattr(RequestFactory(), method)(self.url, HTTP_HOST="localhost")
            self.assertEqual(revision_history(request).status_code, 405)

    @override_settings(ALLOWED_HOSTS=["*"])
    def test_loopback_and_production_restrictions(self):
        self.assertEqual(self.client.get(self.url, HTTP_HOST="example.invalid").status_code, 404)
        for peer in ("192.0.2.1", "", "invalid"):
            self.assertEqual(self.get(REMOTE_ADDR=peer).status_code, 404)
        self.assertEqual(self.client.get(self.url, HTTP_HOST="[::1]", REMOTE_ADDR="::1").status_code,
                         200)
        with patch.dict(os.environ, {"FATWA_PRODUCTION": "1"}):
            self.assertEqual(self.get().status_code, 404)
        with override_settings(FATWA_PRODUCTION=True):
            self.assertEqual(self.get().status_code, 404)
        with override_settings(SETTINGS_MODULE="config.settings.production"):
            self.assertEqual(self.get().status_code, 404)

    @override_settings(DATA_UPLOAD_MAX_NUMBER_FIELDS=2)
    def test_too_many_parameters_are_rejected(self):
        self.assertEqual(self.get({"a": "1", "b": "2", "c": "3"}).status_code, 400)

    def test_ambiguous_fixture_history_is_unavailable(self):
        record = replace(COMPARISON_RECORD, history=(COMPARISON_RECORD.history[0],) * 2)
        with patch("apps.editorial_demo.views.REVISION_HISTORY_RECORD", record):
            response = self.get({"before": "1", "after": "1"})
        self.assertEqual(response.status_code, 503)
        self.assertNotContains(response, "Traceback", status_code=503)

    def test_missing_fixture_source_is_unavailable(self):
        from apps.editorial_demo.revision_fixtures import REVISION_HISTORY_RECORD

        record = replace(REVISION_HISTORY_RECORD, intake=None)
        with patch("apps.editorial_demo.views.REVISION_HISTORY_RECORD", record):
            response = self.get({"before": "1", "after": "11"})
        self.assertEqual(response.status_code, 503)
        self.assertNotContains(response, "Traceback", status_code=503)

    def test_shared_template_keeps_accepted_comparison_entry_point(self):
        response = self.client.get("/dev/editorial-preview/revision-compare", HTTP_HOST="localhost")
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'action="/dev/editorial-preview/revision-compare"')
        self.assertContains(response, 'id="change-title"')
        self.assertContains(response, self.url)
        self.assertEqual(len(response.context["revisions"]), 2)
