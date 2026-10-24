"""SSR accessibility contracts; no claim of browser or screen-reader execution."""

from dataclasses import replace
from html.parser import HTMLParser

from django.template.loader import render_to_string
from django.test import SimpleTestCase

from apps.editorial_demo.revision_comparison import ReferenceComparison, TextPart
from apps.editorial_demo.revision_fixtures import COMPARISON_RECORD


class Element:
    def __init__(self, tag, attrs=()):
        self.tag = tag
        self.attrs = dict(attrs)
        self.children = []

    @property
    def text(self):
        return "".join(child.text if isinstance(child, Element) else child
                       for child in self.children)

    def find(self, tag=None, **attrs):
        found = []
        for child in self.children:
            if not isinstance(child, Element):
                continue
            if (tag is None or child.tag == tag) and all(
                child.attrs.get(key) == value for key, value in attrs.items()
            ):
                found.append(child)
            found.extend(child.find(tag, **attrs))
        return found


class RenderedPage(HTMLParser):
    def __init__(self, html):
        super().__init__()
        self.root = Element("document")
        self.stack = [self.root]
        self.feed(html)

    def handle_starttag(self, tag, attrs):
        element = Element(tag, attrs)
        self.stack[-1].children.append(element)
        if tag not in {"meta", "link", "br", "hr", "input"}:
            self.stack.append(element)

    def handle_endtag(self, tag):
        if self.stack[-1].tag == tag:
            self.stack.pop()

    def handle_data(self, data):
        self.stack[-1].children.append(data)


class ComparisonAccessibilityTests(SimpleTestCase):
    url = "/dev/editorial-preview/revision-compare"

    def page(self, before="1", after="2"):
        response = self.client.get(self.url, {"before": before, "after": after},
                                   HTTP_HOST="localhost")
        self.assertEqual(response.status_code, 200)
        return RenderedPage(response.content.decode()).root

    def test_submit_lands_at_named_focusable_results_with_current_direction(self):
        page = self.page()
        form, = page.find("form")
        self.assertEqual(form.attrs["method"], "get")
        self.assertEqual(form.attrs["action"], self.url)
        submit, = form.find("button", type="submit")
        self.assertEqual(submit.attrs.get("formaction", form.attrs["action"]),
                         self.url + "#comparison-result")
        result, = page.find("section", id="comparison-result")
        self.assertEqual(result.attrs.get("tabindex"), "-1")
        heading, = page.find(id=result.attrs["aria-labelledby"])
        self.assertIn("1", heading.text)
        self.assertIn("2", heading.text)
        descriptions = [page.find(id=ident)[0].text
                        for ident in result.attrs["aria-describedby"].split()]
        self.assertTrue(any("من المراجعة 1 إلى المراجعة 2" in text for text in descriptions))
        self.assertTrue(any("مجموعات الفروق" in text for text in descriptions))

    def test_native_selects_have_help_and_require_explicit_submit(self):
        page = self.page()
        for control in page.find("select"):
            label, = page.find("label", **{"for": control.attrs["id"]})
            self.assertTrue(label.text.strip())
            self.assertIn("aria-describedby", control.attrs)
            help_text = " ".join(page.find(id=ident)[0].text
                                 for ident in control.attrs["aria-describedby"].split())
            for instruction in ("Tab", "الأسهم", "عرض المقارنة", "نفسها", "عكس"):
                self.assertIn(instruction, help_text)
            self.assertNotIn("onchange", control.attrs)
        button, = page.find("button", type="submit")
        self.assertEqual(button.text, "عرض المقارنة")

    def test_result_context_explains_reverse_and_same_revision_selection(self):
        for before, after, explanation in (
            ("2", "1", "بعكس ترتيب المراجعات"),
            ("1", "1", "المراجعة نفسها"),
            ("2", "2", "المراجعة نفسها"),
        ):
            with self.subTest(before=before, after=after):
                page = self.page(before, after)
                self.assertEqual(len(page.find(id="comparison-result")), 1)
                result, = page.find(id="comparison-result")
                descriptions = " ".join(page.find(id=ident)[0].text for ident in
                                        result.attrs["aria-describedby"].split())
                self.assertIn(explanation, descriptions)
                if before == after:
                    self.assertIn("لا توجد فروق", descriptions)
                else:
                    self.assertIn("من المراجعة 2 إلى المراجعة 1", descriptions)

    def test_repeated_partial_groups_preserve_text_without_replacing_change_content(self):
        pieces = (TextPart("unchanged", "أ  \t\r\n"),
                  TextPart("removed", '<del title="x">محذوف</del>'),
                  TextPart("added", "أ جديد"))
        context_label = 'نص "محدد" <script>label</script>'
        html = render_to_string("editorial_demo/_revision_text.html",
                                {"pieces": pieces, "text_context": context_label})
        page = RenderedPage(html + html).root
        self.assertFalse(any("id" in node.attrs for node in page.find()))
        for pre in page.find("pre"):
            self.assertEqual(pre.text, 'أ  \t\r\n<del title="x">محذوف</del>أ جديد')
            self.assertEqual(pre.attrs["dir"], "auto")
            self.assertIn("aria-label", pre.attrs)
            self.assertEqual(pre.attrs["aria-label"], context_label)
            for tag, label in (("del", "محذوف"), ("ins", "مضاف")):
                marker, = pre.find(tag)
                self.assertNotIn("aria-label", marker.attrs)
                groups = pre.find(role="group")
                self.assertTrue(any(label in group.attrs.get("aria-label", "")
                                    and marker in group.find(tag) for group in groups))
        self.assertIn("&lt;del", html)
        self.assertFalse(page.find("script"))

    def test_whitespace_and_empty_text_remain_readable_inside_named_groups(self):
        for pieces, expected in (((), "نص فارغ"),
                                 ((TextPart("removed", " \t\r\n"),), "·⇥␍␊\n")):
            with self.subTest(pieces=pieces):
                html = render_to_string("editorial_demo/_revision_text.html",
                                        {"pieces": pieces, "show_whitespace": True})
                pre, = RenderedPage(html).root.find("pre")
                self.assertEqual(pre.text, expected)
                self.assertEqual(pre.attrs.get("role"), "group")
                self.assertIn("المسافات", pre.attrs["aria-label"])

    def test_reference_groups_keep_identity_order_positions_and_escaped_values(self):
        reference = COMPARISON_RECORD.history[0].reference_links[0]
        attack = '<script title="هوية">x</script>'
        entries = (ReferenceComparison(replace(reference, source_id=attack), "unchanged", 1, 2),
                   ReferenceComparison(reference, "removed", 2, None))
        html = render_to_string("editorial_demo/_revision_references.html",
                                {"entries": entries, "reference_context": attack})
        page = RenderedPage(html + html).root
        self.assertFalse(any("id" in node.attrs for node in page.find()))
        for listing in page.find("ol"):
            self.assertEqual(listing.attrs.get("aria-label"), attack)
            groups = listing.find(role="group")
            self.assertEqual(len(groups), 2)
            for index, group in enumerate(groups, 1):
                self.assertIn(str(index), group.attrs["aria-label"])
                self.assertEqual(len(group.find("dt")), 6)
                self.assertEqual(len(group.find("dd")), 6)
            self.assertEqual([node.text for node in groups[0].find("bdi")], [
                "synthetic-revision-demo", "SYN-BOOK", "SYN-EDITION",
                reference.source_archive_sha256, reference.source_input_sha256, attack,
            ])
            self.assertIn("الموضع في النسخة المقابلة 2", groups[0].text)
            self.assertIn("محذوف", groups[1].text)
        self.assertFalse(page.find("script"))
        empty = RenderedPage(render_to_string(
            "editorial_demo/_revision_references.html", {"entries": ()})).root
        listing, = empty.find("ol")
        self.assertTrue(listing.attrs.get("aria-label"))
        self.assertIn("لا توجد مراجع", listing.text)

    def test_shared_partials_add_no_duplicate_ids_or_broken_local_references(self):
        for url, query in ((self.url, {}), ("/dev/editorial-preview/revision-history",
                                           {"before": "1", "after": "2"})):
            with self.subTest(url=url):
                response = self.client.get(url, query, HTTP_HOST="localhost")
                self.assertEqual(response.status_code, 200)
                page = RenderedPage(response.content.decode()).root
                ids = [node.attrs["id"] for node in page.find() if "id" in node.attrs]
                self.assertEqual(len(ids), len(set(ids)))
                for node in page.find():
                    for attr in ("aria-labelledby", "aria-describedby"):
                        for ident in node.attrs.get(attr, "").split():
                            self.assertIn(ident, ids)
                self.assertTrue(page.find("ins"))
                self.assertTrue(page.find("del"))
