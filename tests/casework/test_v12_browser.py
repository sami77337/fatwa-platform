"""One connected V12 P1 browser journey; V11 utilities, no inherited old test.

Every workflow decision below is made through an actual native form. Only the
synthetic identity/source catalog bootstrap and isolated recovery are fixtures.
"""

import json
import os
import shutil
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from tempfile import TemporaryDirectory
from urllib.parse import urlsplit

from django.db import close_old_connections, connection, connections
from django.test import LiveServerTestCase, override_settings

from apps.casework import services as cases
from apps.composite_delivery import services as composite
from apps.delivery_planner.planner import Capabilities
from apps.pilot_workbench.fixtures import setup_synthetic_fixture
from apps.platform_recovery import encrypted, maintenance
from apps.private_media.filesystem import FileSystemStorage
from apps.private_media.fixtures import synthetic_files
from apps.research_workspace.source_rights_adapter import SourceRightsAdapter
from tests.casework.test_v7_browser import BrowserPublicationAuthority
from tests.casework.test_v9_browser import KnowledgePolicy
from tests.casework.test_v11_browser import FEATURES, V11Harness
from tests.casework.v11_fixtures import (
    DRAFT,
    PRIVATE,
    REPLY,
    Directory,
    OperatorAuthority,
    RightsAuthority,
    bootstrap,
)
from tests.casework.v12_fixtures import APPROVED_TEXT, OUT, inventory


class V12Harness(V11Harness):
    def context(self, browser):
        context = browser.new_context(viewport={"width": 1280, "height": 900})
        context.on("page", lambda page: page.on("pageerror", lambda e: self.errors.append(str(e))))
        if not hasattr(self, "bundled_pdf_requests"):
            self.bundled_pdf_requests = []
            self.bundled_pdf_origins = {}

        def route(request):
            url = urlsplit(request.request.url)
            # Chromium's observed built-in PDF viewer is packaged browser code,
            # not an external network destination. Every nonlocal HTTP request,
            # including one made by that viewer, still takes the blocked branch.
            if (url.scheme, url.netloc) in {
                ("chrome-extension", "mhjfbmdgcfjbbpaeojofohoefgiehjai"),
                ("chrome", "resources"),
            }:
                origin = url.scheme + "://" + url.netloc
                self.bundled_pdf_requests.append(url.path)
                self.bundled_pdf_origins[origin] = self.bundled_pdf_origins.get(origin, 0) + 1
                request.continue_()
            elif (
                url.scheme in {"http", "https"}
                and url.netloc == urlsplit(self.live_server_url).netloc
            ):
                request.continue_()
            else:
                self.external.append(request.request.url)
                request.abort()

        context.route("**/*", route)
        return context

    def respect_budget_window(self):
        from tests.casework.v11_restored_browser import respect_restored_budget_window

        def wait_for_expiry():
            close_old_connections()
            try:
                return respect_restored_budget_window()
            finally:
                connections.close_all()

        # A complete automated multi-role journey can exceed the real staff
        # POST budget in under a minute. Wait for its actual window; never retry
        # a rejected action, erase counters, change clocks or raise the limit.
        with ThreadPoolExecutor(max_workers=1) as pool:
            return pool.submit(wait_for_expiry).result(timeout=70)

    def submit(self, page, button, *, status=200):
        with page.expect_navigation(wait_until="domcontentloaded") as navigation:
            button.focus()
            button.press("Enter")
        response = navigation.value
        detail = response.text()[:300] if response.status >= 400 else "native form"
        self.assertEqual(response.status, status, detail)
        self.assertIn("no-store", response.headers.get("cache-control", ""))
        return response

    def capture(self, page, label):
        OUT.mkdir(parents=True, exist_ok=True)
        for width in (320, 1280):
            page.set_viewport_size({"width": width, "height": 900})
            page.wait_for_load_state("networkidle")
            self.assertEqual(page.locator("html").get_attribute("dir"), "rtl")
            self.assertLessEqual(page.evaluate("document.documentElement.scrollWidth"), width)
            page.screenshot(path=str(OUT / f"{label}-{width}.png"), full_page=True)

    def clarify_and_reply(self, staff, requester, source, files):
        self.open_case(staff, source["public_ref"])
        staff.locator("#clarification-text").fill("استيضاح اصطناعي: أرفق بيان المثال.")
        self.click(staff, "طلب استيضاح")
        requester.goto(self.live_server_url + "/casework/status/")
        requester.locator("#portal-token").fill(source["token"])
        self.click(requester, "فتح قضيتي")
        requester.locator("#portal-followup").fill(REPLY)
        mime, raw = files["synthetic.png"]
        requester.locator("#reply-attachment").set_input_files(
            {"name": "synthetic.png", "mimeType": mime, "buffer": raw}
        )
        requester.locator('#portal-reply-form [name="synthetic_only"]').check()
        self.click(requester, "إرسال التعقيب")
        self.assertIn("حُفظ ردك ومرفقه معًا", requester.content())
        picture = requester.locator("#attachments img")
        picture.scroll_into_view_if_needed()
        picture.evaluate("img=>img.decode()")
        self.assertGreater(picture.evaluate("img=>img.naturalWidth"), 0)
        self.assertNotIn(PRIVATE, requester.content())
        self.capture(requester, "atomic-clarification-reply")
        for name in ("synthetic.pdf", "synthetic.wav"):
            mime, raw = files[name]
            requester.locator("#portal-attachment").set_input_files(
                {"name": name, "mimeType": mime, "buffer": raw}
            )
            self.form(requester, "attachment_upload").locator('[name="synthetic_only"]').check()
            self.click(requester, "حفظ مرفق السؤال")
        self.assertEqual(requester.locator("#attachments article").count(), 3)
        evidence_audio = requester.locator("#attachments audio")
        evidence_audio.evaluate("async e=>{await e.play();}")
        self.assertGreater(evidence_audio.evaluate("e=>e.duration"), 0)
        self.assertEqual(requester.locator('[data-history-kind="attachment"]').count(), 3)
        self.capture(requester, "three-original-evidence-attachments")
        self.open_case(staff, source["public_ref"])
        self.assertEqual(staff.locator("#mufti-connected-journey").count(), 1)
        self.assertEqual(staff.locator("#mufti-evidence-history").count(), 1)
        self.assertEqual(staff.locator("[data-evidence-attachment]").count(), 3)
        before = self.sync(lambda: cases.read_case(**self.common)["revision"])
        self.submit(staff, staff.locator("#mufti-next-action"))
        self.assertEqual(self.sync(lambda: cases.read_case(**self.common)["revision"]), before)
        staff.locator("#answer-text").fill(DRAFT)
        self.click(staff, "حفظ مسودة الجواب")

    def rights_review(self, staff, reviewer, source, edition):
        super().rights_review(staff, reviewer, source, edition)
        # P1 registry has no technical IDs to enter and never turns a TOC into text.
        self.action(staff, "rights_desk")
        staff.locator("#rights-edition").select_option(str(edition))
        staff.locator("#rights-query").fill("فرع")
        self.click(staff, "بحث المصادر الحالية")
        self.click(staff, "تفاصيل الحقوق ومقارنة الإصدارات")
        self.assertIn("فهرس", staff.locator("#rights-material-kind").inner_text())
        matrix = staff.locator("#rights-usage-matrix").inner_text()
        self.assertIn("اقتباس", matrix)
        self.assertIn("نشر", matrix)
        self.assertEqual(staff.locator("#rights-revision-comparison").count(), 1)
        self.capture(staff, "exact-source-rights-inspection")
        self.click(staff, "العودة إلى نتائج المصادر نفسها")
        self.assertEqual(staff.locator("#rights-query").input_value(), "فرع")
        self.assertEqual(staff.locator("#rights-edition").input_value(), str(edition))
        self.click(staff, "العودة إلى القضية")

    def research_and_parts(self, staff, source, edition, files):
        # Research_add creates a current evidence-bound answer, retaining history.
        self.action(staff, "research_open")
        staff.locator("#query").fill("فرع")
        staff.locator("#kind").select_option("REFERENCE")
        staff.locator("#edition").select_option(str(edition))
        staff.locator("#part").fill("مقدمة")
        staff.locator("#page").fill("2")
        self.click(staff, "البحث في المصادر المصرح بها")
        self.click(staff, "فتح المصدر: فَرْعٌ تَجْرِيبِيّ")
        self.assertIn("لا يوجد متن كتاب", staff.content())
        self.click(staff, "العودة إلى نتائج البحث نفسها")
        self.assertEqual(staff.locator("#query").input_value(), "فرع")
        self.assertEqual(staff.locator("#page").input_value(), "2")
        self.click(staff, "فتح المصدر: فَرْعٌ تَجْرِيبِيّ")
        staff.locator("#note").fill(PRIVATE)
        self.form(staff, "research_add").locator('[name="confirm"]').check()
        self.submit_form(staff, "research_add")
        self.click(staff, "العودة إلى القضية")
        self.action(staff, "answer_media")
        for name in ("synthetic.wav", "synthetic.pdf"):
            self.assertEqual(staff.locator("#multipart-text").input_value(), DRAFT)
            mime, raw = files[name]
            staff.locator("#answer-file").set_input_files(
                {"name": name, "mimeType": mime, "buffer": raw}
            )
            self.form(staff, "answer_media_save").locator('[name="synthetic_only"]').check()
            self.click(staff, "حفظ إصدار متعدد الأجزاء")
        # Keep both immutable file identities, reorder into text/PDF/audio.
        staff.locator("#answer-part-order summary").click()
        audio_id = staff.locator("#part-order-2").input_value()
        file_id = staff.locator("#part-order-3").input_value()
        staff.locator("#part-order-2").select_option(file_id)
        staff.locator("#part-order-3").select_option(audio_id)
        self.click(staff, "حفظ ترتيب الأجزاء في نسخة جديدة")
        self.action(staff, "case_workspace")
        staff.locator("#return-note").fill("مراجعة بشرية اصطناعية لترتيب الملف والصوت.")
        self.click(staff, "إعادة للمراجعة")
        self.assertIn("مراجعة بشرية اصطناعية", staff.locator("#mufti-return-reason").inner_text())
        self.action(staff, "answer_media")
        staff.locator("#multipart-text").fill(APPROVED_TEXT)
        self.form(staff, "answer_media_save").locator('[name="synthetic_only"]').check()
        self.click(staff, "حفظ إصدار متعدد الأجزاء")
        self.action(staff, "case_workspace")
        self.assertEqual(staff.locator("#mufti-answer-revision").inner_text(), "6")
        self.assertEqual(staff.locator("#review audio").count(), 1)
        self.assertEqual(staff.locator("#review iframe").count(), 1)
        self.click(staff, "اعتماد هذه النسخة")
        self.action(staff, "answer_media")
        self.form(staff, "answer_media_release").locator('[name="confirm"]').check()
        self.click(staff, "إتاحة النسخة المعتمدة للسائل تجريبيًا")
        self.capture(staff, "human-approved-three-part-answer")

    def pilot_reports(self, staff, requester):
        self.action(staff, "pilot_open")
        self.form(staff, "pilot_authorize").locator('[name="confirm"]').check()
        self.click(staff, "تأكيد إذن الإرجاع التجريبي")
        # Text accepted then delivered; PDF fails; audio accepted only. No retry.
        for outcome, expected in (
            ("ACCEPTED", "PROVIDER_ACCEPTED"),
            ("DELIVERED", "UNRESOLVED"),
            ("FAILED", "UNRESOLVED"),
            ("ACCEPTED", "UNRESOLVED"),
        ):
            form = self.form(staff, "pilot_report")
            form.locator('[name="outcome"]').select_option(outcome)
            form.locator('[name="confirm"]').check()
            self.submit_form(staff, "pilot_report")
            requester.reload(wait_until="domcontentloaded")
            self.assertEqual(requester.locator("#authorized-answer").inner_text(), APPROVED_TEXT)
            self.assertEqual(
                requester.locator("[data-delivery-state]").get_attribute("data-delivery-state"),
                expected,
            )
        self.assertIn("1 / 3", requester.locator("#delivery").inner_text())
        self.assertIn("لا يوجد إثبات قراءة", staff.content())
        self.assertEqual(requester.locator("#answer audio").count(), 1)
        self.assertEqual(requester.locator("#answer iframe").count(), 1)
        self.assertNotIn(PRIVATE, requester.content())
        self.capture(requester, "partial-delivery-private-availability")
        self.click(staff, "فتح مكتب التوصيل ومراجعة المحاولات")
        self.capture(staff, "partial-delivery-human-review")

    def staff_library_roundtrip(self, staff):
        self.action(staff, "pub_open")
        self.action(staff, "pub_library")
        search = self.form(staff, "pub_library")
        search.locator('[name="query"]').fill("عنوان V11")
        search.locator('[name="category"]').select_option("تجربة مغلقة")
        self.submit(staff, search.get_by_role("button", name="بحث", exact=True))
        self.click(staff, "فتح صفحة النسخة")
        self.assert_case_header(staff, self.source["public_ref"])
        self.click(staff, "الدروس والمراجع المرتبطة")
        self.assert_case_header(staff, self.source["public_ref"])
        self.click(staff, "فتح المادة المصرح بها")
        self.assert_case_header(staff, self.source["public_ref"])
        self.assertIn("فَرْعٌ تَجْرِيبِيّ", staff.content())
        self.capture(staff, "publication-knowledge-source-return")
        self.click(staff, "العودة إلى نسخة الفتوى التجريبية")
        self.click(staff, "العودة إلى المكتبة التجريبية")
        search = self.form(staff, "pub_library")
        self.assertEqual(search.locator('[name="query"]').input_value(), "عنوان V11")
        self.assertEqual(search.locator('[name="category"]').input_value(), "تجربة مغلقة")
        self.assertEqual(self.form(staff, "pub_read").locator('[name="page"]').input_value(), "1")


@override_settings(**FEATURES)
class V12ConnectedBrowserTests(V12Harness, LiveServerTestCase):
    host = "127.0.0.1"

    def test_one_v12_case_partial_delivery_encrypted_restore_and_target_http(self):
        from playwright.sync_api import sync_playwright

        OUT.mkdir(parents=True, exist_ok=True)
        self.errors, self.external = [], []
        self.source, edition, _ = bootstrap()
        directory = Directory()
        directory.refs = frozenset({self.source["public_ref"]})
        self.common = dict(
            case_id=self.source["case_id"],
            subject_id="synthetic-mufti",
            provider=directory,
            synthetic_fixtures_only=True,
        )
        profile = composite.ChannelProfile(
            Capabilities(
                composite.SIMULATOR_PROVIDER,
                "synthetic.v1",
                frozenset({"text", "audio", "document", "image"}),
                6000,
                True,
            ),
            192000,
            frozenset({"text/plain", "audio/wav", "image/png", "application/pdf"}),
        )
        files = {name: (mime, raw) for name, mime, raw in synthetic_files()}
        with (
            TemporaryDirectory(prefix="v12-source-") as private_root,
            TemporaryDirectory(prefix="v12-control-") as control,
            TemporaryDirectory(prefix="v12-keys-") as keys,
            TemporaryDirectory(prefix="v12-sealed-") as backup_root,
            TemporaryDirectory(prefix="v12-target-") as target_root,
        ):
            storage = FileSystemStorage(private_root, synthetic_fixtures_only=True)
            maintenance.initialize(root=control, storage=storage, synthetic_fixtures_only=True)
            with override_settings(
                FATWA_PRIVATE_MEDIA_STORAGE=storage,
                FATWA_CASEWORK_IDENTITY_PROVIDER=directory,
                FATWA_SOURCE_RIGHTS_AUTHORITY=RightsAuthority(directory),
                FATWA_RESEARCH_WORKSPACE_RIGHTS=SourceRightsAdapter(),
                FATWA_EXPERIMENTAL_PUBLICATION_AUTHORITY=BrowserPublicationAuthority(directory),
                FATWA_KNOWLEDGE_LINKS_AUTHORITY=KnowledgePolicy(directory),
                FATWA_COMPOSITE_DELIVERY_CAPABILITIES=lambda _: profile,
                FATWA_RECOVERY_MAINTENANCE_ROOT=control,
                FATWA_RECOVERY_MAINTENANCE_REQUIRED=True,
            ):
                fixture = setup_synthetic_fixture(
                    operator_authority=OperatorAuthority(directory),
                    identity_provider=directory,
                    synthetic_fixtures_only=True,
                )
                with override_settings(**fixture.settings()), sync_playwright() as p:
                    sandbox = os.environ.get("FATWA_BROWSER_SANDBOX", "1") != "0"
                    browser = p.chromium.launch(
                        executable_path=os.environ.get(
                            "FATWA_FASTBUILD_BROWSER", "/usr/bin/chromium"
                        ),
                        headless=True,
                        chromium_sandbox=sandbox,
                        args=["--disable-dev-shm-usage"],
                    )
                    try:
                        staff, requester, reviewer = [
                            self.context(browser).new_page() for _ in range(3)
                        ]
                        self.login(staff, "M" * 64)
                        self.review_source(staff, self.source)
                        self.clarify_and_reply(staff, requester, self.source, files)
                        self.rights_review(staff, reviewer, self.source, edition)
                        self.research_and_parts(staff, self.source, edition, files)
                        source_budget = self.respect_budget_window()
                        self.pilot_reports(staff, requester)
                        policy = self.publish_and_relate(staff, reviewer, edition)
                        self.staff_library_roundtrip(staff)
                        with override_settings(FATWA_LIBRARY_PREVIEW_POLICY=policy):
                            self.anonymous_preview(browser)
                        expected = self.sync(lambda: inventory(self.source["case_id"]))
                        self.assertEqual(expected["source_review"], ["HOLD", "REOPEN"])
                        self.assertEqual(
                            expected["counts"],
                            {
                                "cases": 1,
                                "evidence": 6,
                                "source_bindings": 2,
                                "answers": 6,
                                "citations": 1,
                                "parts": 3,
                                "attachments": 3,
                                "rights_sources": 1,
                                "rights_revisions": 1,
                                "rights_approvals": 1,
                                "source_review_notes": 2,
                                "delivery_intents": 3,
                                "publication_approvals": 1,
                                "knowledge_links": 1,
                                "knowledge_approvals": 1,
                            },
                        )
                        self.assertEqual(
                            [row["state"] for row in expected["delivery"]["parts"]],
                            ["DELIVERED", "FAILED_REQUIRES_REVIEW", "SENT_UNCONFIRMED"],
                        )
                        self.assertEqual(expected["delivery"]["attempts"], 3)
                        self.assertEqual(expected["delivery"]["receipts"], 4)
                        self.freeze(staff, storage, control)
                        self.assertEqual(
                            staff.request.get(self.live_server_url + "/casework/staff/").status, 503
                        )
                        self.assertEqual(self.external, [])
                        self.assertEqual(self.errors, [])
                        browser_version = browser.version
                    finally:
                        browser.close()
                self.server_thread.terminate()
                self.assertFalse(self.server_thread.is_alive())
                pg_bin = os.environ.get("FATWA_RECOVERY_PG_BIN") or str(
                    Path(shutil.which("pg_dump")).parent
                )
                key_file = Path(keys) / "backup.key"
                encrypted.generate_key(path=key_file, synthetic_fixtures_only=True)
                sealed = encrypted.snapshot(
                    scratch=backup_root,
                    storage=storage,
                    pg_bin=pg_bin,
                    key_file=key_file,
                    maintenance_root=control,
                    synthetic_fixtures_only=True,
                )
                pin = sealed["ciphertext_sha256"]
                encrypted.verify(
                    bundle=sealed["bundle"], expected_ciphertext_sha256=pin, key_file=key_file
                )
                self.assertEqual(
                    {p.name for p in Path(sealed["bundle"]).iterdir()},
                    {"COMPLETE", "backup.fernet"},
                )
                spec = {
                    "bundle": sealed["bundle"],
                    "ciphertext_sha256": pin,
                    "key_file": str(key_file),
                    "scratch": target_root,
                    "pg_bin": pg_bin,
                    "source_server_port": str(connection.settings_dict["PORT"]),
                    "source_database": connection.settings_dict["NAME"],
                    "source_private_root": private_root,
                    "expected": expected,
                    "public_ref": self.source["public_ref"],
                    "token": self.source["token"],
                    "approval_public_key": fixture.approval_verifier._keys["ephemeral-pilot"]
                    .public_bytes_raw()
                    .hex(),
                    "provider_public_key": fixture.provider_verifier._keys["ephemeral-fixture"]
                    .public_bytes_raw()
                    .hex(),
                }
                result = subprocess.run(
                    [
                        sys.executable,
                        "-m",
                        "infra.dev.with_casework_postgres",
                        "--pg-bin",
                        pg_bin,
                        "--major",
                        os.environ["PG_EXPECTED_MAJOR"],
                        "--settings",
                        "config.settings.campaign_review",
                        "--",
                        sys.executable,
                        "-c",
                        "import django; django.setup(); from tests.casework.v12_restored_browser import restore_and_verify; restore_and_verify()",
                    ],
                    input=json.dumps(spec),
                    text=True,
                    capture_output=True,
                    timeout=180,
                    env=os.environ.copy(),
                )
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertIn("V12_RESTORED_HTTP_PASS", result.stdout)
                self.assertEqual(inventory(self.source["case_id"]), expected)
                self.assertEqual(maintenance.status(root=control)["phase"], "FROZEN")
                # The old source remains FROZEN; no sender, cached worker or
                # old application is resumed after target verification.
                (OUT / "result.json").write_text(
                    json.dumps(
                        {
                            "status": "PASS",
                            "browser": browser_version,
                            "sandbox": sandbox,
                            "widths": [320, 1280],
                            "canonical": expected["counts"],
                            "source_budget": source_budget,
                            "external_requests": self.external,
                            "bundled_pdf_resource_requests": len(self.bundled_pdf_requests),
                            "bundled_pdf_resource_origins": self.bundled_pdf_origins,
                            "page_errors": self.errors,
                            "maintenance": {
                                "draining_http": 503,
                                "direct_writer": "DENIED",
                                "gc": "DENIED",
                                "frozen_snapshot": True,
                            },
                            "recovery": {
                                "state": "READY",
                                "encrypted_only": True,
                                "separate_key": True,
                                "ciphertext_sha256": pin,
                                "target_http": "PASS",
                                "independent_target_postgres_server": True,
                                "source_unchanged": True,
                                "source_left_frozen": True,
                                "wrong_key_and_hash_before_target": "DENIED",
                                "partial_delivery_preserved": True,
                            },
                        },
                        indent=2,
                    )
                )
