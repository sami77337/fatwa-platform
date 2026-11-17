"""One V11 human-operated journey and encrypted recovery, with no inherited V10 test."""

import json
import os
import shutil
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from pathlib import Path
from tempfile import TemporaryDirectory
from threading import Event

from django.db import connection
from django.test import LiveServerTestCase, override_settings
from django.utils import timezone

from apps.casework import services as cases
from apps.composite_delivery import services as composite
from apps.delivery_planner.planner import Capabilities
from apps.experimental_publication.models import PublicationEdition
from apps.library_preview.policy import PreviewPolicy, PublicationGrant, ReferenceGrant
from apps.pilot_workbench.fixtures import setup_synthetic_fixture
from apps.platform_recovery import encrypted, maintenance
from apps.platform_recovery.service import RecoveryError
from apps.private_media.filesystem import FileSystemStorage
from apps.private_media.fixtures import synthetic_files
from apps.research_workspace.source_rights_adapter import SourceRightsAdapter
from tests.casework.test_http import WEB_SETTINGS
from tests.casework.test_v7_browser import BrowserPublicationAuthority
from tests.casework.test_v9_browser import KnowledgePolicy
from tests.casework.test_v10_browser import BrowserHarness
from tests.casework.v11_fixtures import (
    DRAFT,
    OUT,
    PRIVATE,
    PUBLIC,
    QUESTION,
    REPLY,
    Directory,
    OperatorAuthority,
    RightsAuthority,
    bootstrap,
    inventory,
)

FEATURES = {
    **{k: v for k, v in WEB_SETTINGS.items() if k != "MIDDLEWARE"},
    "ROOT_URLCONF": "config.campaign_urls",
    **{
        key: True
        for key in (
            "FATWA_MUFTI_WORKSPACE_ENABLED",
            "FATWA_REQUESTER_PORTAL_ENABLED",
            "FATWA_SOURCE_CASE_INTAKE_ENABLED",
            "FATWA_SOURCE_CASE_INTAKE_DESK_ENABLED",
            "FATWA_SOURCE_CASE_INTAKE_SIMULATOR_ENABLED",
            "FATWA_CASE_ATTACHMENTS_ENABLED",
            "FATWA_CASE_CITATIONS_ENABLED",
            "FATWA_ANSWER_MEDIA_ENABLED",
            "FATWA_ANSWER_MEDIA_PRIVATE_ENABLED",
            "FATWA_COMPOSITE_DELIVERY_ENABLED",
            "FATWA_EXPERIMENTAL_PUBLICATION_ENABLED",
            "FATWA_KNOWLEDGE_LINKS_ENABLED",
            "FATWA_LIBRARY_PREVIEW_ENABLED",
            "FATWA_SOURCE_RIGHTS_ENABLED",
            "FATWA_SOURCE_RIGHTS_ENFORCED",
            "FATWA_RESEARCH_WORKSPACE_ENABLED",
        )
    },
}


class V11Harness(BrowserHarness):
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

    def login(self, page, credential):
        page.goto(self.live_server_url + "/casework/staff/login/")
        page.locator("#credential").fill(credential)
        self.click(page, "دخول المكتب")

    def open_case(self, page, ref):
        page.goto(self.live_server_url + "/casework/staff/")
        self.click(page, ref)
        self.assert_case_header(page, ref)

    def form(self, page, action):
        return page.locator(f'form:has([name="action"][value="{action}"])').first

    def submit_form(self, page, action):
        return self.submit(page, self.form(page, action).get_by_role("button"))

    def review_source(self, staff, source):
        self.action(staff, "source_inbox")
        staff.locator("#source-query").fill(source["public_ref"])
        self.click(staff, "تصفية الأحداث")
        self.click(staff, "فتح الحدث 1 من telegram")
        staff.locator('#source-simulator [name="confirm"]').check()
        self.click(staff, "استقبال الحدث الاصطناعي")
        for kind in ("HOLD", "REOPEN"):
            staff.locator("#note-kind").select_option(kind)
            staff.locator("#review-note").fill(PRIVATE + kind)
            staff.locator('#source-note [name="confirm"]').check()
            self.click(staff, "حفظ المتابعة البشرية")
            self.assertEqual(staff.locator("#followup-form").count(), int(kind == "REOPEN"))
        staff.locator("#followup-token").fill(source["token"])
        staff.locator("#followup-note").fill(PRIVATE)
        staff.locator('#followup-form [name="confirm"]').check()
        self.click(staff, "تأكيد إلحاق التعقيب")
        self.click(staff, "العودة إلى نتائج البحث")
        self.assertEqual(staff.locator("#source-query").input_value(), source["public_ref"])
        self.capture(staff, "held-source-reviewed")

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
        picture.evaluate("img=>img.decode()")
        self.assertGreater(picture.evaluate("img=>img.naturalWidth"), 0)
        self.assertNotIn(PRIVATE, requester.content())
        self.capture(requester, "atomic-clarification-reply")
        self.open_case(staff, source["public_ref"])
        before = self.sync(lambda: cases.read_case(**self.common)["revision"])
        self.submit(staff, staff.locator("#mufti-next-action"))
        self.assertEqual(self.sync(lambda: cases.read_case(**self.common)["revision"]), before)
        staff.locator("#answer-text").fill(DRAFT)
        self.click(staff, "حفظ مسودة الجواب")

    def rights_review(self, staff, reviewer, source, edition):
        self.action(staff, "rights_desk")
        staff.locator("#rights-edition").select_option(str(edition))
        staff.locator("#rights-query").fill("فرع")
        self.click(staff, "بحث المصادر الحالية")
        self.submit_form(staff, "rights_register")
        proposal = self.form(staff, "rights_propose")
        for usage in ("READ", "CITE", "RELATE", "PREVIEW_METADATA"):
            proposal.locator(f'[name="uses"][value="{usage}"]').check()
        proposal.locator('[name="basis"]').fill("مستند إذن اصطناعي راجعه إنسان لهذه النسخة فقط.")
        proposal.locator('[name="note"]').fill(PRIVATE)
        self.submit_form(staff, "rights_propose")
        self.assertIn("PENDING", staff.content())
        self.login(reviewer, "P" * 64)
        self.click(reviewer, source["public_ref"])
        self.action(reviewer, "rights_desk")
        form = self.form(reviewer, "rights_review")
        form.locator('[name="note"]').fill(PRIVATE + " مراجعة مستقلة")
        form.locator('[name="confirm"]').check()
        self.submit_form(reviewer, "rights_review")
        self.assertIn("ALLOWED", reviewer.content())
        self.capture(reviewer, "independent-source-rights")
        self.click(staff, "العودة إلى القضية")

    def research_and_parts(self, staff, source, edition, files):
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
        self.capture(staff, "research-canonical-citation")
        self.click(staff, "العودة إلى القضية")
        self.action(staff, "answer_media")
        for name in ("synthetic.wav", "synthetic.txt"):
            self.assertEqual(staff.locator("#multipart-text").input_value(), DRAFT)
            mime, raw = files[name]
            staff.locator("#answer-file").set_input_files(
                {"name": name, "mimeType": mime, "buffer": raw}
            )
            self.form(staff, "answer_media_save").locator('[name="synthetic_only"]').check()
            self.click(staff, "حفظ إصدار متعدد الأجزاء")
        # Real selects reorder the two existing immutable file identities, then exclude TXT.
        staff.locator("#answer-part-order summary").click()
        audio_id = staff.locator("#part-order-2").input_value()
        text_id = staff.locator("#part-order-3").input_value()
        staff.locator("#part-order-2").select_option(text_id)
        staff.locator("#part-order-3").select_option(audio_id)
        self.click(staff, "حفظ ترتيب الأجزاء في نسخة جديدة")
        staff.locator("#answer-part-order summary").click()
        staff.locator("#part-order-2").select_option("")
        self.click(staff, "حفظ ترتيب الأجزاء في نسخة جديدة")
        self.action(staff, "case_workspace")
        self.assert_case_header(staff, source["public_ref"])
        self.assertEqual(staff.locator("#mufti-answer-revision").inner_text(), "6")
        self.click(staff, "اعتماد هذه النسخة")
        self.submit(staff, staff.locator("#mufti-next-action"))
        self.form(staff, "answer_media_release").locator('[name="confirm"]').check()
        self.click(staff, "إتاحة النسخة المعتمدة للسائل تجريبيًا")
        self.capture(staff, "reordered-approved-package")

    def pilot_reports(self, staff, requester):
        self.action(staff, "pilot_open")
        self.form(staff, "pilot_authorize").locator('[name="confirm"]').check()
        self.click(staff, "تأكيد إذن الإرجاع التجريبي")
        for outcome in ("ACCEPTED", "DELIVERED", "DELIVERED"):
            form = self.form(staff, "pilot_report")
            form.locator('[name="outcome"]').select_option(outcome)
            form.locator('[name="confirm"]').check()
            self.submit_form(staff, "pilot_report")
            requester.reload(wait_until="domcontentloaded")
            self.assertEqual(requester.locator("#authorized-answer").inner_text(), DRAFT)
            state = requester.locator("[data-delivery-state]").get_attribute("data-delivery-state")
            if outcome == "ACCEPTED":
                self.assertEqual(state, "PROVIDER_ACCEPTED")
        self.assertEqual(state, "SIGNED_DELIVERED")
        self.assertIn("لا يوجد إثبات قراءة", staff.content())
        audio = requester.locator("#answer audio")
        audio.evaluate("async e=>{await e.play();}")
        self.assertGreater(audio.evaluate("e=>e.duration"), 0)
        self.assertNotIn(PRIVATE, requester.content())
        self.capture(requester, "requester-current-signed-package")
        self.capture(staff, "human-pilot-reports")

    def publish_and_relate(self, staff, reviewer, edition):
        self.action(staff, "pub_open")
        staff.locator("#publication-title").fill("عنوان V11 اصطناعي")
        staff.locator("#publication-category").fill("تجربة مغلقة")
        staff.locator("#publication-body").fill(PUBLIC)
        self.click(staff, "حفظ نسخة مرشحة جديدة")
        self.form(staff, "pub_review").locator('[name="confirm"]').check()
        self.click(staff, "تسجيل مراجعة التحرير والخصوصية")
        self.open_case(reviewer, self.source["public_ref"])
        self.action(reviewer, "pub_open")
        self.form(reviewer, "pub_approve").locator('[name="confirm"]').check()
        self.click(reviewer, "موافقة نشر مستقلة")
        self.action(staff, "rights_desk")
        staff.locator("#rights-edition").select_option(str(edition))
        staff.locator("#rights-query").fill("فرع")
        self.click(staff, "بحث المصادر الحالية")
        self.form(staff, "rights_relation_propose").locator('[name="note"]').fill(PRIVATE)
        self.submit_form(staff, "rights_relation_propose")
        self.action(reviewer, "rights_desk")
        self.form(reviewer, "rights_relation_action").locator('[name="confirm"]').check()
        self.submit_form(reviewer, "rights_relation_action")
        publication = self.sync(
            lambda: PublicationEdition.objects.get(case_id=self.source["case_id"])
        )
        return PreviewPolicy(
            (PublicationGrant(str(publication.pk), publication.content_sha256),),
            (ReferenceGrant(edition, 2, publication.citations[0]["source_sha256"]),),
            timezone.now() + timedelta(minutes=30),
            True,
        )

    def anonymous_preview(self, browser):
        context = self.context(browser)
        try:
            page = context.new_page()
            page.goto(self.live_server_url + "/library-preview/")
            self.submit(page, page.get_by_role("link", name="عنوان V11 اصطناعي", exact=True))
            for secret in (
                QUESTION,
                REPLY,
                DRAFT,
                PRIVATE,
                self.source["token"],
                self.source["public_ref"],
            ):
                self.assertNotIn(secret, page.content())
            self.submit(page, page.get_by_role("link", name="علاقة موثقة: فَرْعٌ تَجْرِيبِيّ", exact=True))
            self.assertIn("الجزء والصفحة المطبوعة", page.content())
            self.capture(page, "rights-bound-library-source")
            self.submit(
                page, page.get_by_role("link", name="العودة إلى عنوان V11 اصطناعي", exact=True)
            )
            self.assertEqual(context.cookies(), [])
        finally:
            context.close()

    def freeze(self, staff, storage, control):
        admitted, release = Event(), Event()

        def existing_writer():
            with maintenance.mutation_guard(root=control, synthetic_fixtures_only=True):
                admitted.set()
                if not release.wait(timeout=30):
                    raise AssertionError("test-held admission did not drain")

        with ThreadPoolExecutor(max_workers=1) as pool:
            future = pool.submit(lambda: self.sync(existing_writer))
            self.assertTrue(admitted.wait(timeout=15))
            try:
                self.assertEqual(
                    self.sync(
                        lambda: maintenance.enter(root=control, synthetic_fixtures_only=True)
                    )["phase"],
                    "DRAINING",
                )
                csrf = staff.locator('[name="csrfmiddlewaretoken"]').first.input_value()
                denied = staff.request.post(
                    self.live_server_url + "/casework/staff/",
                    form={
                        "csrfmiddlewaretoken": csrf,
                        "action": "case_workspace",
                        "case_ref": self.source["public_ref"],
                    },
                )
                self.assertEqual(denied.status, 503)

                def blocked_writes():
                    with self.assertRaises(RecoveryError):
                        cases.add_followup(
                            token=self.source["token"],
                            text="must not persist",
                            expected_revision=1,
                            synthetic_fixtures_only=True,
                        )
                    with self.assertRaises(RecoveryError):
                        storage.collect_orphans(lambda _: False, grace_seconds=0, dry_run=True)

                self.sync(blocked_writes)
            finally:
                release.set()
            future.result(timeout=15)
        frozen = self.sync(lambda: maintenance.enter(root=control, synthetic_fixtures_only=True))
        self.assertEqual(frozen["phase"], "FROZEN")
        return frozen


@override_settings(**FEATURES)
class V11ConnectedBrowserTests(V11Harness, LiveServerTestCase):
    host = "127.0.0.1"

    def test_human_v11_workflow_to_encrypted_recovery_and_target_http(self):
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
            frozenset({"text/plain", "audio/wav", "image/png"}),
        )
        files = {name: (mime, raw) for name, mime, raw in synthetic_files()}
        with (
            TemporaryDirectory(prefix="v11-source-") as private_root,
            TemporaryDirectory(prefix="v11-control-") as control,
            TemporaryDirectory(prefix="v11-keys-") as keys,
            TemporaryDirectory(prefix="v11-sealed-") as backup_root,
            TemporaryDirectory(prefix="v11-target-") as target_root,
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
                        self.pilot_reports(staff, requester)
                        policy = self.publish_and_relate(staff, reviewer, edition)
                        with override_settings(FATWA_LIBRARY_PREVIEW_POLICY=policy):
                            self.anonymous_preview(browser)
                        expected = self.sync(lambda: inventory(self.source["case_id"]))
                        self.assertEqual(expected["source_review"], ["HOLD", "REOPEN"])
                        self.assertEqual(
                            expected["counts"],
                            {
                                "cases": 1,
                                "evidence": 4,
                                "source_bindings": 2,
                                "answers": 6,
                                "citations": 1,
                                "parts": 2,
                                "attachments": 1,
                                "rights_sources": 1,
                                "rights_revisions": 1,
                                "rights_approvals": 1,
                                "source_review_notes": 2,
                                "delivery_intents": 2,
                                "publication_approvals": 1,
                                "knowledge_links": 1,
                                "knowledge_approvals": 1,
                            },
                        )
                        frozen = self.freeze(staff, storage, control)
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
                restored = encrypted.restore(
                    bundle=sealed["bundle"],
                    expected_ciphertext_sha256=pin,
                    key_file=key_file,
                    scratch=target_root,
                    pg_bin=pg_bin,
                    synthetic_fixtures_only=True,
                )
                self.assertEqual(restored["state"], "READY")
                spec = {
                    **restored,
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
                        "-c",
                        "import django; django.setup(); from tests.casework.v11_restored_browser import verify; verify()",
                    ],
                    input=json.dumps(spec),
                    text=True,
                    capture_output=True,
                    timeout=120,
                    env={
                        **os.environ,
                        "PGDATABASE": restored["database"],
                        "PGTESTDATABASE": "test_" + restored["database"],
                    },
                )
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertIn("V11_RESTORED_HTTP_PASS", result.stdout)
                self.assertEqual(inventory(self.source["case_id"]), expected)
                self.assertEqual(maintenance.status(root=control)["phase"], "FROZEN")
                maintenance.resume(
                    root=control,
                    expected_generation=frozen["generation"],
                    confirmed=True,
                    synthetic_fixtures_only=True,
                )
                (OUT / "result.json").write_text(
                    json.dumps(
                        {
                            "status": "PASS",
                            "browser": browser_version,
                            "sandbox": sandbox,
                            "widths": [320, 1280],
                            "canonical": expected["counts"],
                            "external_requests": self.external,
                            "page_errors": self.errors,
                            "maintenance": {
                                "draining_http": 503,
                                "direct_writer": "DENIED",
                                "gc": "DENIED",
                                "frozen_snapshot": True,
                            },
                            "recovery": {
                                "state": restored["state"],
                                "encrypted_only": True,
                                "separate_key": True,
                                "ciphertext_sha256": pin,
                                "target_http": "PASS",
                                "source_unchanged": True,
                            },
                        },
                        indent=2,
                    )
                )
