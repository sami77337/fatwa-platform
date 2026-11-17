"""V10 connected browser harness; feature steps use integration-owned contracts.

The completed test follows one source case through human ambiguity resolution,
private upload, the unified Mufti editor, composite delivery, independent
publication, the closed library and restore into a different owned database.
No V9 test is inherited or rerun by this module.
"""

import json
import os
import shutil
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict, replace
from datetime import timedelta
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch
from urllib.parse import urlsplit

from django.db import close_old_connections, connection, connections
from django.test import LiveServerTestCase, override_settings
from django.utils import timezone

from apps.composite_delivery import services as composite
from apps.composite_delivery.simulator import OfflineProviderSimulator
from apps.delivery_planner.planner import Capabilities
from apps.experimental_publication.models import PublicationEdition
from apps.knowledge_links import services as knowledge
from apps.library_preview.policy import PreviewPolicy, PublicationGrant, ReferenceGrant
from apps.private_media.filesystem import FileSystemStorage
from apps.private_media.fixtures import synthetic_files
from apps.reference.ingest import ingest_catalog
from apps.reference.models import ReferenceHeading
from apps.transcript_case_links import services as transcripts
from apps.transcript_case_links.tests import bundle
from tests.casework.delivery_fixtures import CaseDeliveryFixture
from tests.casework.test_http import WEB_SETTINGS
from tests.casework.test_v7_browser import BrowserPublicationAuthority
from tests.casework.test_v9_browser import KnowledgePolicy
from tests.casework.v10_fixtures import (
    AMBIGUOUS,
    DRAFT,
    PRIVATE_NOTE,
    PUBLIC_TEXT,
    QUESTION,
    V10Directory,
    canonical_evidence,
    prepare_source_journey,
)
from tests.reference.test_catalog import fixture

OUT = Path(".local/qa/v10/browser")


class BrowserHarness:
    """Utilities only; no placeholder, skipped test or claimed browser result."""

    def sync(self, callback):
        def call():
            close_old_connections()
            try:
                return callback()
            finally:
                connections.close_all()

        with ThreadPoolExecutor(max_workers=1) as pool:
            return pool.submit(call).result(timeout=45)

    def submit(self, page, button, *, status=200):
        with page.expect_navigation(wait_until="domcontentloaded") as navigation:
            button.focus()
            button.press("Enter")
        self.assertEqual(navigation.value.status, status)
        self.assertIn("no-store", navigation.value.headers.get("cache-control", ""))
        return navigation.value

    def capture(self, page, label):
        OUT.mkdir(parents=True, exist_ok=True)
        for width in (320, 1280):
            page.set_viewport_size({"width": width, "height": 900})
            page.wait_for_load_state("networkidle")
            page.evaluate(
                "async()=>{await document.fonts.ready;await new Promise(r=>requestAnimationFrame(()=>requestAnimationFrame(r)));}"
            )
            self.assertEqual(page.locator("html").get_attribute("dir"), "rtl")
            self.assertLessEqual(page.evaluate("document.documentElement.scrollWidth"), width)
            page.screenshot(path=str(OUT / f"{label}-{width}.png"), full_page=True)

    def preview_library(self, browser, *, title, category, private_values):
        """Exercise the expiring anonymous surface after independent publication."""
        context = self.context(browser)
        page = context.new_page()
        private_requests = []
        page.on(
            "request",
            lambda request: (
                private_requests.append(request.url) if "/casework/" in request.url else None
            ),
        )
        try:
            response = page.goto(self.live_server_url + "/library-preview/")
            self.assertEqual(response.status, 200)
            self.assertIn("no-store", response.headers.get("cache-control", ""))
            page.locator("#q").fill("عنوان")
            page.locator("#category").select_option(category)
            page.locator("#material").select_option("reference")
            self.submit(page, page.get_by_role("button", name="بحث وتصفية", exact=True))
            self.assertIn("عدد النتائج: 1", page.content())
            self.capture(page, "anonymous-library-search")
            self.submit(page, page.get_by_role("link", name=title, exact=True))
            self.assertIn("مادة درس أو تفريغ مرتبطة خاصة", page.content())
            self.assertEqual(page.locator('a[href*="transcript"]').count(), 0)
            for value in private_values:
                self.assertNotIn(value, page.content())
            self.capture(page, "anonymous-publication")
            self.submit(
                page,
                page.get_by_role("link", name="علاقة موثقة: فَرْعٌ تَجْرِيبِيّ", exact=True),
            )
            self.assertIn("الجزء والصفحة المطبوعة", page.content())
            self.capture(page, "anonymous-reference")
            self.submit(page, page.get_by_role("link", name="العودة إلى " + title, exact=True))
            self.submit(
                page,
                page.get_by_role("link", name="العودة إلى نتائج البحث والتصفية", exact=True),
            )
            self.assertEqual(page.locator("#q").input_value(), "عنوان")
            self.assertEqual(page.locator("#category").input_value(), category)
            self.assertEqual(page.locator("#material").input_value(), "reference")
            self.assertEqual(context.cookies(), [])
            self.assertEqual(private_requests, [])
        finally:
            context.close()

    def click(self, page, label):
        return self.submit(page, page.get_by_role("button", name=label, exact=True))

    def action(self, page, name):
        selector = f'form:has([name="action"][value="{name}"])'
        # Supporting tools can repeat an action inside a closed details element.
        # Navigate through the persistent current-case tabs when they offer it.
        tabs = page.locator(".mufti-case-nav").locator(selector)
        form = tabs.first if tabs.count() else page.locator(selector).first
        button = form.get_by_role("button").first
        self.assertTrue(button.is_visible(), f"{name} navigation button must be visible")
        return self.submit(page, button)

    def assert_case_header(self, page, public_ref):
        self.assertEqual(page.locator("#mufti-case-reference").inner_text(), public_ref)

    def context(self, browser):
        context = browser.new_context(viewport={"width": 1280, "height": 900})
        context.on("page", lambda page: page.on("pageerror", lambda e: self.errors.append(str(e))))

        def route(r):
            if urlsplit(r.request.url).netloc != urlsplit(self.live_server_url).netloc:
                self.external.append(r.request.url)
                r.abort()
            else:
                r.continue_()

        context.route("**/*", route)
        return context

    def import_provider_receipt(self, page, ordinal, value):
        page.get_by_text(f"مطابقة إيصال الجزء {ordinal}", exact=True).click()
        form = page.locator(f"#part-{ordinal} form")
        form.locator("textarea").fill(value)
        form.locator('input[name="confirm"]').check()
        self.click(page, f"تسجيل إيصال الجزء {ordinal}")


@override_settings(
    **{
        **WEB_SETTINGS,
        # Preserve the explicitly selected isolated compatibility module through
        # Django's test overlay; the normal strict flags remain unchanged.
        "SETTINGS_MODULE": os.environ.get("DJANGO_SETTINGS_MODULE"),
        "ROOT_URLCONF": "config.campaign_urls",
        "MIDDLEWARE": [
            "apps.library_preview.guard.PreviewCompositionGuard",
            "django.middleware.csrf.CsrfViewMiddleware",
        ],
        "FATWA_MUFTI_WORKSPACE_ENABLED": True,
        "FATWA_REQUESTER_PORTAL_ENABLED": True,
        "FATWA_SOURCE_CASE_INTAKE_ENABLED": True,
        "FATWA_SOURCE_CASE_INTAKE_DESK_ENABLED": True,
        "FATWA_CASE_ATTACHMENTS_ENABLED": True,
        "FATWA_CASE_CITATIONS_ENABLED": True,
        "FATWA_ANSWER_MEDIA_ENABLED": True,
        "FATWA_ANSWER_MEDIA_PRIVATE_ENABLED": True,
        "FATWA_COMPOSITE_DELIVERY_ENABLED": True,
        "FATWA_EXPERIMENTAL_PUBLICATION_ENABLED": True,
        "FATWA_KNOWLEDGE_LINKS_ENABLED": True,
        "FATWA_LIBRARY_PREVIEW_ENABLED": True,
    }
)
class V10ConnectedBrowserTests(BrowserHarness, LiveServerTestCase):
    host = "127.0.0.1"

    def test_human_source_review_to_private_portal_library_and_isolated_restore(self):
        from playwright.sync_api import sync_playwright

        OUT.mkdir(parents=True, exist_ok=True)
        source = prepare_source_journey()
        directory = V10Directory()
        directory.refs = frozenset({source.public_ref})
        common = dict(
            case_id=source.case_id,
            subject_id="synthetic-mufti",
            provider=directory,
            synthetic_fixtures_only=True,
        )
        spec, rows = fixture()
        spec = replace(spec, source_book_id="622")
        preview = ingest_catalog(spec, rows)
        edition_id = ingest_catalog(
            spec, rows, dry_run=False, expected_checksum=preview.checksum
        ).edition_id
        heading_id = ReferenceHeading.objects.get(edition_id=edition_id, source_row_id=2).pk
        files = {name: (mime, raw) for name, mime, raw in synthetic_files()}
        signer = CaseDeliveryFixture()
        signer.intake = lambda _: {
            "case_id": source.case_id,
            "public_ref": source.public_ref,
            "token": source.token,
        }
        signer.setUp()
        signer.directory = directory
        simulator = OfflineProviderSimulator(synthetic_fixtures_only=True)
        profile = composite.ChannelProfile(
            Capabilities(
                composite.SIMULATOR_PROVIDER,
                "synthetic.v1",
                frozenset({"text", "audio", "document", "image"}),
                6000,
                True,
            ),
            192000,
            frozenset({"text/plain", "audio/wav", "application/pdf", "image/png"}),
        )
        self.errors, self.external = [], []
        with TemporaryDirectory(prefix="v10-private-") as storage_root:
            storage = FileSystemStorage(storage_root, synthetic_fixtures_only=True)
            with (
                override_settings(
                    FATWA_CASEWORK_IDENTITY_PROVIDER=directory,
                    FATWA_PRIVATE_MEDIA_STORAGE=storage,
                    FATWA_CASE_DELIVERY_APPROVAL_VERIFIER=signer.approval_verifier,
                    FATWA_COMPOSITE_DELIVERY_CAPABILITIES=lambda _: profile,
                    FATWA_COMPOSITE_DELIVERY_PROVIDER_VERIFIER=simulator.verifier,
                    FATWA_EXPERIMENTAL_PUBLICATION_AUTHORITY=BrowserPublicationAuthority(directory),
                    FATWA_KNOWLEDGE_LINKS_AUTHORITY=KnowledgePolicy(directory),
                ),
                sync_playwright() as p,
            ):
                sandbox = os.environ.get("FATWA_BROWSER_SANDBOX", "1") != "0"
                browser = p.chromium.launch(
                    executable_path=os.environ.get("FATWA_FASTBUILD_BROWSER", "/usr/bin/chromium"),
                    headless=True,
                    chromium_sandbox=sandbox,
                    args=["--disable-dev-shm-usage"],
                )
                try:
                    staff, requester, reviewer = [
                        self.context(browser).new_page() for _ in range(3)
                    ]

                    def login(page, credential):
                        page.goto(self.live_server_url + "/casework/staff/login/")
                        page.locator("#credential").fill(credential)
                        self.click(page, "دخول المكتب")

                    login(staff, "M" * 64)
                    self.action(staff, "source_inbox")
                    self.click(staff, "غير المحسوم")
                    self.click(staff, "فتح الحدث 2 من telegram")
                    with staff.expect_download() as download:
                        staff.get_by_role("button", name="تنزيل الأصل الخام", exact=True).click()
                    self.assertEqual(Path(download.value.path()).read_bytes(), source.pending_bytes)
                    staff.locator("#followup-token").fill(source.token)
                    staff.locator("#followup-note").fill(PRIVATE_NOTE)
                    staff.locator('#followup-form input[name="confirm"]').check()
                    self.click(staff, "تأكيد إلحاق التعقيب")
                    self.assertEqual(
                        staff.locator("#resolved-reference").inner_text(), source.public_ref
                    )
                    self.assertNotIn(source.token, staff.content())
                    self.capture(staff, "source-human-resolution")

                    requester.goto(self.live_server_url + "/casework/status/")
                    requester.locator("#portal-token").fill(source.token)
                    self.click(requester, "فتح قضيتي")
                    self.assertIn(QUESTION, requester.locator("#conversation").inner_text())
                    self.assertIn(AMBIGUOUS, requester.locator("#conversation").inner_text())
                    requester.locator("#portal-attachment").set_input_files(
                        {
                            "name": "synthetic.txt",
                            "mimeType": "text/plain",
                            "buffer": files["synthetic.txt"][1],
                        }
                    )
                    requester.locator(
                        'form:has(input[value="attachment_upload"]) input[name="synthetic_only"]'
                    ).check()
                    self.click(requester, "حفظ مرفق السؤال")
                    attachment_url = requester.get_by_role(
                        "link", name="فتح المرفق 1", exact=True
                    ).get_attribute("href")
                    response = requester.request.get(self.live_server_url + attachment_url)
                    self.assertEqual(response.status, 200)
                    self.assertEqual(response.body(), files["synthetic.txt"][1])
                    self.assertEqual(
                        requester.locator("[data-answer-state]").get_attribute("data-answer-state"),
                        "UNDER_REVIEW",
                    )
                    self.assertNotIn(PRIVATE_NOTE, requester.content())
                    self.capture(requester, "requester-original-and-upload")

                    # Existing transcript fixture is linked to this case; no answer or approval is seeded.
                    def link_transcript():
                        staged = transcripts.preview(**common, bundle=bundle())
                        linked = transcripts.attach(
                            **common,
                            upload_id=staged["upload_id"],
                            external_id=staged["entries"][0].external_id,
                        )
                        return linked, staged["entries"][0].question.text

                    transcript, transcript_text = self.sync(link_transcript)
                    staff.goto(self.live_server_url + "/casework/staff/")
                    staff.locator("#queue-query").fill("V10")
                    self.click(staff, "عرض القضايا")
                    self.click(staff, source.public_ref)
                    self.assert_case_header(staff, source.public_ref)
                    self.assertEqual(staff.locator("#mufti-evidence-version").inner_text(), "4")
                    self.capture(staff, "unified-mufti-original")
                    self.action(staff, "citations")
                    self.assert_case_header(staff, source.public_ref)
                    staff.locator("#answer").fill(DRAFT)
                    staff.locator("#edition").select_option(str(edition_id))
                    staff.locator("#query").fill("فرع")
                    self.click(staff, "اقتراح مصادر موجودة للمراجعة")
                    self.click(staff, "معاينة الاقتراح 2")
                    self.assertEqual(staff.locator("#answer").input_value(), DRAFT)
                    self.click(staff, "العودة إلى البحث والمسودة")
                    staff.locator("#note").fill(PRIVATE_NOTE)
                    self.click(staff, "اختيار الاقتراح 2 بعد مراجعتي")
                    staff.locator('input[name="confirm"]').check()
                    self.click(staff, "حفظ الجواب والقائمة الكاملة")
                    self.action(staff, "answer_media")
                    self.assertEqual(staff.locator("#multipart-text").input_value(), DRAFT)
                    staff.locator("#answer-file").set_input_files(
                        {
                            "name": "synthetic.wav",
                            "mimeType": "audio/wav",
                            "buffer": files["synthetic.wav"][1],
                        }
                    )
                    staff.locator('input[name="synthetic_only"]').check()
                    self.click(staff, "حفظ إصدار متعدد الأجزاء")
                    self.action(staff, "case_workspace")
                    self.assert_case_header(staff, source.public_ref)
                    self.assertEqual(staff.locator("#mufti-answer-revision").inner_text(), "2")
                    self.click(staff, "اعتماد هذه النسخة")
                    requester.reload(wait_until="domcontentloaded")
                    self.assertEqual(
                        requester.locator("[data-answer-state]").get_attribute("data-answer-state"),
                        "APPROVED_UNAVAILABLE",
                    )
                    self.assertEqual(requester.locator("#authorized-answer").count(), 0)
                    self.action(staff, "answer_media")
                    staff.locator(
                        'form:has(input[value="answer_media_release"]) input[name="confirm"]'
                    ).check()
                    self.click(staff, "إتاحة النسخة المعتمدة للسائل تجريبيًا")
                    requester.reload(wait_until="domcontentloaded")
                    self.assertEqual(requester.locator("#authorized-answer").inner_text(), DRAFT)
                    self.assertEqual(
                        requester.locator("[data-answer-state]").get_attribute("data-answer-state"),
                        "PRIVATE_AVAILABLE",
                    )
                    self.assertIn("فَرْعٌ تَجْرِيبِيّ", requester.locator("#answer").inner_text())
                    self.assertNotIn(PRIVATE_NOTE, requester.content())
                    self.assertNotIn(transcript_text, requester.content())
                    self.capture(requester, "same-approved-answer-portal")

                    self.action(staff, "composite_open")
                    with staff.expect_download() as download:
                        staff.get_by_role(
                            "button", name="تنزيل طلب إذن جميع الأجزاء", exact=True
                        ).click()
                    prepared = json.loads(Path(download.value.path()).read_text())
                    self.assertEqual(prepared["origin_channel"], "telegram")
                    self.assertEqual(len(prepared["parts"]), 2)
                    staff.locator("#return-permission").fill(
                        json.dumps(
                            {
                                "request_sha256": prepared["plan_sha256"],
                                "receipt": asdict(signer.receipt(prepared)),
                            }
                        )
                    )
                    staff.locator(
                        'form:has(input[value="composite_stage"]) input[name="confirm"]'
                    ).check()
                    self.click(staff, "تسجيل خطة الأجزاء الموقّعة")
                    worker = dict(
                        **common,
                        worker_id="synthetic-worker",
                        verify_worker=lambda worker, _: worker == "synthetic-worker",
                        verify_receipt=signer.approval_verifier,
                    )

                    def reserve_and_resolve():
                        lease = composite.reserve_composite_part(**worker)
                        part = composite.resolve_composite_part(
                            **common, lease=lease, verify_receipt=signer.approval_verifier
                        )
                        return lease, part

                    def receipt_bundle(lease, part, reported):
                        event = simulator.event(lease=lease, part=part, reported=reported)
                        return json.dumps(
                            {
                                "schema": "fatwa.composite-provider-evidence.v1",
                                "part_id": part["id"],
                                "lease": {
                                    **asdict(lease),
                                    "expires_at": lease.expires_at.isoformat(),
                                },
                                "event": asdict(event),
                            }
                        )

                    first, first_part = self.sync(reserve_and_resolve)
                    accepted = self.sync(lambda: receipt_bundle(first, first_part, "ACCEPTED"))
                    delivered = self.sync(lambda: receipt_bundle(first, first_part, "DELIVERED"))
                    self.click(staff, "تحديث متابعة الأجزاء")
                    self.import_provider_receipt(staff, 1, accepted)
                    self.assertIn("قبول المزود فقط", staff.locator("#part-1").inner_text())
                    self.import_provider_receipt(staff, 1, delivered)
                    second, second_part = self.sync(reserve_and_resolve)
                    late = self.sync(lambda: receipt_bundle(second, second_part, "DELIVERED"))
                    staff.locator(
                        'form:has(input[value="composite_reconcile"]) input[name="confirm"]'
                    ).check()
                    with patch(
                        "apps.delivery_queue.services.timezone.now",
                        return_value=timezone.now() + timedelta(minutes=2),
                    ):
                        self.click(staff, "مطابقة المحاولات المنتهية")
                    self.assertIn("نتيجة غير محسومة", staff.locator("#part-2").inner_text())
                    requester.reload(wait_until="domcontentloaded")
                    self.assertEqual(
                        requester.locator("[data-delivery-state]").get_attribute(
                            "data-delivery-state"
                        ),
                        "UNRESOLVED",
                    )
                    self.assertEqual(requester.locator("#authorized-answer").inner_text(), DRAFT)
                    self.capture(staff, "partial-unresolved-control")
                    self.capture(requester, "available-answer-unresolved-delivery")
                    self.import_provider_receipt(staff, 2, late)
                    self.assertIn("اكتمل تقرير التسليم الموقّع", staff.locator("main").inner_text())
                    requester.reload(wait_until="domcontentloaded")
                    self.assertEqual(
                        requester.locator("[data-delivery-state]").get_attribute(
                            "data-delivery-state"
                        ),
                        "SIGNED_DELIVERED",
                    )
                    self.assertIn("لا يثبت قراءة", requester.locator("#delivery").inner_text())
                    self.assertIsNone(self.sync(lambda: composite.reserve_composite_part(**worker)))

                    self.action(staff, "pub_open")
                    staff.locator("#publication-title").fill("عنوان V10 اصطناعي")
                    staff.locator("#publication-category").fill("تصنيف تجربة")
                    staff.locator("#publication-body").fill(PUBLIC_TEXT)
                    self.click(staff, "حفظ نسخة مرشحة جديدة")
                    staff.locator(
                        'form:has(input[value="pub_review"]) input[name="confirm"]'
                    ).check()
                    self.click(staff, "تسجيل مراجعة التحرير والخصوصية")
                    login(reviewer, "P" * 64)
                    self.click(reviewer, source.public_ref)
                    self.action(reviewer, "pub_open")
                    reviewer.locator(
                        'form:has(input[value="pub_approve"]) input[name="confirm"]'
                    ).check()
                    self.click(reviewer, "موافقة نشر مستقلة")
                    publication = self.sync(
                        lambda: PublicationEdition.objects.get(case_id=source.case_id)
                    )

                    # Explicit reviewed relationships use unchanged canonical V9 services.
                    def reviewed_links():
                        args = dict(
                            publication_id=str(publication.pk),
                            subject_id="synthetic-mufti",
                            provider=directory,
                            synthetic_fixtures_only=True,
                        )
                        for kind, target in (
                            ("REFERENCE", heading_id),
                            ("TRANSCRIPT", transcript["link_id"]),
                        ):
                            proposed = knowledge.propose(
                                **args, kind=kind, target_id=target, reason=PRIVATE_NOTE
                            )
                            knowledge.act(
                                **{**args, "subject_id": "synthetic-publisher"},
                                revision_id=proposed["id"],
                                action="APPROVE",
                                confirmed=True,
                            )
                        return publication.citations[0]["source_sha256"]

                    reference_hash = self.sync(reviewed_links)
                    policy = PreviewPolicy(
                        (PublicationGrant(str(publication.pk), publication.content_sha256),),
                        (ReferenceGrant(edition_id, 2, reference_hash),),
                        timezone.now() + timedelta(minutes=30),
                        True,
                    )
                    with override_settings(FATWA_LIBRARY_PREVIEW_POLICY=policy):
                        self.preview_library(
                            browser,
                            title=publication.title,
                            category=publication.category,
                            private_values=(
                                source.public_ref,
                                source.token,
                                QUESTION,
                                AMBIGUOUS,
                                DRAFT,
                                PRIVATE_NOTE,
                                transcript_text,
                            ),
                        )
                    canonical = self.sync(lambda: canonical_evidence(source.case_id, storage_root))
                    self.assertEqual(
                        canonical["counts"],
                        {
                            "cases": 1,
                            "source_bindings": 2,
                            "evidence": 4,
                            "evidence_version": 4,
                            "transcripts": 1,
                            "answer_revisions": 2,
                            "citations": 1,
                            "parts": 2,
                            "private_releases": 1,
                            "same_publication_answer": True,
                            "same_delivery_answer": True,
                            "delivery_intents": 2,
                            "knowledge_links": 2,
                            "knowledge_approvals": 2,
                            "external_objects": 2,
                            "attachment_external": True,
                            "audio_external": True,
                        },
                    )
                    browser_version = browser.version
                    self.assertEqual(self.external, [])
                    self.assertEqual(self.errors, [])
                finally:
                    browser.close()

            # All application/browser writers are stopped before the explicit offline boundary.
            self.server_thread.terminate()
            self.assertFalse(self.server_thread.is_alive())
            from apps.platform_recovery.service import restore, snapshot, verify_bundle

            pg_bin = os.environ.get("FATWA_RECOVERY_PG_BIN")
            if not pg_bin:
                pg_dump = shutil.which("pg_dump")
                self.assertIsNotNone(
                    pg_dump, "set FATWA_RECOVERY_PG_BIN to the matched PostgreSQL clients"
                )
                pg_bin = str(Path(pg_dump).parent)
            source_database = connection.settings_dict["NAME"]
            with TemporaryDirectory(prefix="v10-recovery-") as scratch:
                backup = snapshot(
                    scratch=scratch,
                    storage=storage,
                    pg_bin=pg_bin,
                    synthetic_fixtures_only=True,
                    offline=True,
                )
                manifest_pin = backup["manifest_sha256"]
                verify_bundle(backup["bundle"], manifest_pin)
                restored = restore(
                    bundle=backup["bundle"],
                    expected_manifest_sha256=manifest_pin,
                    scratch=scratch,
                    pg_bin=pg_bin,
                    synthetic_fixtures_only=True,
                    offline=True,
                )
                self.assertEqual(restored["state"], "READY")
                self.assertNotEqual(restored["database"], source_database)
                specification = {
                    **restored,
                    "source_database": source_database,
                    "source_private_root": storage_root,
                    "token": source.token,
                    "public_ref": source.public_ref,
                    "expected": canonical,
                    # Explicit test trust reattachment, never private signing keys or SQL grants.
                    "approval_public_key": signer.approval_key.public_key()
                    .public_bytes_raw()
                    .hex(),
                    "provider_public_key": simulator.verifier._keys["ephemeral-fixture"]
                    .public_bytes_raw()
                    .hex(),
                }
                process = subprocess.run(
                    [
                        sys.executable,
                        "-c",
                        "import django; django.setup(); from tests.casework.v10_fixtures import verify_restored; verify_restored()",
                    ],
                    input=json.dumps(specification),
                    text=True,
                    capture_output=True,
                    timeout=120,
                    env={
                        **os.environ,
                        "PGDATABASE": restored["database"],
                        "PGTESTDATABASE": "test_" + restored["database"],
                    },
                )
                self.assertEqual(process.returncode, 0, process.stderr)
                self.assertIn(
                    "V10_RESTORED_IDENTITIES_BYTES_LINKS_AND_DENIALS_PASS", process.stdout
                )
                self.assertIn("V10_RESTORED_HTTP_BROWSER_PASS", process.stdout)
                self.assertEqual(canonical_evidence(source.case_id, storage_root), canonical)
                (OUT / "result.json").write_text(
                    json.dumps(
                        {
                            "status": "PASS",
                            "browser": browser_version,
                            "sandbox": sandbox,
                            "widths": [320, 1280],
                            "external_requests": self.external,
                            "page_errors": self.errors,
                            "canonical": canonical["counts"],
                            "recovery": {
                                "state": restored["state"],
                                "new_database": True,
                                "new_private_root": True,
                                "fresh_process_services": "PASS",
                                "source_unchanged": True,
                                "restored_browser": "PASS",
                                "manifest_sha256": manifest_pin,
                            },
                        },
                        ensure_ascii=False,
                        indent=2,
                    )
                )
