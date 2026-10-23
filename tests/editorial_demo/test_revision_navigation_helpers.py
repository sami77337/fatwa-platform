"""Ordered comparison navigation, including its real read-only template consumer."""

import re
from dataclasses import FrozenInstanceError, asdict

from django.template.loader import render_to_string
from django.test import SimpleTestCase

from apps.editorial_demo.revision_comparison import ChangeTarget, compare_revisions
from apps.editorial_demo.revision_fixtures import COMPARISON_RECORD, REVISION_HISTORY_RECORD
from tests.editorial_demo.test_revision_compare import PageStructure


class DifferenceNavigationHelperTests(SimpleTestCase):
    def build(self, targets):
        from apps.editorial_demo.revision_navigation import difference_sequence

        return difference_sequence(targets)

    def test_empty_and_single_groups_have_no_invented_neighbours(self):
        self.assertEqual(self.build(()), ())
        target = ChangeTarget("change-references", "المراجع")
        (step,) = self.build((target,))
        self.assertIs(step.current, target)
        self.assertIsNone(step.previous)
        self.assertIsNone(step.following)

    def test_sparse_sequence_preserves_authoritative_order_and_boundaries(self):
        targets = (ChangeTarget("change-reviewer_notes", "ملاحظات"),
                   ChangeTarget("change-references", "مراجع"))
        snapshot = tuple(asdict(target) for target in targets)
        steps = self.build(targets)
        self.assertIsNone(steps[0].previous)
        self.assertIs(steps[0].following, targets[1])
        self.assertIs(steps[1].previous, targets[0])
        self.assertIsNone(steps[1].following)
        self.assertEqual(tuple(asdict(target) for target in targets), snapshot)
        with self.assertRaises(FrozenInstanceError):
            steps[0].following = targets[0]

    def test_reversed_target_order_is_not_sorted_or_reconstructed(self):
        targets = (ChangeTarget("change-references", "مراجع"),
                   ChangeTarget("change-title", "عنوان"),
                   ChangeTarget("change-answer", "نص"))
        steps = self.build(targets)
        self.assertEqual([step.current.anchor for step in steps],
                         ["change-references", "change-title", "change-answer"])
        self.assertEqual((steps[1].previous.anchor, steps[1].following.anchor),
                         ("change-references", "change-answer"))

    def test_unsafe_unknown_and_duplicate_anchors_fail_closed(self):
        for anchor in ('change-title" onclick="alert(1)', "#change-title", "change-missing",
                       "javascript:alert(1)", "change-title\n"):
            with self.subTest(anchor=anchor), self.assertRaises(ValueError):
                self.build((ChangeTarget(anchor, "عنوان"),))
        target = ChangeTarget("change-title", "عنوان")
        with self.assertRaises(ValueError):
            self.build((target, target))


class DifferenceNavigationTemplateTests(SimpleTestCase):
    pattern = r'<nav id="difference-nav-([^" ]+)"[^>]*>(.*?)</nav>'

    def render_comparison(self, before, after):
        from apps.editorial_demo.revision_navigation import difference_sequence

        revisions = {revision.number: revision for revision in REVISION_HISTORY_RECORD.history}
        comparison = compare_revisions(revisions[before], revisions[after])
        html = render_to_string("editorial_demo/_revision_comparison_content.html", {
            "comparison": comparison, "before_revision": revisions[before],
            "after_revision": revisions[after], "source": REVISION_HISTORY_RECORD.intake,
            "difference_navigation": difference_sequence(comparison.targets),
        })
        return comparison, html

    def test_existing_comparison_page_wires_native_controls_to_real_focus_targets(self):
        snapshot = asdict(COMPARISON_RECORD)
        response = self.client.get("/dev/editorial-preview/revision-compare",
                                   HTTP_HOST="localhost")
        self.assertEqual(response.status_code, 200)
        html = response.content.decode()
        navs = dict(re.findall(self.pattern, html, re.S))
        self.assertEqual(list(navs), ["change-title", "change-answer", "change-reviewer_notes",
                                      "change-references"])
        elements = PageStructure(html).elements
        ids = [attrs["id"] for _, attrs in elements if "id" in attrs]
        self.assertEqual(len(ids), len(set(ids)))
        destinations = {attrs["id"]: attrs for _, attrs in elements if "id" in attrs}
        for markup in navs.values():
            for tag, attrs in PageStructure(markup).elements:
                if tag == "a":
                    self.assertEqual(destinations[attrs["href"][1:]].get("tabindex"), "-1")
                    self.assertNotIn("tabindex", attrs)
                    self.assertNotIn("onclick", attrs)
        self.assertIn('<html lang="ar" dir="rtl">', html)
        self.assertFalse(any(tag == "script" for tag, _ in elements))
        self.assertEqual(asdict(COMPARISON_RECORD), snapshot)

    def test_sparse_and_reverse_comparisons_skip_unchanged_groups(self):
        snapshot = asdict(REVISION_HISTORY_RECORD)
        for before, after in ((7, 9), (9, 7)):
            with self.subTest(before=before, after=after):
                _, html = self.render_comparison(before, after)
                navs = dict(re.findall(self.pattern, html, re.S))
                self.assertEqual(list(navs), ["change-reviewer_notes", "change-references"])
                links = [[(attrs["rel"], attrs["href"])
                          for tag, attrs in PageStructure(markup).elements if tag == "a"]
                         for markup in navs.values()]
                self.assertEqual(links, [[("next", "#change-references")],
                                         [("prev", "#change-reviewer_notes")]])
                self.assertIn("لا يوجد فرق سابق", navs["change-reviewer_notes"])
                self.assertIn("لا يوجد فرق تالٍ", navs["change-references"])
        self.assertEqual(asdict(REVISION_HISTORY_RECORD), snapshot)

    def test_single_group_has_boundary_text_without_dead_links(self):
        _, html = self.render_comparison(4, 7)
        navs = dict(re.findall(self.pattern, html, re.S))
        self.assertEqual(list(navs), ["change-references"])
        self.assertFalse(any(tag == "a" for tag, _ in
                             PageStructure(navs["change-references"]).elements))
        self.assertIn("لا يوجد فرق سابق", navs["change-references"])
        self.assertIn("لا يوجد فرق تالٍ", navs["change-references"])

    def test_equal_identity_and_equal_distinct_snapshots_have_no_group_controls(self):
        for before, after in ((4, 4), (9, 11)):
            with self.subTest(before=before, after=after):
                _, html = self.render_comparison(before, after)
                self.assertEqual(re.findall(self.pattern, html, re.S), [])

    def test_navigation_labels_are_escaped_in_the_shared_control_partial(self):
        from apps.editorial_demo.revision_navigation import difference_sequence

        targets = (ChangeTarget("change-title", '<script>alert("label")</script>'),
                   ChangeTarget("change-references", "المراجع"))
        html = render_to_string("editorial_demo/_difference_navigation.html",
                                {"difference": difference_sequence(targets)[1]})
        self.assertNotIn("<script>", html)
        self.assertIn("&lt;script&gt;", html)
        self.assertIn('href="#change-title"', html)

    def test_navigation_leaves_every_rendered_comparison_character_unchanged(self):
        from apps.editorial_demo.revision_navigation import difference_sequence

        before, after = COMPARISON_RECORD.history
        comparison = compare_revisions(before, after)
        context = {"comparison": comparison, "before_revision": before,
                   "after_revision": after, "source": COMPARISON_RECORD.intake}
        template = "editorial_demo/_revision_comparison_content.html"
        original = render_to_string(template, context)
        with_navigation = render_to_string(template, {
            **context, "difference_navigation": difference_sequence(comparison.targets),
        })
        self.assertEqual(re.sub(self.pattern, "", with_navigation, flags=re.S), original)
