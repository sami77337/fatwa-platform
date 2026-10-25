"""Read-only local rehearsal navigation and fail-closed boundaries."""

import os
from html.parser import HTMLParser
from unittest.mock import patch

from django.test import SimpleTestCase, override_settings


class Links(HTMLParser):
    def __init__(self, content):
        super().__init__()
        self.links = []
        self.ids = []
        self.tags = []
        self.feed(content)

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        self.tags.append(tag)
        if "id" in attrs:
            self.ids.append(attrs["id"])
        if tag == "a":
            self.links.append(attrs.get("href", ""))


@override_settings(ALLOWED_HOSTS=["localhost", "127.0.0.1", "[::1]", "remote.invalid"])
class RehearsalViewsTests(SimpleTestCase):
    base = "/dev/workflow-rehearsal"

    def get(self, path="", **kwargs):
        return self.client.get(
            self.base + path, HTTP_HOST="localhost", REMOTE_ADDR="127.0.0.1", **kwargs
        )

    def test_index_and_valid_invalid_transition_detail(self):
        response = self.get()
        self.assertEqual(response.status_code, 200)
        for text in ('lang="ar"', 'dir="rtl"', 'href="#main-content"'):
            self.assertContains(response, text)
        for key in ("history", *(f"intake-{i}" for i in range(1, 9))):
            self.assertContains(response, self.base + "/" + key)
        response = self.get("/intake-7")
        for text in (
            "RECEIVED",
            "draft_preparation",
            "IN_REVIEW",
            "NEEDS_CHANGES",
            "REVIEWED_INTERNAL",
            'data-accepted="true"',
            'data-accepted="false"',
            "ليست اعتماداً علمياً",
            "Gate B NOT_PASSED",
            "C/D/E HOLD",
            "Phase01 BLOCKED",
            "SCOPE_DEVIATION_HOLD",
            "NOT_DEPLOYED",
        ):
            self.assertContains(response, text)
        self.assertEqual(response["Cache-Control"], "no-store")
        parsed = Links(response.content.decode())
        self.assertEqual(len(parsed.ids), len(set(parsed.ids)))
        self.assertFalse(set(parsed.tags) & {"script", "form", "iframe", "video", "audio"})

    def test_steps_inspect_prefix_without_mutation(self):
        full = self.get("/intake-7")
        self.assertEqual(full.status_code, 200)
        result = full.context["rehearsal"]
        for ordinal in range(len(result.steps) + 1):
            response = self.get(f"/intake-7?step={ordinal}")
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.context["selected_step"], ordinal)
            self.assertEqual(response.context["rehearsal"], result)
            self.assertEqual(len(response.context["visible_steps"]), ordinal)
        self.assertEqual(self.get("/intake-7").content, full.content)

    def test_exact_existing_history_source_and_links(self):
        from apps.editorial_workbench.services import build_cases

        for case in build_cases():
            response = self.get("/" + case.key)
            self.assertEqual(response.status_code, 200)
            self.assertContains(response, case.payload_sha256)
            self.assertEqual(
                str(response.context["question"]).replace("&#13;", "\r"),
                case.question or "لم يرد نص سؤال",
            )
            links = Links(response.content.decode()).links
            for prefix in ("/dev/editorial-workbench/", "/dev/reference-triage/"):
                target = prefix + case.key
                self.assertIn(target, links)
                linked = self.client.get(target, HTTP_HOST="localhost", REMOTE_ADDR="127.0.0.1")
                self.assertEqual(linked.status_code, 200)
            if case.record is None:
                self.assertContains(response, "لا توجد مسودة")

    def test_invalid_queries_and_unknown_cases(self):
        for path in (
            "?step=1",
            "/intake-7?step=-1",
            "/intake-7?step=01",
            "/intake-7?step=999",
            "/intake-7?step=",
            "/intake-7?step=1&step=2",
            "/intake-7?action=publish",
            "/intake-7?step=" + "9" * 500,
            "/style.css?x=1",
        ):
            self.assertEqual(self.get(path).status_code, 400, path)
        self.assertEqual(self.get("/unknown").status_code, 404)

    def test_methods_head_and_local_guard(self):
        for path in ("", "/intake-7", "/style.css"):
            head = self.client.head(
                self.base + path, HTTP_HOST="localhost", REMOTE_ADDR="127.0.0.1"
            )
            self.assertEqual(head.status_code, 200)
            self.assertEqual(head.content, b"")
            self.assertEqual(head["Cache-Control"], "no-store")
            for method in ("post", "put", "patch", "delete", "options", "trace"):
                response = getattr(self.client, method)(
                    self.base + path, HTTP_HOST="localhost", REMOTE_ADDR="127.0.0.1"
                )
                self.assertEqual(response.status_code, 405)
        for host, peer in (("remote.invalid", "127.0.0.1"), ("localhost", "192.0.2.1")):
            response = self.client.get(self.base, HTTP_HOST=host, REMOTE_ADDR=peer)
            self.assertEqual(response.status_code, 404)
        with patch.dict(os.environ, {"FATWA_PRODUCTION": "1"}):
            self.assertEqual(self.get().status_code, 404)
        with override_settings(FATWA_PRODUCTION=True):
            self.assertEqual(self.get().status_code, 404)

    def test_data_failure_is_safe(self):
        from apps.editorial_workbench.services import WorkbenchDataError

        with patch(
            "apps.workflow_rehearsal.views.build_rehearsal",
            side_effect=WorkbenchDataError("secret"),
        ):
            response = self.get("/intake-7")
        self.assertEqual(response.status_code, 503)
        self.assertNotContains(response, "secret", status_code=503)
        self.assertEqual(response["Cache-Control"], "no-store")
