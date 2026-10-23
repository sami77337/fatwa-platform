"""Adversarial synthetic revision contracts; no database or external source fixtures."""

from dataclasses import asdict, replace
from html.parser import HTMLParser
from unittest.mock import patch

from django.template.loader import render_to_string
from django.test import SimpleTestCase

from apps.editorial_demo.revision_comparison import compare_revisions
from apps.editorial_demo.revision_fixtures import COMPARISON_RECORD
from apps.editorial_demo.revision_history import build_history, select_revisions
from apps.fatwa_drafts.intake import serialize_intake


class _RenderedPage(HTMLParser):
    """Read actual fragment destinations and exact preformatted text after escaping."""

    def __init__(self, html):
        super().__init__(convert_charrefs=True)
        self.elements = []
        self.preformatted = []
        self._pre = None
        self.feed(html)

    def handle_starttag(self, tag, attrs):
        self.elements.append((tag, dict(attrs)))
        if tag == "pre":
            self._pre = []

    def handle_data(self, data):
        if self._pre is not None:
            self._pre.append(data)

    def handle_endtag(self, tag):
        if tag == "pre":
            self.preformatted.append("".join(self._pre))
            self._pre = None


class AdversarialComparisonTests(SimpleTestCase):
    def test_combining_bidi_supplementary_and_repeated_text_reconstruct_both_directions(self):
        base = COMPARISON_RECORD.history[0]
        before = replace(
            base, title="\u0623\u200f\U0001f469\u200d\U0001f4bb",
            answer="س" * 240 + "\u00a0\t\r\n\u202fEND ",
            reviewer_notes="\u2067\u0646\u0651\u064e\u2069\n\n",
        )
        after = replace(
            base, title="\u0627\u0654\u200e\U0001f469\u200d\U0001f52c",
            answer="س" * 120 + "X" + "س" * 120 + "\u00a0\t\n\u202fEND\t",
            reviewer_notes="\u2067\u0646\u064e\u0651\u2069\n",
        )
        snapshot = (asdict(before), asdict(after))
        for left, right in ((before, after), (after, before)):
            with self.subTest(direction=(left.title, right.title)):
                result = compare_revisions(left, right)
                self.assertEqual([target.anchor for target in result.targets],
                                 ["change-title", "change-answer", "change-reviewer_notes"])
                for field in result.fields:
                    self.assertTrue(field.changed)
                    self.assertEqual("".join(part.text for part in field.before),
                                     getattr(left, field.key))
                    self.assertEqual("".join(part.text for part in field.after),
                                     getattr(right, field.key))
                    self.assertTrue(all(part.kind in {"unchanged", "removed"}
                                        for part in field.before))
                    self.assertTrue(all(part.kind in {"unchanged", "added"}
                                        for part in field.after))
        self.assertEqual((asdict(before), asdict(after)), snapshot)

    def test_rendered_whitespace_markers_preserve_non_ascii_spaces_and_escaped_text(self):
        base = COMPARISON_RECORD.history[0]
        original = ' \t\r\n\u00a0\u202f\u200f<em>&"\U0001f600\n '
        result = compare_revisions(replace(base, answer=original),
                                   replace(base, answer=original))
        pieces = next(field.before for field in result.fields if field.key == "answer")
        normal = _RenderedPage(render_to_string(
            "editorial_demo/_revision_text.html", {"pieces": pieces}))
        marked_html = render_to_string("editorial_demo/_revision_text.html",
                                       {"pieces": pieces, "show_whitespace": True})
        marked = _RenderedPage(marked_html)
        self.assertEqual(normal.preformatted, [original])
        self.assertEqual(marked.preformatted,
                         ['·⇥␍␊\n\u00a0\u202f\u200f<em>&"\U0001f600␊\n·'])
        self.assertFalse(any(tag == "em" for tag, _ in marked.elements))
        self.assertIn("&lt;em&gt;", marked_html)
        self.assertEqual("".join(piece.text for piece in pieces), original)

    def test_same_source_id_with_distinct_pins_is_not_collapsed_during_reorder(self):
        base = COMPARISON_RECORD.history[0]
        original = base.reference_links[0]
        edition = replace(original, edition_key="SYN-SECOND-EDITION")
        archive = replace(original, source_archive_sha256="a" * 64)
        input_pin = replace(original, source_input_sha256="b" * 64)
        before = replace(base, reference_links=(original, edition, archive))
        after = replace(base, reference_links=(archive, input_pin, original))
        result = compare_revisions(before, after)
        self.assertEqual([(ref.kind, ref.position, ref.other_position)
                          for ref in result.before_references],
                         [("unchanged", 1, 3), ("removed", 2, None), ("unchanged", 3, 1)])
        self.assertEqual([(ref.kind, ref.position, ref.other_position)
                          for ref in result.after_references],
                         [("unchanged", 1, 3), ("added", 2, None), ("unchanged", 3, 1)])
        self.assertEqual([ref.reference for ref in result.after_references],
                         [archive, input_pin, original])
        self.assertEqual([target.anchor for target in result.targets], ["change-references"])


class AdversarialHistoryTests(SimpleTestCase):
    url = "/dev/editorial-preview/revision-history"

    def test_sparse_shuffled_history_uses_actual_predecessors_and_exact_snapshot_objects(self):
        first = replace(COMPARISON_RECORD.history[0], number=17)
        middle = replace(first, number=203, title="SYN-CHANGED-TITLE")
        last = replace(middle, number=999999, human_editor="SYN-OTHER-EDITOR",
                       editorial_note="SYN-METADATA-ONLY")
        record = replace(COMPARISON_RECORD, history=(last, first, middle))
        snapshot = asdict(record)
        entries = build_history(record)
        self.assertEqual([(entry.revision.number, entry.previous_number) for entry in entries],
                         [(17, None), (203, 17), (999999, 203)])
        self.assertFalse(entries[0].content_changed)
        self.assertEqual(entries[1].changed_fields, ("العنوان",))
        self.assertFalse(entries[2].content_changed)
        left, right = select_revisions(entries, "999999", "17")
        self.assertIs(left, last)
        self.assertIs(right, first)
        self.assertEqual(select_revisions(entries, "203", "203"), (middle, middle))
        self.assertEqual(asdict(record), snapshot)
        self.assertEqual(record.history, (last, first, middle))

    def test_percent_encoded_duplicate_parameter_aliases_are_rejected(self):
        for query in (
            "before=1&%62efore=1&after=2",
            "before=1&after=2&%61fter=2",
            "%62efore=1&before=2&after=2",
            "before=1&after=2&after=%32",
        ):
            with self.subTest(query=query):
                response = self.client.get(self.url + "?" + query, HTTP_HOST="localhost")
                self.assertEqual(response.status_code, 400)
                self.assertEqual(response["Cache-Control"], "no-store")

    def test_encoded_canonical_identities_get_canonical_navigation_urls(self):
        response = self.client.get(self.url + "?%62efore=%31%31&%61fter=%34",
                                   HTTP_HOST="localhost")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["before_revision"].number, 11)
        self.assertEqual(response.context["after_revision"].number, 4)
        self.assertEqual(response.context["selection_url"], self.url + "?before=11&after=4")
        page = _RenderedPage(response.content.decode())
        reverse_link = next(attrs for _, attrs in page.elements
                            if attrs.get("id") == "comparison-reverse")
        self.assertEqual(reverse_link["href"],
                         self.url + "?before=4&after=11#selected-comparison")

    def test_double_encoding_controls_and_unicode_lookalikes_are_not_revision_ids(self):
        for value in ("%2531", "%2B1", "1%00", "1%0D%0A", "%EF%BC%91", "%C2%A01"):
            for key in ("before", "after"):
                other = "after=2" if key == "before" else "before=1"
                with self.subTest(value=value, key=key):
                    response = self.client.get(self.url + f"?{key}={value}&{other}",
                                               HTTP_HOST="localhost")
                    self.assertEqual(response.status_code, 400)

    def test_sparse_reverse_selection_has_only_real_difference_and_history_destinations(self):
        first = replace(COMPARISON_RECORD.history[0], number=17, title="SYN-OLD",
                        answer="SYN-SAME-ANSWER", reviewer_notes="SYN-OLD-NOTES")
        middle = replace(first, number=203)
        last = replace(first, number=999999, title="SYN-NEW", reviewer_notes="SYN-NEW-NOTES")
        record = replace(COMPARISON_RECORD, history=(last, first, middle))
        snapshot = asdict(record)
        with patch("apps.editorial_demo.views.REVISION_HISTORY_RECORD", record):
            response = self.client.get(self.url + "?before=999999&after=17",
                                       HTTP_HOST="localhost")
        self.assertEqual(response.status_code, 200)
        self.assertIs(response.context["before_revision"], last)
        self.assertIs(response.context["after_revision"], first)
        self.assertEqual([row["previous_url"] for row in response.context["history_rows"]],
                         [None, self.url + "?before=17&after=203#selected-comparison",
                          self.url + "?before=203&after=999999#selected-comparison"])
        page = _RenderedPage(response.content.decode())
        ids = [attrs["id"] for _, attrs in page.elements if "id" in attrs]
        self.assertEqual(len(ids), len(set(ids)))
        self.assertIn("difference-nav-change-title", ids)
        self.assertIn("difference-nav-change-reviewer_notes", ids)
        self.assertNotIn("difference-nav-change-answer", ids)
        self.assertNotIn("difference-nav-change-references", ids)
        self.assertEqual([(attrs["rel"], attrs["href"]) for tag, attrs in page.elements
                          if tag == "a" and attrs.get("rel") in {"prev", "next"}],
                         [("next", "#change-reviewer_notes"), ("prev", "#change-title")])
        for tag, attrs in page.elements:
            if tag == "a" and attrs.get("href", "").startswith("#"):
                self.assertEqual(ids.count(attrs["href"][1:]), 1)
        self.assertEqual(asdict(record), snapshot)

    def test_selected_revision_cannot_replace_original_source_text_or_provenance(self):
        source = replace(
            COMPARISON_RECORD.intake, external_id="SYN-ORIGINAL-SOURCE",
            question=' \r\n\t\u2067SOURCE <b>&"\u2069\u00a0 ',
            staff_notes="\nSYN-SOURCE-NOTES\t\u202f ",
            prepared_clip_url="https://example.invalid/SYN-ORIGINAL?x=1&y=2",
        )
        replacement_ref = replace(source.reference_links[0], source_namespace="SYN-REVISION-ONLY",
                                  source_archive_sha256="c" * 64,
                                  source_input_sha256="d" * 64)
        revisions = tuple(replace(revision, answer="SYN-EDITED-ANSWER",
                                  reference_links=(replacement_ref,))
                          for revision in COMPARISON_RECORD.history)
        record = replace(COMPARISON_RECORD, intake=source, history=revisions)
        snapshot = asdict(record)
        source_bytes = serialize_intake((source,))
        with patch("apps.editorial_demo.views.REVISION_HISTORY_RECORD", record):
            response = self.client.get(self.url + "?before=2&after=1", HTTP_HOST="localhost")
        self.assertEqual(response.status_code, 200)
        self.assertIs(response.context["source"], source)
        page = _RenderedPage(response.content.decode())
        self.assertEqual(page.preformatted[-2:], [source.question, source.staff_notes])
        self.assertContains(response, "SYN-ORIGINAL-SOURCE")
        self.assertContains(response, "https://example.invalid/SYN-ORIGINAL?x=1&amp;y=2")
        self.assertContains(response, "SYN-REVISION-ONLY")
        self.assertContains(response, "c" * 64)
        self.assertContains(response, "d" * 64)
        self.assertFalse(any(tag == "b" for tag, _ in page.elements))
        self.assertFalse(any(tag == "a" and attrs.get("href", "").startswith("https:")
                             for tag, attrs in page.elements))
        self.assertEqual(asdict(record), snapshot)
        self.assertEqual(serialize_intake((source,)), source_bytes)
