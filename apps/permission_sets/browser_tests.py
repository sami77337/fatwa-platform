"""One protected native permission-management journey and actual organizer use."""

import json
import os
from pathlib import Path
from urllib.parse import urlsplit

from django.test import LiveServerTestCase, override_settings

from apps.case_organization.models import OrganizationRevision
from apps.operational_workspace import browser_tests as operational_browser
from apps.operational_workspace.test_support import CREDENTIALS

from . import catalog
from .models import PermissionRevision
from .test_support import FEATURES, Fixture

OUT = Path(".local/qa/functional-continuation/permission-sets-browser")


@override_settings(**FEATURES)
class PermissionSetsBrowserTests(Fixture, LiveServerTestCase):
    host = "127.0.0.1"
    sync = operational_browser.OperationalWorkspaceBrowserTests.sync
    submit = operational_browser.OperationalWorkspaceBrowserTests.submit

    def setUp(self):
        super().setUp()
        self.seeded()

    def capture(self, page, name):
        for width in (320, 1280):
            page.set_viewport_size({"width": width, "height": 900})
            self.assertEqual(page.locator("html").get_attribute("dir"), "rtl")
            self.assertLessEqual(page.evaluate("document.documentElement.scrollWidth"), width)
            page.screenshot(path=str(OUT / f"{name}-{width}.png"), full_page=True)

    def open_user(self, page):
        self.submit(page, page.locator('[data-user="operator"] button'))

    def confirm(self, page):
        page.locator('#ps-confirm [name="confirmed"]').check()
        self.submit(page, page.locator("#ps-confirm button"))
        self.assertEqual(page.locator("#ps-saved").count(), 1)

    def open_notes(self, page):
        response = page.goto(self.live_server_url + "/casework/operations/")
        self.assertEqual(response.status, 200)
        card = page.locator(f'article[data-case-ref="{self.receipt["public_ref"]}"]')
        self.submit(page, card.locator(".ops-notes-open button"))

    def test_native_templates_individual_denial_audit_disable_and_revert(self):
        if os.environ.get("FATWA_BROWSER_SANDBOX") != "1":
            self.fail("Protected permission-set browser evidence requires FATWA_BROWSER_SANDBOX=1")
        from playwright.sync_api import sync_playwright

        OUT.mkdir(parents=True, exist_ok=True)
        (OUT / "result.json").unlink(missing_ok=True)
        errors, external, contexts = [], [], []
        with sync_playwright() as p:
            browser = p.chromium.launch(
                executable_path=os.environ.get("FATWA_FASTBUILD_BROWSER") or None,
                headless=True,
                chromium_sandbox=True,
            )
            try:
                pages = {}
                for subject in ("operator", "admin"):
                    context = browser.new_context(
                        locale="ar", viewport={"width": 1280, "height": 900}
                    )
                    contexts.append(context)

                    def route(request):
                        if (
                            urlsplit(request.request.url).netloc
                            != urlsplit(self.live_server_url).netloc
                        ):
                            external.append(request.request.url)
                            request.abort()
                        else:
                            request.continue_()

                    context.route("**/*", route)
                    context.tracing.start(screenshots=True, snapshots=True)
                    page = context.new_page()
                    page.on("pageerror", lambda error: errors.append(str(error)))
                    self.assertEqual(
                        page.goto(self.live_server_url + "/casework/operations/login/").status, 200
                    )
                    page.locator('[name="credential"]').fill(CREDENTIALS[subject])
                    self.submit(page, page.locator("#ops-login button"))
                    pages[subject] = page
                operator, admin = pages["operator"], pages["admin"]
                self.open_notes(operator)
                self.assertIn("ORGANIZER", operator.locator("#ops-actor").inner_text())
                operator.locator('#ops-note-add [name="note"]').fill(
                    "طلب قديم يجب رفضه بعد سحب الإضافة"
                )
                path = self.live_server_url + "/casework/operations/permissions/"
                self.assertEqual(admin.goto(path).status, 200)
                self.open_user(admin)
                key = catalog.digest(self.scopes["ADD_INTERNAL_NOTE"])
                admin.locator(f'#ps-edit [name="deny"][value="{key}"]').check()
                admin.locator('#ps-edit [name="note"]').fill("رفض فردي للإضافة مع بقاء القراءة")
                self.submit(admin, admin.locator("#ps-edit button"))
                self.assertEqual(admin.locator('[data-affected="operator"]').count(), 1)
                self.assertTrue(self.sync(lambda: self.allowed("ADD_INTERNAL_NOTE")))
                self.capture(admin, "preview-individual-deny")
                self.confirm(admin)
                self.submit(operator, operator.locator("#ops-note-add button"), expected=409)
                self.assertEqual(self.sync(lambda: OrganizationRevision.objects.count()), 0)
                self.submit(admin, admin.locator("#ps-open-saved button"))
                self.assertEqual(admin.locator("#ps-history > article").count(), 2)
                admin.locator(f'#ps-edit [name="deny"][value="{key}"]').uncheck()
                admin.locator(f'#ps-edit [name="allow"][value="{key}"]').check()
                admin.locator('#ps-edit [name="note"]').fill("سماح فردي محدد بعد مراجعة سبب الرفض")
                self.submit(admin, admin.locator("#ps-edit button"))
                self.confirm(admin)
                self.open_notes(operator)
                operator.locator('#ops-note-add [name="note"]').fill(
                    "ملاحظة تنظيمية بعد إعادة الإذن <script>لا ينفذ</script>"
                )
                self.submit(operator, operator.locator("#ops-note-add button"))
                self.assertEqual(operator.locator("#ops-note-saved").count(), 1)
                self.assertEqual(operator.locator("#ops-note-history > article").count(), 1)
                self.capture(operator, "organizer-after-current-grant")
                self.submit(admin, admin.locator("#ps-back button"))
                self.submit(admin, admin.locator(f'[data-set="{self.template_key}"] button'))
                admin.locator(f'#ps-edit [name="allow"][value="{key}"]').uncheck()
                admin.locator(f'#ps-edit [name="deny"][value="{key}"]').check()
                admin.locator('#ps-edit [name="note"]').fill(
                    "رفض من القالب يتقدم على السماح الفردي"
                )
                self.submit(admin, admin.locator("#ps-edit button"))
                self.confirm(admin)
                operator.locator('#ops-note-add [name="note"]').fill(
                    "طلب يرفضه القالب رغم السماح الفردي"
                )
                self.submit(operator, operator.locator("#ops-note-add button"), expected=409)
                self.submit(admin, admin.locator("#ps-open-saved button"))
                admin.locator('#ps-disable [name="note"]').fill("تعطيل القالب مؤقتًا بسبب إداري")
                self.submit(admin, admin.locator("#ps-disable button"))
                self.confirm(admin)
                self.assertEqual(
                    operator.goto(self.live_server_url + "/casework/operations/").status, 200
                )
                self.assertEqual(operator.locator("#ops-queue > article").count(), 0)
                self.submit(admin, admin.locator("#ps-open-saved button"))
                original = admin.locator('#ps-history > article[data-version="1"] .ps-revert')
                original.locator('[name="note"]').fill("رجوع صريح إلى التعريف الأول بإصدار جديد")
                self.submit(admin, original.locator("button"))
                self.confirm(admin)
                self.open_notes(operator)
                self.assertEqual(operator.locator("#ops-note-history > article").count(), 1)
                self.assertEqual(operator.locator("#ops-note-add").count(), 1)
                self.submit(admin, admin.locator("#ps-open-saved button"))
                self.assertEqual(admin.locator("#ps-history > article").count(), 4)
                self.capture(admin, "template-disable-revert-audit")
                self.sync(self.assert_original)
                self.assertEqual(self.sync(lambda: PermissionRevision.objects.count()), 7)
                self.assertEqual(errors, [])
                self.assertEqual(external, [])
                (OUT / "result.json").write_text(
                    json.dumps(
                        {
                            "status": "PASS",
                            "sandbox": True,
                            "widths": [320, 1280],
                            "actual_roles": ["ORGANIZER_ADMIN", "ORGANIZER"],
                            "native_preview_and_confirmation": True,
                            "deny_wins": True,
                            "audit_revisions": 7,
                            "disable_and_fresh_revert": True,
                            "late_stale_form_rejected": True,
                            "positive_read_after_denial": True,
                            "originals_unchanged": True,
                            "external_requests": external,
                            "page_errors": errors,
                        },
                        ensure_ascii=False,
                        indent=2,
                    )
                )
            finally:
                for index, context in enumerate(contexts):
                    context.tracing.stop(path=str(OUT / f"trace-{index}.zip"))
                    context.close()
                browser.close()
