"""Actual isolated browser media journey; all documents and sound are synthetic."""

import json
import os
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from hashlib import sha256
from pathlib import Path
from urllib.parse import urlsplit

from django.db import close_old_connections, connections
from django.test import LiveServerTestCase, override_settings

from apps.answer_media.models import AnswerManifest, AnswerPart, PrivateAnswerRelease
from apps.case_attachments.models import CaseAttachment
from apps.case_citations.models import AnswerCitation
from apps.casework.models import AnswerRevision, Case
from apps.delivery_queue.models import DeliveryIntent
from apps.private_media.fixtures import synthetic_files
from apps.reference.ingest import ingest_catalog
from tests.casework.test_http import WEB_SETTINGS, Directory
from tests.reference.test_catalog import fixture

OUT = Path(".local/qa/v8/browser")
DRAFT = "مسودة بشرية اصطناعية تحافظ على النص أثناء بحث مرجعين.\nهذا ليس حكمًا شرعيًا."
PRIVATE_NOTE = "تعليق تحريري داخلي اصطناعي لا يظهر للسائل."
QUESTION = "سؤال اصطناعي لتجربة الملفات والجواب متعدد الأجزاء."


@override_settings(
    **{
        **WEB_SETTINGS,
        "ROOT_URLCONF": "config.campaign_urls",
        "FATWA_CASE_ATTACHMENTS_ENABLED": True,
        "FATWA_CASE_CITATIONS_ENABLED": True,
        "FATWA_ANSWER_MEDIA_ENABLED": True,
        "FATWA_ANSWER_MEDIA_PRIVATE_ENABLED": True,
        "FATWA_CASEWORK_PRIVATE_ANSWER_ENABLED": False,
    }
)
class V8MediaBrowserTests(LiveServerTestCase):
    host = "127.0.0.1"

    def sync(self, callback):
        def call():
            close_old_connections()
            try:
                return callback()
            finally:
                connections.close_all()

        with ThreadPoolExecutor(max_workers=1) as pool:
            return pool.submit(call).result(timeout=30)

    def click(self, page, name):
        with page.expect_navigation(wait_until="domcontentloaded") as navigation:
            page.get_by_role("button", name=name, exact=True).click()
        self.assertEqual(navigation.value.status, 200)
        self.assertIn("no-store", navigation.value.headers.get("cache-control", ""))

    def capture(self, page, name):
        for width in (320, 1280):
            page.set_viewport_size({"width": width, "height": 900})
            page.wait_for_load_state("networkidle")
            page.evaluate(
                "async () => { await document.fonts.ready; await new Promise(r=>requestAnimationFrame(()=>requestAnimationFrame(r))); }"
            )
            self.assertEqual(page.locator("html").get_attribute("dir"), "rtl")
            measured = page.evaluate("document.documentElement.scrollWidth")
            if measured > width:
                overflow = page.locator("body *").evaluate_all("""elements => elements.map(el => {
                    const r=el.getBoundingClientRect(); return {tag:el.tagName,id:el.id,
                    left:r.left,right:r.right,width:r.width,text:el.textContent.slice(0,100)};
                }).filter(r=>r.left<0 || r.right>innerWidth)""")
                (OUT / "overflow.json").write_text(
                    json.dumps(overflow, ensure_ascii=False, indent=2)
                )
                page.screenshot(path=str(OUT / "overflow.png"), full_page=True)
            self.assertLessEqual(measured, width)
            page.screenshot(path=str(OUT / f"{name}-{width}.png"), full_page=True)

    def play(self, audio):
        audio.wait_for(state="visible")
        audio.evaluate("el => el.load()")
        audio.page.wait_for_function(
            "el => el.readyState >= 1 && Number.isFinite(el.duration) && el.duration > 0",
            arg=audio.element_handle(),
        )
        result = audio.evaluate("""async el => {
            let played=false;
            el.addEventListener('playing',()=>{played=true},{once:true});
            await el.play();
            const result={duration:el.duration,played,readyState:el.readyState};
            el.pause(); return result;
        }""")
        self.assertTrue(result["played"])
        self.assertGreater(result["duration"], 0)
        return result

    def test_private_files_two_citations_and_whole_answer_release_invalidate_together(self):
        from playwright.sync_api import sync_playwright

        files = {name: (mime, raw) for name, mime, raw in synthetic_files()}
        spec, rows = fixture()
        spec = replace(spec, source_book_id="622")
        preview = ingest_catalog(spec, rows)
        edition = ingest_catalog(
            spec, rows, dry_run=False, expected_checksum=preview.checksum
        ).edition_id
        directory = Directory()
        errors, external, pdf_responses, browser_resources = [], [], [], []
        audio_evidence = {}
        OUT.mkdir(parents=True, exist_ok=True)
        with override_settings(FATWA_CASEWORK_IDENTITY_PROVIDER=directory), sync_playwright() as p:
            sandbox = os.environ.get("FATWA_BROWSER_SANDBOX", "1") != "0"
            browser = p.chromium.launch(
                executable_path=os.environ.get("FATWA_FASTBUILD_BROWSER", "/usr/bin/chromium"),
                headless=True,
                chromium_sandbox=sandbox,
                args=["--disable-dev-shm-usage"],
            )
            try:
                contexts = [
                    browser.new_context(viewport={"width": 1280, "height": 900}) for _ in range(3)
                ]
                for context in contexts:

                    def route(r):
                        parsed = urlsplit(r.request.url)
                        if (
                            parsed.scheme == "chrome-extension"
                            and parsed.netloc == "mhjfbmdgcfjbbpaeojofohoefgiehjai"
                        ) or (parsed.scheme == "chrome" and parsed.netloc == "resources"):
                            browser_resources.append(r.request.url)
                            r.continue_()
                        elif parsed.netloc != urlsplit(self.live_server_url).netloc:
                            external.append(r.request.url)
                            r.abort()
                        else:
                            r.continue_()

                    context.route("**/*", route)
                requester, staff, foreign = [context.new_page() for context in contexts]
                for page in (requester, staff, foreign):
                    page.on("pageerror", lambda error: errors.append(str(error)))
                    page.on(
                        "response",
                        lambda response: (
                            pdf_responses.append(response)
                            if response.headers.get("content-type", "").startswith(
                                "application/pdf"
                            )
                            else None
                        ),
                    )

                def intake(page, question):
                    page.goto(self.live_server_url + "/casework/")
                    page.locator("#question").fill(question)
                    self.click(page, "حفظ السؤال")
                    ref = page.locator("#public-reference").inner_text()
                    token = page.locator("#issued-token").inner_text()
                    page.get_by_role("link", name="متابعة هذا السؤال", exact=True).click()
                    return ref, token

                public_ref, token = intake(requester, QUESTION)
                foreign_ref, _ = intake(foreign, "سؤال اصطناعي مستقل لسائل آخر.")
                directory.grant(public_ref)
                self.click(requester, "مرفقات سؤالي")
                attachment_urls = []
                for name in ("synthetic.png", "synthetic.pdf", "synthetic.wav"):
                    mime, raw = files[name]
                    requester.locator('input[name="attachment"]').set_input_files(
                        {
                            "name": name,
                            "mimeType": mime,
                            "buffer": raw,
                        }
                    )
                    requester.locator('input[name="synthetic_only"]').check()
                    self.click(requester, "حفظ الأصل وإضافة الوقائع")
                    form = requester.locator("section").filter(
                        has=requester.get_by_role("heading", name=name, exact=True)
                    )
                    item_id = form.locator('input[name="attachment_id"]').input_value()
                    attachment_urls.append(f"/casework/status/attachments/{item_id}/")
                    self.assertIn(name, requester.content())
                for url in attachment_urls:
                    denied = foreign.request.get(self.live_server_url + url)
                    self.assertEqual(denied.status, 404)
                    self.assertNotIn(public_ref, denied.text())

                staff.goto(self.live_server_url + "/casework/staff/login/")
                staff.locator("#credential").fill(directory.credential)
                self.click(staff, "دخول المكتب")
                self.click(staff, public_ref)
                self.click(staff, "مرفقات القضية")
                self.click(staff, "معاينة synthetic.png")
                image = staff.locator('img[src*="/attachments/"]')
                staff.wait_for_function(
                    "img => img.complete && img.naturalWidth > 0", arg=image.element_handle()
                )
                self.assertEqual(
                    image.evaluate("img => [img.naturalWidth,img.naturalHeight]"), [16, 12]
                )
                self.capture(staff, "staff-image")
                self.click(staff, "معاينة synthetic.pdf")
                iframe = staff.locator('iframe[title="معاينة PDF الخاصة"]')
                pdf_url = iframe.get_attribute("src")
                self.assertIsNotNone(iframe.get_attribute("sandbox"))
                pdf = staff.request.get(self.live_server_url + pdf_url)
                self.assertEqual(pdf.status, 200)
                self.assertEqual(pdf.body(), files["synthetic.pdf"][1])
                self.assertTrue(pdf.headers["content-disposition"].startswith("inline"))
                self.assertEqual(pdf.headers["content-type"], "application/pdf")
                staff.wait_for_timeout(100)
                self.assertTrue(
                    any(urlsplit(r.url).path == pdf_url and r.status == 200 for r in pdf_responses)
                )
                self.capture(staff, "staff-pdf-inline-response")
                self.click(staff, "معاينة synthetic.wav")
                audio_evidence["staff_attachment"] = self.play(staff.locator("audio"))
                self.capture(staff, "staff-audio")
                self.click(staff, "العودة إلى القضية")

                self.click(staff, "تحرير جواب بإحالة موثقة")
                staff.locator("#answer").fill(DRAFT)
                staff.locator("#edition").select_option(str(edition))
                staff.locator("#part").fill("مقدمة")
                for position in (2, 3):
                    staff.locator("#page").fill(str(position))
                    self.click(staff, "البحث مع الاحتفاظ بالمسودة")
                    self.assertEqual(staff.locator("#answer").input_value(), DRAFT)
                    staff.locator("#note").fill(PRIVATE_NOTE + str(position))
                    self.click(staff, f"إضافة الموضع {position} إلى القائمة")
                    self.assertEqual(staff.locator("#answer").input_value(), DRAFT)
                self.assertIn("(2/12)", staff.content())
                self.capture(staff, "two-reference-draft")
                staff.locator('input[name="confirm"]').check()
                self.click(staff, "حفظ الجواب والقائمة الكاملة")
                self.click(staff, "العودة إلى القضية دون حفظ هذه المسودة")
                self.click(staff, "تحرير جواب متعدد الأجزاء")
                for name in ("synthetic.pdf", "synthetic.wav"):
                    self.assertEqual(staff.locator("#multipart-text").input_value(), DRAFT)
                    mime, raw = files[name]
                    staff.locator("#answer-file").set_input_files(
                        {"name": name, "mimeType": mime, "buffer": raw}
                    )
                    staff.locator("#retain-parts").select_option("yes")
                    staff.locator('input[name="synthetic_only"]').check()
                    self.click(staff, "حفظ إصدار متعدد الأجزاء")
                self.capture(staff, "multipart-draft")
                requester.goto(self.live_server_url + "/casework/status/")
                self.assertNotIn(DRAFT, requester.content())
                self.assertNotIn(PRIVATE_NOTE, requester.content())
                latest = staff.locator("article").first
                private_urls = [
                    url.replace("/staff/", "/status/")
                    for url in latest.locator("a[download]").evaluate_all(
                        "xs => xs.map(x=>x.getAttribute('href'))"
                    )
                ]
                self.assertEqual(len(private_urls), 2)
                for url in private_urls:
                    self.assertEqual(requester.request.get(self.live_server_url + url).status, 404)
                self.click(staff, "العودة إلى القضية والاعتماد")
                self.click(staff, "اعتماد هذه النسخة")
                for url in private_urls:
                    self.assertEqual(requester.request.get(self.live_server_url + url).status, 404)
                self.click(staff, "تحرير جواب متعدد الأجزاء")
                staff.locator(
                    'form:has(input[value="answer_media_release"]) input[name="confirm"]'
                ).check()
                self.click(staff, "إتاحة النسخة المعتمدة للسائل تجريبيًا")
                self.assertIn("لا يعني ذلك تسليم مزود القناة", staff.content())
                requester.goto(self.live_server_url + "/casework/status/")
                self.click(requester, "أجزاء الجواب المتاحة خصوصيًا")
                self.assertIn(DRAFT, requester.content())
                self.assertNotIn(PRIVATE_NOTE, requester.content())
                self.assertNotIn(token, requester.content())
                self.assertNotIn(foreign_ref, requester.content())
                self.assertIn("ليس إثبات تسليم", requester.content())
                audio_evidence["requester_answer"] = self.play(requester.locator("audio"))
                self.assertEqual(requester.locator("iframe").count(), 1)
                for url, name in zip(private_urls, ("synthetic.pdf", "synthetic.wav"), strict=True):
                    response = requester.request.get(self.live_server_url + url)
                    self.assertEqual(response.status, 200)
                    self.assertEqual(response.body(), files[name][1])
                    self.assertIn("no-store", response.headers["cache-control"])
                    self.assertEqual(foreign.request.get(self.live_server_url + url).status, 404)
                self.capture(requester, "released-package")

                def canonical():
                    case = Case.objects.get(public_ref=public_ref)
                    manifest = AnswerManifest.objects.get(answer=case.approved_answer)
                    release = PrivateAnswerRelease.objects.get(manifest=manifest)
                    return {
                        "answer_revisions": AnswerRevision.objects.filter(case=case).count(),
                        "citation_count": AnswerCitation.objects.filter(
                            answer=case.approved_answer
                        ).count(),
                        "manifest_part_count": manifest.part_count,
                        "part_kinds": list(
                            AnswerPart.objects.filter(manifest=manifest)
                            .order_by("ordinal")
                            .values_list("kind", flat=True)
                        ),
                        "attachments": CaseAttachment.objects.filter(case=case).count(),
                        "evidence_version": case.evidence_version,
                        "release_matches_manifest": release.manifest_sha256 == manifest.sha256,
                        "provider_intents": DeliveryIntent.objects.count(),
                    }

                evidence = self.sync(canonical)
                self.assertEqual(
                    evidence,
                    {
                        "answer_revisions": 3,
                        "citation_count": 2,
                        "manifest_part_count": 3,
                        "part_kinds": ["TEXT", "FILE", "AUDIO"],
                        "attachments": 3,
                        "evidence_version": 4,
                        "release_matches_manifest": True,
                        "provider_intents": 0,
                    },
                )
                with requester.expect_navigation(wait_until="domcontentloaded") as returned:
                    return_link = requester.get_by_role(
                        "link", name="العودة إلى متابعة سؤالي", exact=True
                    )
                    return_link.focus()
                    return_link.press("Enter")
                self.assertEqual(returned.value.status, 200, requester.content())
                requester.locator("#workspace-followup").fill(
                    "واقعة اصطناعية جديدة تبطل النسخة المتاحة السابقة."
                )
                self.click(requester, "حفظ التعقيب")
                self.assertNotIn(DRAFT, requester.content())
                for url in private_urls:
                    self.assertEqual(requester.request.get(self.live_server_url + url).status, 404)
                self.assertTrue(
                    self.sync(
                        lambda: Case.objects.get(public_ref=public_ref).approved_answer_id is None
                    )
                )
                (OUT / "network.json").write_text(json.dumps(external, indent=2))
                self.assertEqual(external, [])
                self.assertEqual(errors, [])
                result = {
                    "status": "PASS",
                    "browser": browser.version,
                    "sandbox": sandbox,
                    "widths": [320, 1280],
                    "image_dimensions": [16, 12],
                    "pdf_inline_status": 200,
                    "pdf_sha256": sha256(files["synthetic.pdf"][1]).hexdigest(),
                    "pdf_visual_rasterization": "NOT_ASSERTED",
                    "audio_play": audio_evidence,
                    "foreign_file_status": 404,
                    "stale_private_file_status": 404,
                    "external_requests": 0,
                    "native_browser_resources": len(browser_resources),
                    "page_errors": 0,
                    "canonical": evidence,
                }
                (OUT / "result.json").write_text(
                    json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8"
                )
                print(
                    f"V8 browser PASS: Chromium {browser.version}, sandbox={sandbox}, real image/audio/PDF responses, "
                    "two citations retained, whole package approved/released, foreign/stale media denied."
                )
            finally:
                browser.close()
