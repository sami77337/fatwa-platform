"""One V14 UI-created audio case and independent-target recovery.

Native synthetic decisions are not real human gold review or owner acceptance."""

import base64
import io
import json
import os
import shutil
import subprocess
import sys
import wave
from hashlib import sha256
from pathlib import Path
from tempfile import TemporaryDirectory
from urllib.parse import urlsplit

from django.db import connection
from django.test import LiveServerTestCase, override_settings

from apps.browser_audio.test_browser import OBSERVE
from apps.case_attachments import services as attachments
from apps.case_attachments.models import CaseAttachment
from apps.casework.models import Case
from apps.composite_delivery import services as composite
from apps.delivery_planner.planner import Capabilities
from apps.pilot_workbench.fixtures import setup_synthetic_fixture
from apps.platform_recovery import encrypted, maintenance
from apps.private_media.filesystem import FileSystemStorage
from apps.private_media.validation import validate
from apps.timed_citations.models import TimedCitation
from tests.casework.test_v9_browser import KnowledgePolicy
from tests.casework.test_v11_browser import FEATURES as V11_FEATURES
from tests.casework.test_v12_browser import V12Harness
from tests.casework.v11_fixtures import (
    DRAFT,
    PRIVATE,
    REPLY,
    OperatorAuthority,
    RightsAuthority,
)
from tests.casework.v14_fixtures import (
    APPROVED_TEXT,
    CLASSIFICATION_LABEL,
    CLASSIFICATION_REASON,
    OUT,
    QUESTION,
    TIMED_REASON,
    ClassificationPolicy,
    Directory,
    EvaluationPolicy,
    ExactRecordingRights,
    PublicationPolicy,
    SimulationPolicy,
    bootstrap_catalog,
    inventory,
    synthetic_files,
    write_fake_microphone,
)

FEATURES = {
    **V11_FEATURES,
    "FATWA_BROWSER_AUDIO_ENABLED": True,
    "FATWA_TIMED_CITATIONS_ENABLED": True,
    "FATWA_CLASSIFICATION_REVIEW_ENABLED": True,
    "FATWA_ARABIC_SEARCH_EVAL_ENABLED": True,
    "FATWA_CLASSIFICATION_EDITORIAL_SIMULATION_ENABLED": True,
    "FATWA_PDF_CITATIONS_ENABLED": True,
    "FATWA_ARABIC_SEARCH_REVIEW_ENABLED": True,
}


class V14Harness(V12Harness):
    def context(self, browser):
        context = browser.new_context(viewport={"width": 1280, "height": 900})
        self.browser_contexts = [*getattr(self, "browser_contexts", []), context]
        # Observe our native recorder, not Chromium's opaque PDF viewer frames.
        # Product page errors still remain fatal in every frame/context.
        context.add_init_script(
            "if (location.origin === "
            + json.dumps(self.live_server_url)
            + " && navigator.mediaDevices && navigator.mediaDevices.getUserMedia) {"
            + f"({OBSERVE})();"
            + "}"
        )
        context.on("page", lambda page: page.on("pageerror", lambda e: self.errors.append(str(e))))
        if not hasattr(self, "bundled_pdf_requests"):
            self.bundled_pdf_requests, self.bundled_pdf_origins = [], {}

        def route(request):
            url = urlsplit(request.request.url)
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
            ) or (
                url.scheme == "blob"
                and urlsplit(url.path).scheme == "http"
                and urlsplit(url.path).netloc == urlsplit(self.live_server_url).netloc
            ):
                request.continue_()
            else:
                self.external.append(request.request.url)
                request.abort()

        context.route("**/*", route)
        return context

    def respect_budget_window(self):
        # Native PDF/audio requests must settle before the read-only counter
        # snapshot; otherwise a legitimate in-flight read changes that snapshot.
        for context in getattr(self, "browser_contexts", []):
            for page in context.pages:
                if not page.is_closed():
                    page.wait_for_load_state("networkidle")
        return super().respect_budget_window()

    def capture(self, page, label):
        OUT.mkdir(parents=True, exist_ok=True)
        for width in (320, 1280):
            page.set_viewport_size({"width": width, "height": 900})
            page.wait_for_load_state("networkidle")
            self.assertEqual(page.locator("html").get_attribute("dir"), "rtl")
            self.assertLessEqual(page.evaluate("document.documentElement.scrollWidth"), width)
            page.screenshot(path=str(OUT / f"{label}-{width}.png"), full_page=True)

    def released(self, page):
        page.wait_for_function(
            "() => probe.contexts.every(c=>c.state==='closed') && "
            "probe.streams.every(s=>s.getTracks().every(t=>t.readyState==='ended')) && "
            "probe.nodes.every(n=>n.closed && n.disconnected)"
        )

    def record(self, page, form):
        widget = form.locator("[data-browser-audio]")
        widget.locator("[data-audio-start]").focus()
        widget.locator("[data-audio-start]").press("Enter")
        page.wait_for_function("e=>e.dataset.audioState==='recording'", arg=widget.element_handle())
        page.wait_for_function("e => +e.dataset.audioFrames >= 8000", arg=widget.element_handle())
        live = widget.evaluate(
            "e=>({seconds:+e.querySelector('[data-audio-duration]').textContent,"
            "bytes:+e.querySelector('[data-audio-bytes]').textContent,"
            "progress:e.querySelector('[data-audio-progress]').value})"
        )
        self.assertGreater(live["seconds"], 0)
        self.assertLessEqual(live["bytes"], 160044)
        self.assertAlmostEqual(live["progress"], (live["bytes"] - 44) / 16000)
        widget.locator("[data-audio-stop]").click()
        page.wait_for_function(
            "e => e.dataset.audioState === 'preview'", arg=widget.element_handle()
        )
        self.released(page)
        widget.locator("[data-audio-preview]").evaluate("async e=>{await e.play();}")
        self.assertGreater(widget.locator("[data-audio-preview]").evaluate("e=>e.duration"), 0)
        widget.locator("[data-audio-accept]").click()
        encoded = form.locator('input[type="file"]').evaluate(
            """async input=>{const bytes=new Uint8Array(await input.files[0].arrayBuffer());
            let out='';for(const b of bytes)out+=String.fromCharCode(b);return btoa(out);}"""
        )
        raw = base64.b64decode(encoded)
        parsed = validate(raw, "capture.wav", "audio/wav")
        self.assertLessEqual(len(raw), 160044)
        self.assertEqual(parsed.metadata["sample_rate"], 8000)
        self.assertEqual(parsed.metadata["channels"], 1)
        self.assertEqual(int(widget.locator("[data-audio-bytes]").inner_text()), len(raw))
        self.assertAlmostEqual(
            float(widget.locator("[data-audio-duration]").inner_text()),
            (len(raw) - 44) / 16000,
            places=2,
        )
        with wave.open(io.BytesIO(raw)) as audio:
            self.assertEqual(audio.getsampwidth(), 2)
            self.assertGreaterEqual(audio.getnframes(), 8000)
            self.assertNotEqual(set(audio.readframes(audio.getnframes())), {0})
        return raw, parsed

    def initial_audio_case(self, page, directory, rights):
        response = page.goto(self.live_server_url + "/casework/")
        self.assertEqual(response.status, 200)
        self.assertIn("microphone=(self)", response.headers["permissions-policy"])
        form = page.locator("form:has(#question)")
        widget = form.locator("[data-browser-audio]")
        page.wait_for_function("e=>e.dataset.audioState==='idle'", arg=widget.element_handle())
        self.assertEqual(page.evaluate("probe.calls"), 0)
        self.assertEqual(self.sync(lambda: Case.objects.count()), 0)
        session = page.context.new_cdp_session(page)
        context_id = session.send("Target.getTargetInfo")["targetInfo"]["browserContextId"]
        permission = {
            "permission": {"name": "microphone"},
            "origin": self.live_server_url,
            "browserContextId": context_id,
        }
        session.send("Browser.setPermission", {**permission, "setting": "denied"})
        widget.locator("[data-audio-start]").click()
        page.wait_for_function("e=>e.dataset.audioState==='error'", arg=widget.element_handle())
        self.released(page)
        self.assertIn("لم يُمنح", widget.locator("[data-audio-status]").inner_text())
        session.send("Browser.setPermission", {**permission, "setting": "granted"})
        widget.locator("[data-audio-start]").click()
        page.wait_for_function("e=>e.dataset.audioState==='recording'", arg=widget.element_handle())
        widget.locator("[data-audio-cancel]").click()
        self.released(page)
        self.assertEqual(form.locator('[type="file"]').evaluate("e=>e.files.length"), 0)
        self.assertEqual(page.evaluate("probe.urls.size"), 0)
        self.assertEqual(self.sync(lambda: Case.objects.count()), 0)
        raw, parsed = self.record(page, form)
        form.locator("#question").fill(QUESTION)
        form.locator('[name="synthetic_only"]').check()
        self.capture(page, "initial-real-fake-microphone-preview")
        self.submit(page, form.locator('button[type="submit"]'))
        self.source = {
            "public_ref": page.locator("#public-reference").inner_text(),
            "token": page.locator("#issued-token").inner_text(),
        }
        case = self.sync(lambda: Case.objects.get(public_ref=self.source["public_ref"]))
        self.source["case_id"] = str(case.pk)
        self.assertEqual(self.sync(lambda: Case.objects.count()), 1)
        self.assertEqual(case.evidence_version, 2)
        asset = self.sync(lambda: CaseAttachment.objects.get(case=case))
        self.assertIsNone(asset.original)
        self.assertEqual(asset.sha256, sha256(raw).hexdigest())
        self.assertEqual(asset.validation_metadata, parsed.metadata)
        self.assertEqual(
            self.sync(
                lambda: attachments.requester_read(
                    token=self.source["token"],
                    attachment_id=str(asset.pk),
                    synthetic_fixtures_only=True,
                )["raw"]
            ),
            raw,
        )
        # Fixture scopes/rights are explicit and exact; intake grants none itself.
        directory.refs = frozenset({self.source["public_ref"]})
        rights.pins = frozenset(
            {(self.source["public_ref"], "ATTACHMENT", str(asset.pk), asset.sha256)}
        )
        self.recordings = {"question": base64.b64encode(raw).decode()}
        self.question_audio = {"id": str(asset.pk), "sha256": asset.sha256}
        self.common = dict(
            case_id=self.source["case_id"],
            subject_id="synthetic-mufti",
            provider=directory,
            synthetic_fixtures_only=True,
        )
        self.capture(page, "sole-case-created-from-recorded-audio")

    def clarify_and_reply(self, staff, requester, source, files):
        self.open_case(staff, source["public_ref"])
        staff.locator("#clarification-text").fill("استيضاح اصطناعي عن التسجيل المرفق.")
        self.click(staff, "طلب استيضاح")
        requester.goto(self.live_server_url + "/casework/status/")
        self.assertEqual(requester.locator("#portal-token").count(), 0)
        requester.locator("#portal-followup").fill(REPLY)
        mime, raw = files["synthetic.png"]
        requester.locator("#reply-attachment").set_input_files(
            {"name": "synthetic.png", "mimeType": mime, "buffer": raw}
        )
        requester.locator('#portal-reply-form [name="synthetic_only"]').check()
        self.click(requester, "إرسال التعقيب")
        self.assertIn("حُفظ ردك ومرفقه معًا", requester.content())
        mime, raw = files["synthetic.pdf"]
        requester.locator("#portal-attachment").set_input_files(
            {"name": "synthetic.pdf", "mimeType": mime, "buffer": raw}
        )
        self.form(requester, "attachment_upload").locator('[name="synthetic_only"]').check()
        self.click(requester, "حفظ مرفق السؤال")
        self.assertEqual(requester.locator("#attachments article").count(), 3)
        requester.locator("#attachments audio[src]").evaluate("async e=>{await e.play();}")
        self.capture(requester, "recorded-original-and-clarification-evidence")
        self.open_case(staff, source["public_ref"])
        self.assertEqual(staff.locator("[data-evidence-attachment]").count(), 3)
        staff.locator("#answer-text").fill(DRAFT)
        self.click(staff, "حفظ مسودة الجواب")

    def research_and_parts(self, staff, source, edition, files):
        # Research_add creates a current evidence-bound answer, retaining history.
        self.action(staff, "research_open")
        staff.locator("#query").fill("فرع")
        staff.locator("#kind").select_option("REFERENCE")
        staff.locator("#edition").select_option(str(edition))
        staff.locator("#part").fill("مقدمة")
        staff.locator("#page").fill("2")
        self.submit(staff, staff.locator("#research-ranked-search"))
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
        staff.context.grant_permissions(["microphone"], origin=self.live_server_url)
        raw, _ = self.record(staff, self.form(staff, "answer_media_save"))
        self.recordings["answer"] = base64.b64encode(raw).decode()
        self.form(staff, "answer_media_save").locator('[name="synthetic_only"]').check()
        self.click(staff, "حفظ إصدار متعدد الأجزاء")
        mime, raw = files["synthetic.pdf"]
        staff.locator("#answer-file").set_input_files(
            {"name": "synthetic.pdf", "mimeType": mime, "buffer": raw}
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
        self.reference_budget = self.respect_budget_window()
        old_timed = self.timed_reference(staff, 100, 700)
        old_pdf = self.pdf_reference(staff)
        self.action(staff, "case_workspace")
        staff.locator("#return-note").fill("مراجعة بشرية اصطناعية لترتيب الملف والصوت.")
        self.click(staff, "إعادة للمراجعة")
        self.assertIn("مراجعة بشرية اصطناعية", staff.locator("#mufti-return-reason").inner_text())
        self.action(staff, "answer_media")
        staff.locator("#multipart-text").fill(APPROVED_TEXT)
        self.form(staff, "answer_media_save").locator('[name="synthetic_only"]').check()
        self.click(staff, "حفظ إصدار متعدد الأجزاء")
        self.assertEqual(staff.request.get(self.live_server_url + old_timed["url"]).status, 404)
        self.final_timed = self.timed_reference(staff, 200, 800, old_timed["id"])
        self.assertEqual(staff.request.get(self.live_server_url + old_pdf["url"]).status, 404)
        self.final_pdf = self.pdf_reference(staff, previous=old_pdf["id"])
        self.action(staff, "case_workspace")
        self.assertEqual(staff.locator("#mufti-answer-revision").inner_text(), "6")
        self.assertEqual(staff.locator("#review audio").count(), 1)
        self.assertEqual(staff.locator("#review iframe").count(), 1)
        self.click(staff, "اعتماد هذه النسخة")
        self.action(staff, "answer_media")
        self.form(staff, "answer_media_release").locator('[name="confirm"]').check()
        self.click(staff, "إتاحة النسخة المعتمدة للسائل تجريبيًا")
        self.capture(staff, "human-approved-three-part-answer")

    def timed_reference(self, staff, start, end, previous=None):
        self.action(staff, "timed_desk")
        form = self.form(staff, "timed_propose")
        options = form.locator('[name="source_pin"] option')
        self.assertEqual(options.count(), 1)
        self.assertIn(self.question_audio["sha256"], options.inner_text())
        form.locator('[name="start_ms"]').fill(str(start))
        form.locator('[name="end_ms"]').fill(str(end))
        form.locator('[name="reason"]').fill(TIMED_REASON)
        if previous:
            form.locator('[name="replaces_id"]').select_option(previous)
            self.assertIn("لم تُنقل إلى الإصدار الحالي", staff.content())
        self.click(staff, "حفظ اقتراح بشري")
        self.form(staff, "timed_preview").locator('[name="context_ms"]').select_option("1000")
        self.click(staff, "استماع خاص للمراجعة قبل التأكيد")
        audio = staff.locator("main audio")
        preview_url = audio.get_attribute("src")
        self.assertTrue(preview_url.split("#")[1].startswith("t=0,"))
        audio.evaluate("async e=>{await e.play();}")
        self.assertGreater(audio.evaluate("e=>e.duration"), end / 1000)
        self.click(staff, "تأكيد الموضع بعد الاستماع البشري")
        self.click(staff, "فتح الموضع المصرح به")
        player_url = staff.locator("main audio").get_attribute("src")
        self.assertEqual(player_url.split("#")[1], f"t={start / 1000:g},{end / 1000:g}")
        url = player_url.split("#")[0]
        response = staff.request.get(self.live_server_url + url)
        self.assertEqual(response.status, 200)
        self.assertEqual(response.body(), base64.b64decode(self.recordings["question"]))
        row = self.sync(lambda: TimedCitation.objects.order_by("-created_at").first())
        self.assertEqual(str(row.attachment_id), self.question_audio["id"])
        self.assertEqual((row.start_ms, row.end_ms), (start, end))
        self.assertLessEqual(end, row.duration_ms)
        self.capture(staff, "timed-correction" if previous else "timed-confirmed-original")
        return {"id": str(row.pk), "url": url}

    def evaluate_search(self, staff, reviewer):
        from apps.arabic_search_eval.models import EvaluationDecision, EvaluationRevision
        from apps.arabic_search_eval.views import proposed_bundle

        bundle = proposed_bundle()
        bundle["queries"] = bundle["queries"][:2]
        self.action(staff, "research_open")
        self.click(staff, "إصدارات تقييم البحث والمراجعة البشرية")
        staff.get_by_text("اقتراح إصدار جديد مع حفظ التاريخ", exact=True).click()
        staff.locator("#bundle").fill(json.dumps(bundle, ensure_ascii=False))
        staff.locator("#proposal_note").fill("تقييم اصطناعي لا يمثل مراجعة خبير حقيقي.")
        self.click(staff, "حفظ إصدار ينتظر المراجعة")
        self.assertIn("بانتظار المراجعة", staff.locator("main").inner_text())
        self.assertEqual(self.sync(lambda: EvaluationDecision.objects.count()), 0)
        self.action(reviewer, "research_open")
        self.click(reviewer, "إصدارات تقييم البحث والمراجعة البشرية")
        for index in range(2):
            reviewer.locator(f"#verdict_{index}").select_option("AGREE")
            reviewer.locator(f"#note_{index}").fill("قرار اختبار اصطناعي للتوقع المحدد فقط.")
        reviewer.locator("#decision_note").fill("مراجعة منفصلة مصطنعة، ليست معيارًا ذهبيًا بشريًا.")
        reviewer.locator('input[name="confirm"]').check()
        self.click(reviewer, "اعتماد هذه النسخة فقط")
        self.assertIn("اعتمده المراجع المسجل", reviewer.locator("main").inner_text())
        approved = self.sync(lambda: EvaluationRevision.objects.get(number=1))
        decision = self.sync(lambda: EvaluationDecision.objects.get(revision=approved))
        self.assertNotEqual(decision.subject_id, approved.subject_id)
        self.assertEqual(decision.subject_id, "synthetic-publisher")
        self.capture(reviewer, "independent-synthetic-evaluation-decision")
        # A changed evaluation version cannot inherit the old decision.
        self.action(staff, "research_open")
        self.click(staff, "إصدارات تقييم البحث والمراجعة البشرية")
        staff.get_by_text("اقتراح إصدار جديد مع حفظ التاريخ", exact=True).click()
        bundle["queries"][0]["rationale"] += " تصحيح اصطناعي للشرح في النسخة2."
        staff.locator("#bundle").fill(json.dumps(bundle, ensure_ascii=False))
        staff.locator("#proposal_note").fill(
            "نسخة جديدة تنتظر مراجعة مستقلة ولا ترث القرار السابق."
        )
        self.click(staff, "حفظ إصدار ينتظر المراجعة")
        current = self.sync(lambda: EvaluationRevision.objects.get(number=2))
        self.assertEqual(current.corpus_sha256, approved.corpus_sha256)
        self.assertNotEqual(current.judgements_sha256, approved.judgements_sha256)
        self.assertFalse(
            self.sync(lambda: EvaluationDecision.objects.filter(revision=current).exists())
        )
        self.assertEqual(self.sync(lambda: EvaluationDecision.objects.count()), 1)
        self.assertIn("بانتظار المراجعة", staff.locator("main").inner_text())
        self.capture(staff, "new-evaluation-pending-preserved-first-review")

    def pdf_reference(self, staff, previous=None):
        from apps.pdf_citations.models import PdfCitation

        self.action(staff, "pdf_desk")
        form = self.form(staff, "pdf_propose")
        options = form.locator('[name="source_pin"] option')
        self.assertEqual(options.count(), 1)
        self.assertIn(self.pdf_source["sha256"], options.inner_text())
        form.locator('[name="page_number"]').fill("2")
        form.locator('[name="printed_label"]').fill("7")
        form.locator('[name="printed_confirmed"]').select_option("yes")
        form.locator('[name="reason"]').fill(
            "مطابقة بشرية اصطناعية: صفحة الملف2 تحمل الرقم7؛ ليست نصًا علميًا."
        )
        if previous:
            form.locator('[name="replaces_id"]').select_option(previous)
        self.click(staff, "حفظ اقتراح بشري")
        self.click(staff, "معاينة خاصة للمراجعة قبل التأكيد")
        frame = staff.locator('iframe[title="معاينة ملف PDF الأصلي"]')
        preview_url = frame.get_attribute("src")
        self.assertTrue(preview_url.endswith("#page=2"))
        preview = staff.request.get(self.live_server_url + preview_url.split("#")[0])
        self.assertEqual(preview.status, 200)
        self.assertEqual(preview.body(), self.pdf_bytes)
        self.assertIn("sandbox", preview.headers["content-security-policy"])
        # A native viewer fragment plus exact bytes proves navigation intent, not
        # the browser plugin's visually selected page. Keep that limit in evidence.
        self.click(staff, "تأكيد الموضع بعد المعاينة البشرية")
        self.click(staff, "فتح الموضع المصرح به")
        url = (
            staff.locator('iframe[title="معاينة ملف PDF الأصلي"]')
            .get_attribute("src")
            .split("#")[0]
        )
        response = staff.request.get(self.live_server_url + url)
        self.assertEqual(response.status, 200)
        self.assertEqual(response.body(), self.pdf_bytes)
        row = self.sync(lambda: PdfCitation.objects.order_by("-created_at").first())
        self.assertEqual(
            (row.page_number, row.page_count, row.printed_label, row.printed_confirmed),
            (2, 2, "7", True),
        )
        self.assertEqual(str(row.attachment_id), self.pdf_source["id"])
        self.capture(staff, "pdf-corrected-page-mapping" if previous else "pdf-page-mapping")
        return {"id": str(row.pk), "url": url}

    def classification(self, staff, reviewer):
        self.action(staff, "pub_open")
        self.action(staff, "pub_library")
        self.click(staff, "فتح صفحة النسخة")
        self.click(staff, "اقتراح التصنيف ومراجعته المستقلة")
        staff.locator("#new-label").fill(CLASSIFICATION_LABEL)
        staff.locator("#new-reason").fill(CLASSIFICATION_REASON)
        self.click(staff, "حفظ اقتراح غير معتمد")
        self.action(reviewer, "pub_open")
        self.action(reviewer, "pub_library")
        self.click(reviewer, "فتح صفحة النسخة")
        self.click(reviewer, "اقتراح التصنيف ومراجعته المستقلة")
        form = reviewer.locator('form:has(button[value="classification_reject"])')
        form.locator('[name="note"]').fill("رفض اصطناعي يتطلب توضيح حدود الفهرس.")
        form.locator('[name="confirm"]').check()
        self.submit(reviewer, form.locator('[value="classification_reject"]'))
        self.click(staff, "تحديث مكتب المراجعة")
        staff.get_by_text("تصحيح باقتراح جديد غير معتمد", exact=True).click()
        correction = staff.locator('article form:has(input[name="label"])')
        correction.locator('[name="label"]').fill(CLASSIFICATION_LABEL)
        correction.locator('[name="reason"]').fill(CLASSIFICATION_REASON + " تصحيح بشري: فهرس فقط.")
        self.click(staff, "حفظ تصحيح غير معتمد")
        self.click(reviewer, "تحديث مكتب المراجعة")
        form = reviewer.locator('form:has(button[value="classification_approve"])')
        form.locator('[name="note"]').fill("اعتماد تصنيف تجريبي محدود بعد مراجعة بشرية مستقلة.")
        form.locator('[name="confirm"]').check()
        self.submit(reviewer, form.locator('[value="classification_approve"]'))
        self.assertIn("APPROVED", reviewer.content())
        self.assertIn("REJECTED", reviewer.content())
        from apps.experimental_publication.models import PublicationEdition

        publication = self.sync(
            lambda: PublicationEdition.objects.get(case_id=self.source["case_id"])
        )
        self.assertEqual(publication.category, "تجربة مغلقة")
        self.capture(reviewer, "independent-classification-correction-history")

    def classified_publication(self, staff, reviewer, publisher, simulation, edition):
        from datetime import timedelta

        from django.utils import timezone

        from apps.classification_review.models import ClassificationRevision, EditorialBinding
        from apps.experimental_publication.models import PublicationAction, PublicationEdition
        from apps.library_preview.policy import PreviewPolicy, PublicationGrant, ReferenceGrant

        classification = self.sync(
            lambda: ClassificationRevision.objects.order_by("-number").first()
        )
        simulation.revision_ids = frozenset({str(classification.pk)})
        original = self.sync(lambda: PublicationEdition.objects.get(case_id=self.source["case_id"]))
        self.click(staff, "تحديث مكتب المراجعة")
        self.form(staff, "classification_editorial_prepare").locator('[name="confirm"]').check()
        self.submit_form(staff, "classification_editorial_prepare")
        self.assertIn("CANDIDATE", staff.locator("main").inner_text())
        binding = self.sync(lambda: EditorialBinding.objects.get(revision=classification))
        candidate = self.sync(lambda: PublicationEdition.objects.get(pk=binding.edition_id))
        self.assertEqual(candidate.number, 2)
        self.assertEqual(candidate.category, CLASSIFICATION_LABEL)
        self.assertEqual(
            (candidate.title, candidate.body, candidate.citations),
            (original.title, original.body, original.citations),
        )
        self.assertFalse(
            self.sync(
                lambda: PublicationAction.objects.filter(
                    edition=candidate, action="APPROVE"
                ).exists()
            )
        )
        self.form(staff, "classification_editorial_review").locator('[name="confirm"]').check()
        self.submit_form(staff, "classification_editorial_review")
        self.assertIn("REVIEWED", staff.locator("main").inner_text())
        self.assertEqual(self.form(staff, "classification_editorial_approve").count(), 0)
        self.capture(staff, "classification-separate-unpublished-editorial-candidate")
        self.login(publisher, "N" * 64)
        self.open_case(publisher, self.source["public_ref"])
        self.action(publisher, "pub_open")
        self.action(publisher, "pub_library")
        self.click(publisher, "فتح صفحة النسخة")
        self.click(publisher, "اقتراح التصنيف ومراجعته المستقلة")
        self.click(publisher, "فحص النسخة التحريرية المرتبطة في المحاكاة")
        self.form(publisher, "classification_editorial_approve").locator('[name="confirm"]').check()
        self.submit_form(publisher, "classification_editorial_approve")
        self.assertIn("PUBLISHED", publisher.locator("main").inner_text())
        self.assertEqual(
            self.sync(
                lambda: (
                    PublicationAction.objects.get(edition=candidate, action="APPROVE").subject_id
                )
            ),
            "synthetic-independent-publisher",
        )
        self.assertEqual(
            self.sync(lambda: PublicationEdition.objects.get(pk=original.pk).category),
            "تجربة مغلقة",
        )
        self.capture(publisher, "independent-new-edition-publication")
        # New editorial editions do not inherit old scientific relationships.
        self.action(staff, "rights_desk")
        staff.locator("#rights-edition").select_option(str(edition))
        staff.locator("#rights-query").fill("فرع")
        self.click(staff, "بحث المصادر الحالية")
        self.form(staff, "rights_relation_propose").locator('[name="note"]').fill(PRIVATE)
        self.submit_form(staff, "rights_relation_propose")
        self.action(reviewer, "rights_desk")
        self.form(reviewer, "rights_relation_action").locator('[name="confirm"]').check()
        self.submit_form(reviewer, "rights_relation_action")
        self.editorial_binding = str(binding.pk)
        self.source_publication = str(original.pk)
        return PreviewPolicy(
            (PublicationGrant(str(candidate.pk), candidate.content_sha256),),
            (ReferenceGrant(edition, 2, candidate.citations[0]["source_sha256"]),),
            timezone.now() + timedelta(minutes=30),
            True,
        )

    def staff_library_roundtrip(self, staff):
        self.action(staff, "pub_open")
        self.action(staff, "pub_library")
        search = self.form(staff, "pub_library")
        search.locator('[name="query"]').fill("عنوان V11")
        search.locator('[name="category"]').select_option(CLASSIFICATION_LABEL)
        self.submit(staff, search.get_by_role("button", name="بحث", exact=True))
        self.click(staff, "فتح صفحة النسخة")
        self.assert_case_header(staff, self.source["public_ref"])
        self.click(staff, "الدروس والمراجع المرتبطة")
        self.assert_case_header(staff, self.source["public_ref"])
        self.click(staff, "فتح المادة المصرح بها")
        self.assertIn("فَرْعٌ تَجْرِيبِيّ", staff.content())
        self.capture(staff, "new-publication-explicit-knowledge-return")
        self.click(staff, "العودة إلى نسخة الفتوى التجريبية")
        self.click(staff, "العودة إلى المكتبة التجريبية")
        search = self.form(staff, "pub_library")
        self.assertEqual(search.locator('[name="query"]').input_value(), "عنوان V11")
        self.assertEqual(search.locator('[name="category"]').input_value(), CLASSIFICATION_LABEL)

    def anonymous_preview(self, browser):
        super().anonymous_preview(browser)
        context = self.context(browser)
        try:
            page = context.new_page()
            page.goto(self.live_server_url + "/library-preview/")
            self.submit(page, page.get_by_role("link", name="عنوان V11 اصطناعي", exact=True))
            for private in (QUESTION, CLASSIFICATION_REASON, TIMED_REASON):
                self.assertNotIn(private, page.content())
        finally:
            context.close()


@override_settings(**FEATURES)
class V14ConnectedBrowserTests(V14Harness, LiveServerTestCase):
    host = "127.0.0.1"

    def test_one_v14_recorded_case_partial_delivery_encrypted_restore_and_target_http(self):
        from playwright.sync_api import sync_playwright

        # Fail before opening a browser if the isolated PostgreSQL tools are absent.
        pg_bin = os.environ.get("FATWA_RECOVERY_PG_BIN")
        if not pg_bin:
            dump = shutil.which("pg_dump")
            self.assertIsNotNone(
                dump, "set FATWA_RECOVERY_PG_BIN to the isolated matching PG tools"
            )
            pg_bin = str(Path(dump).parent)
        self.assertTrue((Path(pg_bin) / "pg_dump").is_file())
        OUT.mkdir(parents=True, exist_ok=True)
        self.errors, self.external = [], []
        edition, _ = bootstrap_catalog()
        directory = Directory()
        directory.refs = frozenset()
        recording_rights = ExactRecordingRights(directory)
        simulation = SimulationPolicy(directory)
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
            TemporaryDirectory(prefix="v14-source-") as private_root,
            TemporaryDirectory(prefix="v14-control-") as control,
            TemporaryDirectory(prefix="v14-keys-") as keys,
            TemporaryDirectory(prefix="v14-sealed-") as backup_root,
            TemporaryDirectory(prefix="v14-target-") as target_root,
        ):
            storage = FileSystemStorage(private_root, synthetic_fixtures_only=True)
            maintenance.initialize(root=control, storage=storage, synthetic_fixtures_only=True)
            with override_settings(
                FATWA_PRIVATE_MEDIA_STORAGE=storage,
                FATWA_CASEWORK_IDENTITY_PROVIDER=directory,
                FATWA_SOURCE_RIGHTS_AUTHORITY=RightsAuthority(directory),
                FATWA_RESEARCH_WORKSPACE_RIGHTS=recording_rights,
                FATWA_CLASSIFICATION_REVIEW_AUTHORITY=ClassificationPolicy(directory),
                FATWA_ARABIC_SEARCH_REVIEW_AUTHORITY=EvaluationPolicy(directory),
                FATWA_EXPERIMENTAL_PUBLICATION_AUTHORITY=PublicationPolicy(directory),
                FATWA_CLASSIFICATION_EDITORIAL_SIMULATION_POLICY=simulation,
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
                fake_microphone = Path(keys) / "fake-microphone.wav"
                write_fake_microphone(fake_microphone)
                with override_settings(**fixture.settings()), sync_playwright() as p:
                    sandbox = os.environ.get("FATWA_BROWSER_SANDBOX", "1") != "0"
                    browser = p.chromium.launch(
                        executable_path=os.environ.get(
                            "FATWA_FASTBUILD_BROWSER", "/usr/bin/chromium"
                        ),
                        headless=True,
                        chromium_sandbox=sandbox,
                        args=[
                            "--disable-dev-shm-usage",
                            "--use-fake-device-for-media-stream",
                            "--use-file-for-fake-audio-capture=" + str(fake_microphone),
                        ],
                    )
                    try:
                        staff, requester, reviewer, publisher = [
                            self.context(browser).new_page() for _ in range(4)
                        ]
                        self.initial_audio_case(requester, directory, recording_rights)
                        self.login(staff, "M" * 64)
                        self.clarify_and_reply(staff, requester, self.source, files)
                        pdf = self.sync(
                            lambda: CaseAttachment.objects.get(
                                case_id=self.source["case_id"], media_type="application/pdf"
                            )
                        )
                        self.pdf_source = {"id": str(pdf.pk), "sha256": pdf.sha256}
                        self.pdf_bytes = files["synthetic.pdf"][1]
                        recording_rights.pins = recording_rights.pins | {
                            (self.source["public_ref"], "ATTACHMENT", str(pdf.pk), pdf.sha256)
                        }
                        self.rights_review(staff, reviewer, self.source, edition)
                        self.research_and_parts(staff, self.source, edition, files)
                        source_budget = self.respect_budget_window()
                        self.evaluate_search(staff, reviewer)
                        self.pilot_reports(staff, requester)
                        policy = self.publish_and_relate(staff, reviewer, edition)
                        classification_budget = self.respect_budget_window()
                        self.classification(staff, reviewer)
                        editorial_budget = self.respect_budget_window()
                        policy = self.classified_publication(
                            staff, reviewer, publisher, simulation, edition
                        )
                        self.staff_library_roundtrip(staff)
                        with override_settings(FATWA_LIBRARY_PREVIEW_POLICY=policy):
                            self.anonymous_preview(browser)
                        expected = self.sync(lambda: inventory(self.source["case_id"]))
                        self.assertEqual(expected["source_review"], [])
                        self.assertEqual(
                            expected["counts"],
                            {
                                "cases": 1,
                                "evidence": 5,
                                "source_bindings": 0,
                                "answers": 6,
                                "citations": 1,
                                "parts": 3,
                                "attachments": 3,
                                "rights_sources": 1,
                                "rights_revisions": 1,
                                "rights_approvals": 1,
                                "source_review_notes": 0,
                                "delivery_intents": 3,
                                "publications": 2,
                                "publication_approvals": 2,
                                "knowledge_links": 2,
                                "knowledge_approvals": 2,
                                "evaluation_revisions": 2,
                                "evaluation_decisions": 1,
                                "pdf_citations": 2,
                                "pdf_confirmations": 2,
                                "editorial_bindings": 1,
                                "timed_citations": 2,
                                "timed_confirmations": 2,
                                "classifications": 2,
                                "classification_approvals": 1,
                                "classification_rejections": 1,
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
                    "recordings": self.recordings,
                    "media_pins": list(recording_rights.pins),
                    "media_deadline": recording_rights.deadline.isoformat(),
                    "identity_deadline": directory.valid_until.isoformat(),
                    "final_timed": self.final_timed,
                    "final_pdf": self.final_pdf,
                    "simulation_revisions": list(simulation.revision_ids),
                    "editorial_binding": self.editorial_binding,
                    "source_publication": self.source_publication,
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
                        "import django; django.setup(); from tests.casework.v14_restored_browser import restore_and_verify; restore_and_verify()",
                    ],
                    input=json.dumps(spec),
                    text=True,
                    capture_output=True,
                    timeout=180,
                    env=os.environ.copy(),
                )
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertIn("V14_RESTORED_HTTP_PASS", result.stdout)
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
                            "reference_budget": self.reference_budget,
                            "classification_budget": classification_budget,
                            "editorial_budget": editorial_budget,
                            "human_expert_gold_review": "PENDING",
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
                                "pdf_plugin_selected_page": "NOT_VERIFIED",
                            },
                        },
                        indent=2,
                    )
                )
