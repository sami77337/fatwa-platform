"""One offline-source to approved knowledge-library browser journey on canonical records."""

import json
import os
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict, replace
from pathlib import Path
from tempfile import TemporaryDirectory
from urllib.parse import urlsplit

from django.db import close_old_connections, connections
from django.test import LiveServerTestCase, override_settings

from apps.answer_media.models import AnswerManifest, AnswerPart, PrivateAnswerRelease
from apps.case_attachments.models import CaseAttachment
from apps.case_citations.models import AnswerCitation
from apps.casework.models import AnswerRevision, Case
from apps.composite_delivery import services as composite
from apps.composite_delivery.models import CompositeDelivery
from apps.composite_delivery.simulator import OfflineProviderSimulator
from apps.delivery_planner.planner import Capabilities
from apps.delivery_queue.models import DeliveryIntent
from apps.experimental_publication.models import PublicationEdition
from apps.knowledge_links.authority import KnowledgeAuthority
from apps.knowledge_links.models import KnowledgeAction, KnowledgeRevision
from apps.private_media.filesystem import FileSystemStorage
from apps.private_media.fixtures import synthetic_files
from apps.reference.ingest import ingest_catalog
from apps.reference.models import ReferenceHeading
from apps.source_case_intake import services as intake
from apps.source_case_intake import simulators
from apps.source_case_intake.models import EvidenceBinding
from apps.transcript_case_links.models import TranscriptLink
from apps.transcript_case_links.tests import bundle
from tests.casework.delivery_fixtures import CaseDeliveryFixture
from tests.casework.test_http import WEB_SETTINGS
from tests.casework.test_v7_browser import BrowserDirectory, BrowserPublicationAuthority
from tests.reference.test_catalog import fixture

OUT = Path(".local/qa/v9/browser")
DRAFT = "جواب بشري اصطناعي متصل بمرجعين وتسجيل تجريبي، وليس فتوى حقيقية."
NOTE = "سبب بحثي خاص لا يكشف في المكتبة."
PUBLIC = "نص تحريري اصطناعي للمكتبة التجريبية المغلقة."


class KnowledgePolicy(KnowledgeAuthority):
    def __init__(self, directory):
        self.directory = directory
        self.allow_open = True

    def permits(self, *, provider_id, subject_id, auth_epoch, case_ref, action, kind):
        return (
            provider_id == self.directory.provider_id
            and auth_epoch == "epoch-1"
            and case_ref in self.directory.refs
            and kind in {"REFERENCE", "TRANSCRIPT"}
            and (
                (action in {"APPROVE", "WITHDRAW"} and subject_id == "synthetic-publisher")
                or (
                    action == "OPEN_TRANSCRIPT"
                    and self.allow_open
                    and subject_id in {"synthetic-mufti", "synthetic-publisher"}
                )
            )
        )


@override_settings(
    **{
        **WEB_SETTINGS,
        "ROOT_URLCONF": "config.campaign_urls",
        "FATWA_SOURCE_CASE_INTAKE_ENABLED": True,
        "FATWA_CASE_ATTACHMENTS_ENABLED": True,
        "FATWA_CASE_CITATIONS_ENABLED": True,
        "FATWA_ANSWER_MEDIA_ENABLED": True,
        "FATWA_ANSWER_MEDIA_PRIVATE_ENABLED": True,
        "FATWA_COMPOSITE_DELIVERY_ENABLED": True,
        "FATWA_EXPERIMENTAL_PUBLICATION_ENABLED": True,
        "FATWA_KNOWLEDGE_LINKS_ENABLED": True,
    }
)
class V9ConnectedBrowserTests(LiveServerTestCase):
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

    def click(self, page, name, *, locator=None, code=200):
        target = locator or page.get_by_role("button", name=name, exact=True)
        with page.expect_navigation(wait_until="domcontentloaded") as navigation:
            target.focus()
            target.press("Enter")
        self.assertEqual(navigation.value.status, code, page.content()[:1000])
        self.assertIn("no-store", navigation.value.headers.get("cache-control", ""))

    def capture(self, page, name):
        for width in (320, 1280):
            page.set_viewport_size({"width": width, "height": 900})
            page.wait_for_load_state("networkidle")
            page.evaluate(
                "async()=>{await document.fonts.ready;await new Promise(r=>requestAnimationFrame(()=>requestAnimationFrame(r)));}"
            )
            self.assertEqual(page.locator("html").get_attribute("dir"), "rtl")
            self.assertLessEqual(page.evaluate("document.documentElement.scrollWidth"), width)
            page.screenshot(path=str(OUT / f"{name}-{width}.png"), full_page=True)

    def test_source_files_research_composite_delivery_and_reviewed_knowledge_links(self):
        from playwright.sync_api import sync_playwright

        OUT.mkdir(parents=True, exist_ok=True)
        spec, rows = fixture()
        spec = replace(spec, source_book_id="622")
        preview = ingest_catalog(spec, rows)
        edition = ingest_catalog(
            spec, rows, dry_run=False, expected_checksum=preview.checksum
        ).edition_id
        heading = ReferenceHeading.objects.get(edition_id=edition, source_row_id=2)
        directory = BrowserDirectory()
        policy = KnowledgePolicy(directory)
        source = intake.ingest(
            raw=simulators.telegram(document=True),
            context=simulators.context("telegram"),
            synthetic_fixtures_only=True,
        )
        directory.refs = frozenset({source["public_ref"]})
        common = dict(
            case_id=source["case_id"],
            subject_id="synthetic-mufti",
            provider=directory,
            synthetic_fixtures_only=True,
        )
        signing_fixture = CaseDeliveryFixture()
        signing_fixture.intake = lambda suffix: source
        signing_fixture.setUp()
        signing_fixture.directory = directory
        simulator = OfflineProviderSimulator(synthetic_fixtures_only=True)
        files = {name: (mime, raw) for name, mime, raw in synthetic_files()}
        channels = []
        profile = composite.ChannelProfile(
            Capabilities(
                composite.SIMULATOR_PROVIDER,
                "synthetic.v1",
                frozenset({"text", "document", "audio", "image"}),
                6000,
                True,
            ),
            192000,
            frozenset({"text/plain", "audio/wav", "application/pdf", "image/png"}),
        )

        def capabilities(channel):
            channels.append(channel)
            return profile

        with TemporaryDirectory(
            prefix="v9-private-", dir=Path(".local").absolute()
        ) as private_root:
            storage = FileSystemStorage(private_root, synthetic_fixtures_only=True)
            with (
                override_settings(
                    FATWA_CASEWORK_IDENTITY_PROVIDER=directory,
                    FATWA_PRIVATE_MEDIA_STORAGE=storage,
                    FATWA_CASE_DELIVERY_APPROVAL_VERIFIER=signing_fixture.approval_verifier,
                    FATWA_COMPOSITE_DELIVERY_CAPABILITIES=capabilities,
                    FATWA_COMPOSITE_DELIVERY_PROVIDER_VERIFIER=simulator.verifier,
                    FATWA_EXPERIMENTAL_PUBLICATION_AUTHORITY=BrowserPublicationAuthority(directory),
                    FATWA_KNOWLEDGE_LINKS_AUTHORITY=policy,
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
                errors, external = [], []
                try:
                    contexts = [
                        browser.new_context(viewport={"width": 1280, "height": 900})
                        for _ in range(3)
                    ]
                    for context in contexts:

                        def route(r):
                            if (
                                urlsplit(r.request.url).netloc
                                != urlsplit(self.live_server_url).netloc
                            ):
                                external.append(r.request.url)
                                r.abort()
                            else:
                                r.continue_()

                        context.route("**/*", route)
                    requester, staff, reviewer = [context.new_page() for context in contexts]
                    for page in (requester, staff, reviewer):
                        page.on("pageerror", lambda e: errors.append(str(e)))

                    requester.goto(self.live_server_url + "/casework/status/")
                    requester.locator("#workspace-token").fill(source["token"])
                    self.click(requester, "فتح المتابعة الخاصة")
                    self.click(requester, "مرفقات سؤالي")
                    requester.locator('input[name="attachment"]').set_input_files(
                        {
                            "name": "synthetic.txt",
                            "mimeType": files["synthetic.txt"][0],
                            "buffer": files["synthetic.txt"][1],
                        }
                    )
                    requester.locator('input[name="synthetic_only"]').check()
                    self.click(requester, "حفظ الأصل وإضافة الوقائع")
                    self.click(requester, "معاينة synthetic.txt")
                    self.assertIn(
                        files["synthetic.txt"][1].decode(), requester.locator("pre").inner_text()
                    )

                    def login(page, credential):
                        page.goto(self.live_server_url + "/casework/staff/login/")
                        page.locator("#credential").fill(credential)
                        self.click(page, "دخول المكتب")
                        self.click(page, source["public_ref"])

                    login(staff, "M" * 64)
                    self.assertIn("telegram", staff.content().lower())
                    self.assertIn("اسم تجريبي متكرر", staff.content())
                    self.capture(staff, "source-provenance")
                    self.click(staff, "ربط التفريغات بالقضايا")
                    staff.locator("#case").select_option(source["public_ref"])
                    self.click(staff, "عرض تفريغات القضية")
                    staff.locator("#bundle").set_input_files(
                        {
                            "name": "synthetic-reviewed.zip",
                            "mimeType": "application/zip",
                            "buffer": bundle(),
                        }
                    )
                    staff.locator('input[name="synthetic_only"]').check()
                    self.click(staff, "حفظ المصدر ومعاينة أسئلته")
                    staff.locator('input[name="confirm"]').first.check()
                    self.click(
                        staff,
                        "ربط السؤال بالقضية",
                        locator=staff.get_by_role(
                            "button", name="ربط السؤال بالقضية", exact=True
                        ).first,
                    )
                    self.assertIn("الروابط المحفوظة (1)", staff.content())
                    self.capture(staff, "same-case-transcript")
                    self.click(staff, "العودة إلى القضايا")
                    self.click(staff, source["public_ref"])

                    self.click(staff, "تحرير جواب بإحالة موثقة")
                    staff.locator("#answer").fill(DRAFT)
                    staff.locator("#edition").select_option(str(edition))
                    staff.locator("#query").fill("فرع")
                    self.click(staff, "اقتراح مصادر موجودة للمراجعة")
                    self.assertIn("(0/12)", staff.content())
                    self.click(staff, "معاينة الاقتراح 2")
                    self.assertEqual(staff.locator("#answer").input_value(), DRAFT)
                    self.capture(staff, "research-source-preview")
                    self.click(staff, "العودة إلى البحث والمسودة")
                    self.assertEqual(staff.locator("#query").input_value(), "فرع")
                    staff.locator("#note").fill(NOTE)
                    self.click(staff, "اختيار الاقتراح 2 بعد مراجعتي")
                    staff.locator("#query").fill("")
                    staff.locator("#page").fill("3")
                    self.click(staff, "البحث مع الاحتفاظ بالمسودة")
                    self.click(staff, "إضافة الموضع 3 إلى القائمة")
                    self.assertEqual(staff.locator("#answer").input_value(), DRAFT)
                    staff.locator('input[name="confirm"]').check()
                    self.click(staff, "حفظ الجواب والقائمة الكاملة")
                    self.click(staff, "العودة إلى القضية دون حفظ هذه المسودة")
                    self.click(staff, "تحرير جواب متعدد الأجزاء")
                    staff.locator("#answer-file").set_input_files(
                        {
                            "name": "synthetic.wav",
                            "mimeType": files["synthetic.wav"][0],
                            "buffer": files["synthetic.wav"][1],
                        }
                    )
                    staff.locator('input[name="synthetic_only"]').check()
                    self.click(staff, "حفظ إصدار متعدد الأجزاء")
                    self.click(staff, "العودة إلى القضية والاعتماد")
                    self.click(staff, "اعتماد هذه النسخة")
                    self.click(staff, "تحرير جواب متعدد الأجزاء")
                    staff.locator(
                        'form:has(input[value="answer_media_release"]) input[name="confirm"]'
                    ).check()
                    self.click(staff, "إتاحة النسخة المعتمدة للسائل تجريبيًا")
                    requester.goto(self.live_server_url + "/casework/status/")
                    self.click(requester, "أجزاء الجواب المتاحة خصوصيًا")
                    self.assertIn(DRAFT, requester.content())
                    self.assertNotIn(NOTE, requester.content())
                    self.assertIn("ليس إثبات تسليم", requester.content())
                    self.capture(requester, "private-portal-separate-from-delivery")
                    self.click(staff, "العودة إلى القضية والاعتماد")

                    self.click(staff, "تجهيز توصيل الجواب المركب")
                    prepared = self.sync(lambda: composite.prepare_composite_delivery(**common))
                    self.assertEqual(len(prepared["parts"]), 2)
                    signed = signing_fixture.receipt(prepared)
                    staff.locator("#composite-response").fill(
                        json.dumps(
                            {"request_sha256": prepared["plan_sha256"], "receipt": asdict(signed)}
                        )
                    )
                    staff.locator(
                        'form:has(input[value="composite_stage"]) input[name="confirm"]'
                    ).check()
                    self.click(staff, "تسجيل خطة الأجزاء الموقّعة")
                    worker = dict(
                        **common,
                        worker_id="synthetic-worker",
                        verify_worker=lambda worker, plan: worker == "synthetic-worker",
                        verify_receipt=signing_fixture.approval_verifier,
                    )

                    resolved_parts = {}

                    def outcome(lease, reported):
                        if lease.intent_key not in resolved_parts:
                            resolved_parts[lease.intent_key] = composite.resolve_composite_part(
                                **common,
                                lease=lease,
                                verify_receipt=signing_fixture.approval_verifier,
                            )
                        part = resolved_parts[lease.intent_key]
                        event = simulator.event(lease=lease, part=part, reported=reported)
                        return composite.record_composite_event(
                            **common, lease=lease, event=event, verifier=simulator.verifier
                        )

                    first = self.sync(lambda: composite.reserve_composite_part(**worker))
                    self.sync(lambda: outcome(first, "ACCEPTED"))
                    self.click(staff, "تحديث خطة التوصيل")
                    self.assertIn("قبول المزود فقط", staff.content())
                    self.assertIn("لم يثبت اكتمال", staff.content())
                    self.capture(staff, "accepted-is-not-delivered")
                    self.sync(lambda: outcome(first, "DELIVERED"))
                    second = self.sync(lambda: composite.reserve_composite_part(**worker))
                    self.sync(lambda: outcome(second, "DELIVERED"))
                    self.click(staff, "تحديث خطة التوصيل")
                    self.assertIn("اكتمل تقرير التسليم الموقّع", staff.content())
                    self.capture(staff, "signed-composite-complete")
                    requester.goto(self.live_server_url + "/casework/status/")
                    composite_section = requester.locator("#requester-composite-delivery")
                    self.assertIn(
                        "تحققت الإيصالات الموقّعة لجميع أجزاء هذا الإصدار.",
                        requester.locator("#composite-delivery-verified").inner_text(),
                    )
                    self.assertIn(
                        "أجزاء تحقق إثبات تسليمها الموقّع: 2 من 2.",
                        composite_section.inner_text(),
                    )
                    self.assertIn(
                        "ليست إرسالًا خارجيًا أو إثباتًا لقراءتك", composite_section.inner_text()
                    )
                    # Composite simulation evidence never unlocks the legacy #225 text path.
                    self.assertEqual(requester.locator("#requester-answer-text").count(), 0)
                    self.assertEqual(requester.locator("#requester-verified-parts").count(), 0)
                    self.assertNotIn(DRAFT, requester.content())
                    self.assertNotIn(NOTE, requester.content())
                    self.assertEqual(
                        requester.get_by_role(
                            "button", name="أجزاء الجواب المتاحة خصوصيًا", exact=True
                        ).count(),
                        1,
                    )
                    self.capture(requester, "requester-composite-evidence-separate-from-text")
                    # Return through the standard same-case desk; no additional original case.
                    staff.goto(self.live_server_url + "/casework/staff/")
                    self.click(staff, source["public_ref"])
                    self.click(staff, "نسخة النشر التجريبية")
                    staff.locator("#publication-title").fill("عنوان معرفة اصطناعي متصل")
                    staff.locator("#publication-category").fill("مرجع تجربة")
                    staff.locator("#publication-body").fill(PUBLIC)
                    self.click(staff, "حفظ نسخة مرشحة جديدة")
                    staff.locator(
                        'form:has(input[value="pub_review"]) input[name="confirm"]'
                    ).check()
                    self.click(staff, "تسجيل مراجعة التحرير والخصوصية")
                    login(reviewer, "P" * 64)
                    self.click(reviewer, "نسخة النشر التجريبية")
                    reviewer.locator(
                        'form:has(input[value="pub_approve"]) input[name="confirm"]'
                    ).check()
                    self.click(reviewer, "موافقة نشر مستقلة")
                    self.click(reviewer, "المكتبة التجريبية المغلقة")
                    self.click(reviewer, "فتح صفحة النسخة")
                    self.click(reviewer, "الدروس والمراجع المرتبطة")
                    self.assertNotIn(DRAFT, reviewer.content())
                    self.assertNotIn(source["public_ref"], reviewer.content())
                    self.click(staff, "المكتبة التجريبية المغلقة")
                    self.click(staff, "فتح صفحة النسخة")
                    self.click(staff, "الدروس والمراجع المرتبطة")
                    self.click(staff, "مراجعة الاقتراحات وسجل التصحيح الخاص")
                    transcript_id = self.sync(
                        lambda: str(TranscriptLink.objects.get(case_id=source["case_id"]).pk)
                    )
                    for kind, target_id in (
                        ("REFERENCE", str(heading.pk)),
                        ("TRANSCRIPT", transcript_id),
                    ):
                        form = staff.locator(
                            f'form:has(input[name="kind"][value="{kind}"]):has(input[name="target_id"][value="{target_id}"])'
                        )
                        form.locator('input[name="reason"]').fill(NOTE)
                        self.click(
                            staff,
                            "",
                            locator=form.get_by_role(
                                "button", name="اقتراح العلاقة دون اعتماد", exact=True
                            ),
                        )
                    self.click(reviewer, "مراجعة الاقتراحات وسجل التصحيح الخاص")
                    for kind in ("REFERENCE", "TRANSCRIPT"):
                        article = reviewer.locator("article").filter(
                            has=reviewer.get_by_role(
                                "heading", name=f"{kind} — الإصدار 1 — PROPOSED", exact=True
                            )
                        )
                        article.locator('input[name="confirm"]').check()
                        self.click(
                            reviewer,
                            "",
                            locator=article.get_by_role("button", name="اعتماد مستقل", exact=True),
                        )
                    self.click(reviewer, "العودة إلى العلاقات وموضع البحث السابق")
                    reviewer.locator("#knowledge-query").fill("فرع")
                    self.click(reviewer, "بحث")
                    self.click(reviewer, "فتح المادة المصرح بها")
                    self.assertIn("الصفحة المطبوعة", reviewer.content())
                    self.capture(reviewer, "linked-reference")
                    self.click(reviewer, "العودة إلى العلاقات وموضع البحث السابق")
                    self.assertEqual(reviewer.locator("#knowledge-query").input_value(), "فرع")
                    reviewer.locator("#knowledge-query").fill("")
                    self.click(reviewer, "بحث")
                    transcript_article = reviewer.locator("article").filter(has_text="سؤال من درس")
                    self.click(
                        reviewer,
                        "",
                        locator=transcript_article.get_by_role(
                            "button", name="فتح المادة المصرح بها", exact=True
                        ),
                    )
                    transcript_text = reviewer.locator("blockquote").inner_text()
                    self.assertTrue(transcript_text.strip())
                    self.capture(reviewer, "authorized-transcript")
                    self.click(reviewer, "العودة إلى العلاقات وموضع البحث السابق")
                    for secret in (
                        transcript_text,
                        NOTE,
                        DRAFT,
                        source["token"],
                        source["public_ref"],
                    ):
                        self.assertNotIn(secret, reviewer.content())
                    policy.allow_open = False
                    transcript_article = reviewer.locator("article").filter(has_text="سؤال من درس")
                    self.click(
                        reviewer,
                        "",
                        locator=transcript_article.get_by_role(
                            "button", name="فتح المادة المصرح بها", exact=True
                        ),
                        code=404,
                    )
                    self.assertNotIn(transcript_text, reviewer.content())

                    def canonical():
                        case = Case.objects.get(pk=source["case_id"])
                        attachment = CaseAttachment.objects.get(case=case)
                        manifest = AnswerManifest.objects.get(answer=case.approved_answer)
                        publication = PublicationEdition.objects.get(case=case)
                        binding = CompositeDelivery.objects.select_related("decision").get(
                            decision__case=case
                        )
                        parts = list(
                            AnswerPart.objects.filter(manifest=manifest).order_by("ordinal")
                        )
                        return {
                            "cases": Case.objects.count(),
                            "source_bindings": EvidenceBinding.objects.filter(case=case).count(),
                            "transcripts": TranscriptLink.objects.filter(case=case).count(),
                            "evidence_version": case.evidence_version,
                            "answer_revisions": AnswerRevision.objects.filter(case=case).count(),
                            "citations": AnswerCitation.objects.filter(
                                answer=case.approved_answer
                            ).count(),
                            "parts": len(parts),
                            "private_release": PrivateAnswerRelease.objects.filter(
                                manifest=manifest
                            ).count(),
                            "same_publication_answer": publication.answer_id
                            == case.approved_answer_id,
                            "same_delivery_answer": binding.decision.answer_id
                            == case.approved_answer_id,
                            "delivery_intents": DeliveryIntent.objects.count(),
                            "knowledge_links": KnowledgeRevision.objects.filter(
                                publication=publication
                            ).count(),
                            "knowledge_approvals": KnowledgeAction.objects.filter(
                                action="APPROVE"
                            ).count(),
                            "attachment_backend": attachment.storage_backend,
                            "answer_media_backend": parts[-1].storage_backend,
                            "external_originals": len(list(Path(private_root).rglob("*.blob"))),
                        }

                    evidence = self.sync(canonical)
                    self.assertEqual(
                        evidence,
                        {
                            "cases": 1,
                            "source_bindings": 1,
                            "transcripts": 1,
                            "evidence_version": 3,
                            "answer_revisions": 2,
                            "citations": 2,
                            "parts": 2,
                            "private_release": 1,
                            "same_publication_answer": True,
                            "same_delivery_answer": True,
                            "delivery_intents": 2,
                            "knowledge_links": 2,
                            "knowledge_approvals": 2,
                            "attachment_backend": "private-filesystem-v1",
                            "answer_media_backend": "private-filesystem-v1",
                            "external_originals": 2,
                        },
                    )
                    self.assertIn("telegram", channels)
                    self.assertEqual(external, [])
                    self.assertEqual(errors, [])
                    (OUT / "result.json").write_text(
                        json.dumps(
                            {
                                "status": "PASS",
                                "browser": browser.version,
                                "sandbox": sandbox,
                                "widths": [320, 1280],
                                "external_requests": 0,
                                "page_errors": 0,
                                "revoked_transcript_status": 404,
                                "requester_composite_verified": True,
                                "legacy_private_text_visible": False,
                                "canonical": evidence,
                            },
                            indent=2,
                        ),
                        encoding="utf-8",
                    )
                    print(
                        f"V9 connected browser PASS Chromium {browser.version} sandbox={sandbox}; offline telegram → private filesystem → transcript → research → media answer → release → signed composite → independent publication → reviewed knowledge links."
                    )
                finally:
                    browser.close()
