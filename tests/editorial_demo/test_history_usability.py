"""Focused Arabic history context and accessible timeline contracts."""

from django.test import SimpleTestCase

from tests.editorial_demo.test_revision_compare import PageStructure


class HistoryUsabilityTests(SimpleTestCase):
    url = "/dev/editorial-preview/revision-history"

    def page(self, query=None):
        response = self.client.get(self.url, data=query or {}, HTTP_HOST="localhost")
        self.assertEqual(response.status_code, 200)
        structure = PageStructure(response.content.decode())
        elements = {attrs["id"]: (tag, attrs) for tag, attrs in structure.elements
                    if "id" in attrs}
        return response, elements

    def test_initial_choices_are_explicitly_proposed_not_a_displayed_comparison(self):
        response, elements = self.page()
        self.assertContains(response, "لم تُعرض مقارنة بعد. الاختيار المبدئي: المراجعة 1 ثم المراجعة 11.")
        self.assertEqual(elements["selection"][1].get("aria-describedby"), "selection-state")
        self.assertNotContains(response, "المقارنة المعروضة: المراجعة")

    def test_applied_selection_context_preserves_reverse_identity_order(self):
        response, elements = self.page({"before": "11", "after": "4"})
        self.assertContains(response, "المقارنة المعروضة: المراجعة 11 ثم المراجعة 4.")
        self.assertEqual(elements["selection"][1].get("aria-describedby"), "selection-state")
        self.assertNotContains(response, "الاختيار المبدئي:")

    def test_same_revision_help_is_specific_to_a_single_snapshot(self):
        message = "اختيار المراجعة نفسها يعرض لقطة واحدة في الطرفين؛ اختر مراجعة أخرى لفحص التغييرات عبر السجل."
        response, _ = self.page({"before": "7", "after": "7"})
        self.assertTrue(message in response.text)
        response, _ = self.page({"before": "9", "after": "11"})
        self.assertNotContains(response, message)
        self.assertContains(response, "لا يتغير محتوى المقارنة")

    def test_history_region_and_each_article_have_resolvable_names(self):
        _, elements = self.page({"before": "11", "after": "4"})
        self.assertIn("history", elements)
        self.assertEqual(elements["history"][0], "section")
        self.assertEqual(elements["history"][1].get("tabindex"), "-1")
        self.assertEqual(elements["history"][1].get("aria-labelledby"), "history-heading")
        self.assertEqual(elements["history-list"][1].get("aria-labelledby"), "history-heading")
        self.assertEqual(elements["history-jump"][1].get("href"), "#history")
        for number in (1, 2, 4, 7, 9, 11):
            with self.subTest(number=number):
                article = elements[f"history-entry-{number}"]
                heading_id = article[1].get("aria-labelledby")
                self.assertEqual(article[0], "article")
                self.assertEqual(heading_id, f"history-title-{number}")
                self.assertEqual(elements[heading_id][0], "h3")

    def test_selected_article_descriptions_identify_both_roles_for_same_revision(self):
        for query, expected in (
            ({"before": "11", "after": "4"},
             {11: "selected-before-11", 4: "selected-after-4"}),
            ({"before": "7", "after": "7"},
             {7: "selected-before-7 selected-after-7"}),
        ):
            _, elements = self.page(query)
            for number in (1, 2, 4, 7, 9, 11):
                with self.subTest(query=query, number=number):
                    self.assertIn(f"history-entry-{number}", elements)
                    describedby = elements[f"history-entry-{number}"][1].get("aria-describedby")
                    self.assertEqual(describedby, expected.get(number))
                    for target in (describedby or "").split():
                        self.assertIn(target, elements)
