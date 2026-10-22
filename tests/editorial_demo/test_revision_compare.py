"""Synthetic comparison contracts; no database, network, or accepted asset suites."""

import os
from dataclasses import asdict, replace
from html.parser import HTMLParser
from unittest.mock import patch

from django.test import RequestFactory, SimpleTestCase, override_settings
from django.urls import resolve

from apps.fatwa_drafts.domain import DraftRecord, Revision
from apps.fatwa_drafts.intake import ReferenceLink, serialize_intake


class ComparisonTests(SimpleTestCase):
    def setUp(self):
        from apps.editorial_demo.revision_comparison import compare_revisions
        from apps.editorial_demo.revision_fixtures import COMPARISON_RECORD

        self.compare = compare_revisions
        self.record = COMPARISON_RECORD
        self.before, self.after = self.record.history

    def field(self, result, key):
        return next(field for field in result.fields if field.key == key)

    def test_exact_character_changes_and_reconstruction(self):
        before = replace(self.before, title="أ", answer="س  \t\r\n ", reviewer_notes="س")
        after = replace(self.after, title="أب", answer="س \t\r\n ", reviewer_notes="ص")
        result = self.compare(before, after)
        title = self.field(result, "title")
        self.assertEqual([(p.kind, p.text) for p in title.before], [("unchanged", "أ")])
        self.assertEqual([(p.kind, p.text) for p in title.after],
                         [("unchanged", "أ"), ("added", "ب")])
        answer = self.field(result, "answer")
        self.assertEqual("".join(p.text for p in answer.before if p.kind == "removed"), " ")
        notes = self.field(result, "reviewer_notes")
        self.assertEqual([(p.kind, p.text) for p in notes.before], [("removed", "س")])
        self.assertEqual([(p.kind, p.text) for p in notes.after], [("added", "ص")])
        for field in result.fields:
            self.assertEqual("".join(p.text for p in field.before), getattr(before, field.key))
            self.assertEqual("".join(p.text for p in field.after), getattr(after, field.key))

    def test_unicode_is_not_normalized(self):
        result = self.compare(replace(self.before, title="أ"), replace(self.after, title="أ"))
        title = self.field(result, "title")
        self.assertTrue(title.changed)
        self.assertEqual("".join(p.text for p in title.before), "\u0623")
        self.assertEqual("".join(p.text for p in title.after), "\u0627\u0654")

    def test_unchanged_revision_has_no_change_targets(self):
        result = self.compare(self.before, self.before)
        self.assertFalse(result.changed)
        self.assertEqual(result.targets, ())
        self.assertTrue(all(not field.changed for field in result.fields))
        self.assertTrue(all(ref.kind == "unchanged" for ref in result.before_references))

    def test_added_removed_references_preserve_order_and_objects(self):
        result = self.compare(self.before, self.after)
        self.assertEqual([r.kind for r in result.before_references], ["unchanged", "removed"])
        self.assertEqual([r.kind for r in result.after_references], ["unchanged", "added"])
        self.assertEqual([r.reference.source_id for r in result.before_references],
                         ["SYN-KEEP", "SYN-REMOVE"])
        self.assertEqual([r.reference.source_id for r in result.after_references],
                         ["SYN-KEEP", "SYN-ADD"])
        self.assertIs(result.before_references[0].reference, self.before.reference_links[0])
        self.assertIs(result.after_references[1].reference, self.after.reference_links[1])

    def test_every_reference_identity_field_is_compared(self):
        reference = self.before.reference_links[0]
        for name in ReferenceLink.__dataclass_fields__:
            value = "f" * 64 if name.endswith("sha256") else "DIFFERENT-SYNTHETIC"
            with self.subTest(field=name):
                changed = replace(reference, **{name: value})
                result = self.compare(replace(self.before, reference_links=(reference,)),
                                      replace(self.before, reference_links=(changed,)))
                self.assertEqual(result.before_references[0].kind, "removed")
                self.assertEqual(result.after_references[0].kind, "added")
                self.assertTrue(result.references_changed)

    def test_reference_reordering_is_visible_without_sorting(self):
        result = self.compare(self.before,
                              replace(self.before, reference_links=self.before.reference_links[::-1]))
        self.assertTrue(result.references_changed)
        self.assertEqual([r.kind for r in result.after_references], ["unchanged", "unchanged"])
        self.assertEqual([(r.position, r.other_position) for r in result.before_references],
                         [(1, 2), (2, 1)])
        self.assertEqual([r.reference for r in result.after_references],
                         list(self.before.reference_links[::-1]))

    def test_original_source_and_revision_snapshots_are_preserved(self):
        original = asdict(self.record)
        source_bytes = serialize_intake((self.record.intake,))
        result = self.compare(self.before, self.after)
        self.assertIsInstance(self.record, DraftRecord)
        self.assertIsInstance(self.before, Revision)
        self.assertEqual(asdict(self.record), original)
        self.assertEqual(serialize_intake((self.record.intake,)), source_bytes)
        self.assertEqual(result, self.compare(self.before, self.after))
        self.compare(self.after, self.before)
        self.assertEqual(asdict(self.record), original)

    def test_empty_text_and_reference_lists(self):
        before = replace(self.before, title="", answer="", reviewer_notes="", reference_links=())
        after = replace(before, title="س", reference_links=self.before.reference_links[:1])
        result = self.compare(before, after)
        self.assertEqual(self.field(result, "title").before, ())
        self.assertEqual(result.before_references, ())
        self.assertEqual(result.after_references[0].kind, "added")

    def test_invalid_comparison_inputs_are_rejected(self):
        from apps.editorial_demo.revision_comparison import MAX_TEXT_LENGTH

        for invalid in (None, {}, "1", replace(self.before, answer=None),
                        replace(self.before, title="\ud800"),
                        replace(self.before, reference_links=[])):
            with self.subTest(value=invalid), self.assertRaises((TypeError, ValueError)):
                self.compare(invalid, self.after)
        for invalid in (
            replace(self.before, answer="x" * (MAX_TEXT_LENGTH + 1)),
            replace(self.before, reference_links=(self.before.reference_links[0],) * 2),
            replace(self.before, reference_links=("not-a-reference",)),
        ):
            with self.subTest(value=invalid), self.assertRaises((TypeError, ValueError)):
                self.compare(self.before, invalid)


class PageStructure(HTMLParser):
    def __init__(self, html):
        super().__init__()
        self.elements = []
        self.feed(html)

    def handle_starttag(self, tag, attrs):
        self.elements.append((tag, dict(attrs)))


class RevisionCompareRouteTests(SimpleTestCase):
    url = "/dev/editorial-preview/revision-compare"
    css_url = "/dev/editorial-preview/revision-compare.css"

    def get(self, query=None, **kwargs):
        return self.client.get(self.url, data=query or {}, HTTP_HOST="localhost", **kwargs)

    def test_route_defaults_and_rtl(self):
        response = self.get()
        self.assertEqual(response.status_code, 200)
        self.assertEqual(resolve(self.url).url_name, "editorial_revision_compare")
        self.assertContains(response, '<html lang="ar" dir="rtl">')
        self.assertEqual(response.context["before_revision"].number, 1)
        self.assertEqual(response.context["after_revision"].number, 2)
        for label in ("مضاف", "محذوف", "دون تغيير", "النص الأصلي", "بيانات اصطناعية"):
            self.assertContains(response, label)
        self.assertEqual(response["Cache-Control"], "no-store")

    def test_same_and_reversed_fixed_revisions(self):
        for number in ("1", "2"):
            response = self.get({"before": number, "after": number})
            self.assertEqual(response.status_code, 200)
            self.assertFalse(response.context["comparison"].changed)
            self.assertContains(response, "لا توجد فروق")
        response = self.get({"before": "2", "after": "1"})
        self.assertTrue(response.context["comparison"].changed)
        self.assertEqual(response.context["before_revision"].number, 2)

    def test_reference_position_changes_are_rendered(self):
        from apps.editorial_demo.revision_fixtures import COMPARISON_RECORD

        before = COMPARISON_RECORD.history[0]
        after = replace(before, number=2, reference_links=before.reference_links[::-1])
        record = replace(COMPARISON_RECORD, history=(before, after))
        with patch("apps.editorial_demo.views.COMPARISON_RECORD", record):
            response = self.get()
        self.assertContains(response, "الموضع في النسخة المقابلة 2")
        self.assertContains(response, "الموضع في النسخة المقابلة 1")
        self.assertTrue(response.context["comparison"].references_changed)

    def test_get_and_head_for_page_and_stylesheet(self):
        for path, content_type in ((self.url, "text/html; charset=utf-8"),
                                   (self.css_url, "text/css; charset=utf-8")):
            response = self.client.get(path, HTTP_HOST="localhost")
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response["Content-Type"], content_type)
            head = self.client.head(path, HTTP_HOST="localhost")
            self.assertEqual(head.status_code, 200)
            self.assertEqual(head.content, b"")
            self.assertEqual(head["Cache-Control"], "no-store")

    def test_unsafe_methods_rejected_by_route_and_view(self):
        from apps.editorial_demo.views import revision_compare, revision_compare_stylesheet

        for path, view in ((self.url, revision_compare),
                           (self.css_url, revision_compare_stylesheet)):
            for method in ("post", "put", "patch", "delete", "options", "trace"):
                with self.subTest(path=path, method=method):
                    response = getattr(self.client, method)(path, HTTP_HOST="localhost")
                    self.assertEqual(response.status_code, 405)
                    self.assertEqual(response["Allow"], "GET, HEAD")
                    request = getattr(RequestFactory(), method)(path, HTTP_HOST="localhost")
                    self.assertEqual(view(request).status_code, 405)

    def test_invalid_or_unrecognized_inputs_are_not_reflected(self):
        for query in (
            {"before": "0"}, {"after": "3"}, {"before": "01"}, {"before": ""},
            {"after": "-1"}, {"before": "١"}, {"before": " 1"}, {"after": "1.0"},
            {"before": ["1", "2"]}, {"unknown": "1"}, {"answer": "<script>x</script>"},
            {"before": "1" * 1000},
        ):
            with self.subTest(query=query):
                response = self.get(query)
                self.assertEqual(response.status_code, 400)
                self.assertNotIn(b"<script>", response.content)
                self.assertEqual(response["Cache-Control"], "no-store")
        self.assertEqual(self.client.head(self.url + "?before=3", HTTP_HOST="localhost").status_code,
                         400)
        self.assertEqual(self.client.get(self.css_url + "?unknown=1", HTTP_HOST="localhost").status_code,
                         400)

    @override_settings(DATA_UPLOAD_MAX_NUMBER_FIELDS=2)
    def test_too_many_fields_fails_with_400(self):
        self.assertEqual(self.get({"a": "1", "b": "2", "c": "3"}).status_code, 400)

    @override_settings(ALLOWED_HOSTS=["*"])
    def test_local_host_and_peer_guard_applies_to_both_routes(self):
        for path in (self.url, self.css_url):
            for host in ("example.invalid", "localhost.example.invalid", "127.0.0.2"):
                self.assertEqual(self.client.get(path, HTTP_HOST=host).status_code, 404)
            for peer in ("192.0.2.1", "", "invalid"):
                self.assertEqual(self.client.get(path, HTTP_HOST="localhost", REMOTE_ADDR=peer,
                                                 HTTP_X_FORWARDED_FOR="127.0.0.1").status_code, 404)
            self.assertEqual(self.client.get(path, HTTP_HOST="[::1]:8000", REMOTE_ADDR="::1").status_code,
                             200)

    def test_all_existing_production_denials_are_preserved(self):
        for path in (self.url, self.css_url):
            with patch.dict(os.environ, {"FATWA_PRODUCTION": "1"}):
                self.assertEqual(self.client.get(path, HTTP_HOST="localhost").status_code, 404)
            with override_settings(FATWA_PRODUCTION=True):
                self.assertEqual(self.client.get(path, HTTP_HOST="localhost").status_code, 404)
            with override_settings(SETTINGS_MODULE="config.settings.production"):
                self.assertEqual(self.client.get(path, HTTP_HOST="localhost").status_code, 404)

    def test_xss_escaping_in_text_source_and_reference_fields(self):
        from apps.editorial_demo.revision_fixtures import COMPARISON_RECORD

        payload = '<script>alert("synthetic")</script>'
        ref = replace(COMPARISON_RECORD.history[0].reference_links[0], source_id=payload)
        revisions = tuple(replace(revision, title=payload, answer=payload, reviewer_notes=payload,
                                  reference_links=(ref,)) for revision in COMPARISON_RECORD.history)
        record = replace(COMPARISON_RECORD,
                         intake=replace(COMPARISON_RECORD.intake, question=payload, staff_notes=payload),
                         history=revisions)
        with patch("apps.editorial_demo.views.COMPARISON_RECORD", record):
            response = self.get()
        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, payload)
        self.assertContains(response, "&lt;script&gt;")
        structure = PageStructure(response.content.decode())
        self.assertFalse(any(tag in {"script", "iframe", "textarea"} for tag, _ in structure.elements))
        self.assertNotContains(response, '<a href="https://example.invalid')

    def test_change_navigation_targets_and_keyboard_landmarks(self):
        response = self.get()
        structure = PageStructure(response.content.decode())
        ids = {attrs["id"]: attrs for _, attrs in structure.elements if "id" in attrs}
        links = [attrs["href"] for tag, attrs in structure.elements
                 if tag == "a" and attrs.get("href", "").startswith("#")]
        self.assertIn("#main-content", links)
        for target in ("change-title", "change-answer", "change-reviewer_notes", "change-references"):
            self.assertIn("#" + target, links)
            self.assertEqual(ids[target].get("tabindex"), "-1")
        for link in links:
            self.assertIn(link[1:], ids)
        labels = {attrs.get("for") for tag, attrs in structure.elements if tag == "label"}
        self.assertTrue({"before", "after"} <= labels)
        self.assertTrue(any(tag == "ins" for tag, _ in structure.elements))
        self.assertTrue(any(tag == "del" for tag, _ in structure.elements))
        self.assertFalse(any(tag in {"input", "textarea", "script"} for tag, _ in structure.elements))

    def test_immutable_source_fields_are_displayed_verbatim(self):
        from apps.editorial_demo.revision_fixtures import COMPARISON_RECORD

        response = self.get()
        for value in (COMPARISON_RECORD.intake.external_id, COMPARISON_RECORD.intake.question,
                      COMPARISON_RECORD.intake.prepared_clip_url, COMPARISON_RECORD.intake.staff_notes):
            self.assertContains(response, value)
        self.assertContains(response, "␍")
        self.assertContains(response, "⇥")

    def test_existing_preview_links_to_comparison(self):
        response = self.client.get("/dev/editorial-preview", HTTP_HOST="localhost")
        self.assertContains(response, 'href="' + self.url + '"')
