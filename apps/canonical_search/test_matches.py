"""Exact original character spans and current-source navigation, without source edits."""

from dataclasses import replace
from unittest.mock import patch

from django.test import SimpleTestCase, TransactionTestCase, override_settings

from apps.casework import services as cases
from apps.casework.models import AnswerRevision, CaseEvent, CaseSource
from apps.mufti_review.identity import IdentityUnavailable

from . import matches
from .test_support import FEATURES, SearchFixture


class MatchProjectionTests(SimpleTestCase):
    def test_arabic_diacritics_tatweel_and_crlf_preserve_original_ranges(self):
        original = "  زَكَاةٌ\r\nثم زكـاة ثم زكاة  "
        result = matches.project(original, value="زكاة", mode="FTS")
        self.assertEqual([row["text"] for row in result["matches"]], ["زَكَاةٌ", "زكـاة", "زكاة"])
        self.assertEqual("".join(part["text"] for part in result["parts"]), original)
        for row in result["matches"]:
            self.assertEqual(original[row["start"] : row["end"]], row["text"])
        self.assertEqual(result["active"]["text"], "زَكَاةٌ")
        self.assertEqual(
            matches.project(original, value="زكاة", mode="FTS", index=2)["active"]["text"], "زكاة"
        )

    def test_literal_mode_does_not_rewrite_diacritics_or_case(self):
        original = "زَكَاة زكاة زكاة <script>alert(1)</script>"
        result = matches.project(original, value="زكاة", mode="LITERAL")
        self.assertEqual(len(result["matches"]), 2)
        self.assertEqual(result["matches"][0]["start"], original.index("زكاة"))
        self.assertEqual("".join(part["text"] for part in result["parts"]), original)

    def test_compatibility_expansion_and_casefold_map_back_to_original_characters(self):
        original = "ß ﬃ ﷲ أ\u0654مانة"
        for value, expected in (("ss", "ß"), ("ffi", "ﬃ"), ("الله", "ﷲ"), ("امانة", "أ\u0654مانة")):
            with self.subTest(value=value):
                result = matches.project(original, value=value, mode="FTS")
                self.assertEqual([row["text"] for row in result["matches"]], [expected])
                self.assertEqual("".join(part["text"] for part in result["parts"]), original)

    def test_terms_are_whole_tokens_and_multiple_terms_keep_source_order(self):
        original = "كتاب زكاة والكتاب زكاة كتاب"
        result = matches.project(original, value="زكاة كتاب", mode="FTS")
        self.assertEqual(
            [row["text"] for row in result["matches"]], ["كتاب", "زكاة", "زكاة", "كتاب"]
        )
        self.assertNotIn("والكتاب", [row["text"] for row in result["matches"]])

    def test_fuzzy_only_result_never_fabricates_literal_spans(self):
        result = matches.project("المُعاملات المالية", value="المعاملاتت", mode="FUZZY")
        self.assertEqual(result["matches"], [])
        self.assertEqual(result["state"], "APPROXIMATE_WITHOUT_EXACT_SPAN")
        self.assertIsNone(result["active"])

    def test_bounds_and_noninteger_positions_are_rejected_and_truncation_is_explicit(self):
        result = matches.project("a " * 250, value="a", mode="LITERAL")
        self.assertEqual(len(result["matches"]), matches.MAX_MATCHES)
        self.assertTrue(result["limited"])
        self.assertEqual("".join(part["text"] for part in result["parts"]), "a " * 250)
        for index in (-1, True, "0", 200):
            with self.subTest(index=index), self.assertRaises(cases.CaseConflict):
                matches.project("a " * 250, value="a", mode="LITERAL", index=index)
        for value in ("x" * 121, "\n", "...", "a b c d e f g h i"):
            with self.subTest(value=value), self.assertRaises(cases.CaseConflict):
                matches.project("text", value=value, mode="FTS")


@override_settings(**FEATURES)
class SearchMatchServiceTests(SearchFixture, TransactionTestCase):
    def selected(self, *, kind="QUESTION", value="المعاملات"):
        self.build()
        return self.search(value, kind=kind)["results"][0]

    def open_match(self, selected, **changes):
        return matches.open_match(
            **self.common,
            generation_id=selected["generation_id"],
            document_id=selected["document_id"],
            value=changes.pop("value", "المعاملات"),
            mode=changes.pop("mode", "FTS"),
            **changes,
        )

    def test_question_and_current_answer_open_exact_spans_without_any_canonical_write(self):
        self.answer("المُعاملات ثم المعاملات؛ جواب محفوظ\r\nبنصه الأصلي")
        selected = self.selected()
        before = CaseEvent.objects.count()
        question = self.open_match(selected)
        self.assertEqual(question["text"], self.question)
        self.assertEqual(question["navigation"]["active"]["text"], "المُعاملاتِ")
        answer = self.search("المعاملات", kind="ANSWER")["results"][0]
        first = self.open_match(answer)
        second = self.open_match(answer, index=1)
        self.assertEqual(first["text"], second["text"])
        self.assertEqual(second["navigation"]["active"]["text"], "المعاملات")
        self.assertEqual(
            self.open_match(answer)["navigation"]["active"], first["navigation"]["active"]
        )
        self.assertEqual(CaseEvent.objects.count(), before)
        self.assertEqual(
            CaseSource.objects.get(case_id=self.common["case_id"]).original_question, self.question
        )
        self.assertEqual(AnswerRevision.objects.latest("revision").text, first["text"])

    def test_document_must_still_match_the_signed_query_and_mode(self):
        selected = self.selected()
        for value, mode in (("غيرموجود", "FTS"), ("المعاملات", "LITERAL")):
            with (
                self.subTest(mode=mode),
                self.assertRaisesMessage(cases.CaseConflict, "search_match_not_current"),
            ):
                self.open_match(selected, value=value, mode=mode)

    def test_stale_generation_and_current_open_or_search_revocation_fail_closed(self):
        selected = self.selected()
        for action in ("OPEN", "SEARCH"):
            self.authority.denied.add(action)
            with self.assertRaises(cases.CaseConflict):
                self.open_match(selected)
            self.authority.denied.remove(action)
        self.answer("جواب جديد يجعل الفهرس القديم غير صالح")
        with self.assertRaisesMessage(cases.CaseConflict, "search_result_stale_or_unavailable"):
            self.open_match(selected)

    def test_late_source_or_permission_change_cannot_return_derived_spans(self):
        selected = self.selected()
        original = matches.project

        def revoke(*args, **kwargs):
            result = original(*args, **kwargs)
            self.authority.denied.add("SEARCH")
            return result

        with (
            patch.object(matches, "project", side_effect=revoke),
            self.assertRaises(cases.CaseConflict),
        ):
            self.open_match(selected)
        self.authority.denied.clear()
        actor = self.directory.identities["editor"]
        self.directory.identities["editor"] = replace(actor, active=False)
        with self.assertRaises((IdentityUnavailable, cases.CaseConflict)):
            self.open_match(selected)
