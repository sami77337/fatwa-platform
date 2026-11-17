"""Original Arabic text, match semantics and safe result-field navigation."""

from dataclasses import replace
from html.parser import HTMLParser
from unittest.mock import patch

from django.test import SimpleTestCase, override_settings

from apps.editorial_queue.services import build_queue_catalog
from apps.editorial_search.highlights import MAX_MATCHES, MAX_TEXT_LENGTH, highlight
from apps.editorial_search.services import search_catalog


class HighlightTests(SimpleTestCase):
    def marked(self, text, query, kind="words"):
        result = highlight(text, query, kind)
        self.assertEqual("".join(segment.text for segment in result.segments), text)
        return [segment.text for segment in result.segments if segment.matched]

    def test_arabic_diacritics_tatweel_alef_and_maqsura_keep_original_text(self):
        self.assertEqual(
            self.marked("  إِجَابَةٌ عَـلَى سُؤَالٍ  ", "اجابة علي"),
            ["إِجَابَةٌ", "عَـلَى"],
        )
        self.assertEqual(self.marked("أ\u0654ثَرٌ", "اثر"), ["أ\u0654ثَرٌ"])

    def test_nfkc_ligature_casefold_and_combining_cluster_offsets(self):
        self.assertEqual(self.marked("ﻻ ملاحظة", "لا"), ["ﻻ", "لا"])
        self.assertEqual(self.marked("e\u0301 ثم إِجَابَةٌ", "é اجابة"), ["e\u0301", "إِجَابَةٌ"])
        self.assertEqual(self.marked("Straße", "STRASSE", "exact"), ["Straße"])

    def test_synonyms_use_the_full_original_word_and_existing_word_boundaries(self):
        self.assertEqual(
            self.marked("بِدُون مقطع بلا مثال دون تعليق", "بلا مقطع", "synonym"),
            ["بِدُون", "مقطع", "بلا"],
        )
        self.assertEqual(self.marked("بلا بدون دون بلامثال", "بدون", "words"), ["بدون"])
        self.assertEqual(self.marked("بلا بدون دون بلامثال", "بدون", "synonym"), ["بلا", "بدون"])

    def test_regex_metacharacters_are_literal_and_overlapping_spans_merge(self):
        self.assertEqual(self.marked("100%_ [x] .*", "100%_ [x] .*"), ["100%_", "[x]", ".*"])
        self.assertEqual(self.marked("abcabc", "abc bc"), ["abcabc"])

    def test_unmatched_empty_and_mark_only_queries_keep_every_character(self):
        for text in ("", "\n\r\n إِحَالَةٌ\t <script> e\u0301  ", "َـ"):
            for query in ("", "َـ", "not-present"):
                self.assertEqual(self.marked(text, query), [])

    def test_unsafe_normalization_alignment_falls_back_without_guessing(self):
        # NFKC composes these two Hangul Jamo across the mapped cluster boundary.
        original = "\u1100\u1161 عنوان"
        result = highlight(original, "가", "words")
        self.assertEqual(result.count, 0)
        self.assertTrue(result.limited)
        self.assertEqual("".join(segment.text for segment in result.segments), original)

    def test_bounded_highlights_do_not_truncate_source_text(self):
        text = "مثال " * (MAX_MATCHES + 2)
        result = highlight(text, "مثال", "words")
        self.assertEqual(result.count, MAX_MATCHES)
        self.assertTrue(result.limited)
        self.assertEqual("".join(segment.text for segment in result.segments), text)
        long = "x" * (MAX_TEXT_LENGTH + 1)
        result = highlight(long, "x", "words")
        self.assertEqual(result.count, 0)
        self.assertTrue(result.limited)
        self.assertEqual(result.segments[0].text, long)
        self.assertEqual(self.marked("x", "x", "unknown"), [])

    def test_multiple_query_terms_are_marked_in_source_order(self):
        text = "الأول " + "الثاني " * (MAX_MATCHES + 1)
        result = highlight(text, "الثاني الاول", "words")
        self.assertEqual(next(part.text for part in result.segments if part.matched), "الأول")
        self.assertTrue(result.limited)


class HighlightMarkup(HTMLParser):
    def __init__(self, content):
        super().__init__(convert_charrefs=True)
        self.ids, self.links, self.marked, self.code_texts = [], [], [], []
        self.in_mark, self.in_code = False, False
        self.feed(content)

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if "id" in attrs:
            self.ids.append(attrs["id"])
        if tag == "a":
            self.links.append(attrs.get("href", ""))
        if tag == "code":
            self.in_code = True
            self.code_texts.append("")
        if tag == "mark":
            self.in_mark = True
            self.marked.append("")

    def handle_data(self, data):
        if self.in_mark:
            self.marked[-1] += data
        if self.in_code:
            self.code_texts[-1] += data

    def handle_endtag(self, tag):
        if tag == "mark":
            self.in_mark = False
        if tag == "code":
            self.in_code = False


@override_settings(ALLOWED_HOSTS=["localhost"])
class HighlightViewTests(SimpleTestCase):
    def get(self, data):
        return self.client.get(
            "/dev/editorial-search", data, HTTP_HOST="localhost", REMOTE_ADDR="127.0.0.1"
        )

    def test_original_arabic_and_html_are_preserved_and_escaped_inside_marks(self):
        catalog = build_queue_catalog()
        row = catalog.rows[0]
        original = '\n إِجَابَةٌ عَـلَى\r\n<script>alert("x")</script> e\u0301 '
        catalog = replace(catalog, rows=(replace(row, case=replace(row.case, question=original)),))
        with patch("apps.editorial_search.views.build_queue_catalog", return_value=catalog):
            response = self.get({"q": "اجابة علي <script>", "source": "question"})
        self.assertEqual(response.status_code, 200)
        markup = HighlightMarkup(response.content.decode())
        self.assertEqual(markup.code_texts, [original])
        self.assertEqual(markup.marked, ["إِجَابَةٌ", "عَـلَى", "<script>"])
        self.assertContains(response, "&#13;")
        self.assertNotContains(response, "<script>")
        self.assertContains(response, "<mark>&lt;script&gt;</mark>")

    def test_matched_field_links_have_unique_real_targets(self):
        response = self.get(
            {"q": "SYN", "source": "reference", "case_key": "history", "revision": 9}
        )
        markup = HighlightMarkup(response.content.decode())
        self.assertEqual(len(markup.ids), len(set(markup.ids)))
        targets = [link[1:] for link in markup.links if link.startswith("#result-")]
        self.assertTrue(targets)
        self.assertTrue(all(target in markup.ids for target in targets))
        for row in response.context["rows"]:
            self.assertTrue(row["matched_fields"])
            self.assertTrue(all(field["matches"] > 0 for field in row["matched_fields"]))
        self.assertContains(response, 'aria-label="الحقول المطابقة في النتيجة 1"')

    def test_presentation_keeps_hit_ranking_text_identities_and_links(self):
        catalog = build_queue_catalog()
        params = {"q": "بدون مقطع", "source": "question"}
        expected = search_catalog(catalog, **params)
        response = self.get(params)
        self.assertEqual(response.context["result"], expected)
        self.assertEqual(response.context["rows"][0]["hit"], expected.hits[0])
        markup = HighlightMarkup(response.content.decode())
        self.assertIn("بلا", markup.marked)
        self.assertIn("مقطع", markup.marked)
        self.assertEqual(markup.code_texts[0], expected.hits[0].fields[0].text)
        self.assertContains(response, "تطابق بتكافؤ بلا وبدون")
        self.assertIn(response.context["rows"][0]["url"], markup.links)

    def test_long_field_has_explicit_limit_and_preserves_full_source(self):
        catalog = build_queue_catalog()
        row = catalog.rows[0]
        original = "مثال " * (MAX_TEXT_LENGTH // 5 + 1)
        catalog = replace(catalog, rows=(replace(row, case=replace(row.case, question=original)),))
        with patch("apps.editorial_search.views.build_queue_catalog", return_value=catalog):
            response = self.get({"q": "مثال", "source": "question"})
        self.assertContains(response, "تمييز محدود في هذا الحقل")
        self.assertEqual(HighlightMarkup(response.content.decode()).code_texts, [original])
        self.assertEqual(response.context["rows"][0]["matched_fields"], ())
