"""Protected native teaching creation/review, exact originals and public navigation."""

import json
import os
from hashlib import sha256
from pathlib import Path
from urllib.parse import urlsplit

from django.test import LiveServerTestCase, override_settings

from apps.answer_media import services as media
from apps.public_answer_media.browser_tests import PublicAnswerMediaBrowserTests
from apps.public_answer_media.test_support import audio
from apps.scholarly_links.models import SeriesVersion

from . import services
from .models import TeachingAction, TeachingItem, TeachingVersion
from .test_support import CREDENTIALS, FEATURES, MATERIAL, TeachingFixture

OUT = Path(".local/qa/functional-continuation/public-teaching-browser")


@override_settings(**FEATURES)
class PublicTeachingBrowserTests(TeachingFixture, LiveServerTestCase):
    host = "127.0.0.1"
    sync = PublicAnswerMediaBrowserTests.sync
    submit = PublicAnswerMediaBrowserTests.submit
    send = PublicAnswerMediaBrowserTests.send
    media_state = PublicAnswerMediaBrowserTests.media_state

    def capture(self, page, label, proof):
        for width in (320, 1280):
            page.set_viewport_size({"width": width, "height": 900})
            self.assertEqual(page.locator("html").get_attribute("dir"), "rtl")
            self.assertLessEqual(page.evaluate("document.documentElement.scrollWidth"), width)
            name = f"{label}-{width}.png"
            page.screenshot(path=str(OUT / name), full_page=True)
            proof["screenshots"].append(name)

    def login(self, page, subject):
        page.goto(self.live_server_url + "/casework/staff/login/")
        page.locator("#credential").fill(CREDENTIALS[subject])
        self.submit(page, page.get_by_role("button", name="دخول المكتب", exact=True))

    def open_desk(self, page):
        response = page.goto(self.live_server_url + "/casework/staff/")
        self.assertEqual(response.status, 200)
        self.submit(page, page.get_by_role("button", name=self.receipt["public_ref"], exact=True))
        self.submit(
            page, page.get_by_role("button", name="مواد العلماء والدروس المنشورة", exact=True)
        )

    def create(self, page, kind, title, choices, *, members=(), attribution=""):
        self.open_desk(page)
        details = page.locator(f'details:has(form.teaching-save[data-kind="{kind}"])')
        details.locator("summary").click()
        form = details.locator("form.teaching-save")
        form.locator('[name="title"]').fill(title)
        form.locator('[name="summary"]').fill("وصف عام اصطناعي اختاره المحرر دون بيانات خاصة")
        for name, value in choices.items():
            self.assertEqual(
                form.locator(f'select[name="{name}"] option[value="{value}"]').count(), 1
            )
            form.locator(f'[name="{name}"]').select_option(value)
        if attribution:
            form.locator('[name="attribution"]').fill(attribution)
        if members:
            form.locator('[name="topic"]').fill("موضوع عام تجريبي")
            for value in members:
                self.assertEqual(
                    form.locator(f'select[name="members"] option[value="{value}"]').count(), 1
                )
            form.locator('[name="members"]').select_option(list(members))
        form.locator('[name="note"]').fill("اختيار بشري للنسخة والنسبة أو الترتيب المحدد")
        form.locator('[name="confirmed"]').check()
        self.send(page, form)
        article = page.locator(f'article[data-kind="{kind}"]').filter(has_text=title)
        self.assertEqual(article.count(), 1)
        return article.get_attribute("data-teaching-id"), article.get_attribute("data-public-id")

    def native_decision(self, page, identifier, command):
        self.open_desk(page)
        form = page.locator(
            f'article[data-teaching-id="{identifier}"] form.teaching-decision[data-command="{command}"]'
        )
        self.assertEqual(form.count(), 1)
        form.locator('[name="note"]').fill(
            "راجعت النسخة والنسبة وحقوق الإتاحة الحالية بصورة مستقلة"
        )
        form.locator('[name="confirmed"]').check()
        self.send(page, form)

    def click(self, page, link):
        self.assertEqual(link.count(), 1)
        with page.expect_navigation(wait_until="domcontentloaded") as navigation:
            link.press("Enter")
        self.assertEqual(navigation.value.status, 200)
        return navigation.value

    def test_native_scholar_material_ordered_series_actual_lesson_playback_and_revocation(self):
        from playwright.sync_api import sync_playwright

        scholar, first_metadata, second_metadata = self.metadata()
        material = self.material()
        series = (
            SeriesVersion.objects.filter(series_id=self.first.lesson.series_id)
            .order_by("-number")
            .first()
        )
        source_hash = sha256(media.raw_for_part(self.part)).hexdigest()
        source_version_ids = [str(row.pk) for row in (scholar, first_metadata, second_metadata)]
        OUT.mkdir(parents=True, exist_ok=True)
        proof = {
            "status": "ERROR",
            "sandbox": True,
            "protected_browser": True,
            "widths": [320, 1280],
            "screenshots": [],
            "trace": "trace.zip",
            "traces": [],
            "external_requests": [],
            "page_errors": [],
            "source_version_ids": source_version_ids,
            "original_audio_sha256": source_hash,
            "original_material_sha256": sha256(MATERIAL).hexdigest(),
        }
        contexts = []
        origin = self.live_server_url
        try:
            with sync_playwright() as playwright:
                browser = playwright.chromium.launch(
                    executable_path=os.environ["FATWA_FASTBUILD_BROWSER"],
                    chromium_sandbox=True,
                    args=["--disable-dev-shm-usage"],
                )
                try:

                    def local_only(route):
                        parsed = urlsplit(route.request.url)
                        if parsed.scheme != "http" or parsed.netloc != urlsplit(origin).netloc:
                            proof["external_requests"].append("blocked")
                            route.abort()
                        else:
                            route.continue_()

                    def page_for(label):
                        context = browser.new_context(
                            viewport={"width": 320, "height": 900}, accept_downloads=True
                        )
                        context.route("**/*", local_only)
                        context.tracing.start(screenshots=True, snapshots=True, sources=True)
                        contexts.append((label, context))
                        page = context.new_page()
                        page.on(
                            "pageerror",
                            lambda error: proof["page_errors"].append(type(error).__name__),
                        )
                        return page

                    editor, reviewer, publisher, reader = [
                        page_for(label) for label in ("editor", "reviewer", "publisher", "public")
                    ]
                    for page, subject in (
                        (editor, "editor"),
                        (reviewer, "other"),
                        (publisher, "publisher"),
                    ):
                        self.login(page, subject)
                    attribution = self.create(
                        editor,
                        "SCHOLAR_MATERIAL",
                        "مادة عامة ذات نسبة مراجعة",
                        {
                            "profile": services.selection(scholar),
                            "material": services.selection(material),
                        },
                        attribution="نسبة بشرية صريحة للنسخة المحددة",
                    )
                    first = self.create(
                        editor,
                        "LESSON",
                        "الدرس العام الأول",
                        {"lesson": services.selection(first_metadata)},
                    )
                    second = self.create(
                        editor,
                        "LESSON",
                        "الدرس العام الثاني",
                        {"lesson": services.selection(second_metadata)},
                    )
                    self.capture(editor, "native-reviewed-source-choices", proof)
                    for identifier, _ in (attribution, first, second):
                        self.native_decision(reviewer, identifier, "REVIEW")
                        self.native_decision(publisher, identifier, "APPROVE")
                        self.native_decision(publisher, identifier, "RELEASE")
                    member_tokens = self.sync(
                        lambda: [
                            services.selection(TeachingVersion.objects.get(pk=identifier))
                            for identifier, _ in (first, second)
                        ]
                    )
                    ordered = self.create(
                        editor,
                        "SERIES",
                        "سلسلة دروس بترتيب موثق",
                        {"series": services.selection(series)},
                        members=member_tokens,
                    )
                    for page, command in (
                        (reviewer, "REVIEW"),
                        (publisher, "APPROVE"),
                        (publisher, "RELEASE"),
                    ):
                        self.native_decision(page, ordered[0], command)

                    self.assertEqual(reader.goto(origin + "/library-preview/").status, 200)
                    self.click(reader, reader.locator('a[href="/library-preview/teaching/"]'))
                    self.capture(reader, "public-teaching-catalogue", proof)
                    self.click(
                        reader,
                        reader.get_by_role("link", name="سلسلة دروس بترتيب موثق", exact=True),
                    )
                    self.assertEqual(
                        reader.locator("#series-lessons li").evaluate_all(
                            "rows => rows.map(row => row.dataset.lessonId)"
                        ),
                        [first[1], second[1]],
                    )
                    self.capture(reader, "exact-series-order", proof)
                    with reader.expect_response(
                        lambda response: response.url.endswith(f"/lessons/{first[1]}/1/media/")
                    ) as original:
                        self.click(
                            reader, reader.get_by_role("link", name="الدرس العام الأول", exact=True)
                        )
                    self.assertEqual(original.value.status, 206)
                    self.assertEqual(original.value.body(), audio())
                    state = self.media_state(reader)
                    self.assertTrue(state["paused"])
                    player = reader.locator("audio[controls]")
                    self.assertIsNone(player.get_attribute("autoplay"))
                    proof["native_controls_geometry"] = []
                    for width in (320, 1280):
                        reader.set_viewport_size({"width": width, "height": 900})
                        player.scroll_into_view_if_needed()
                        self.assertTrue(player.is_visible())
                        self.assertTrue(player.evaluate("e => e.controls"))
                        box = player.bounding_box()
                        self.assertIsNotNone(box)
                        self.assertGreaterEqual(box["height"], 32)
                        self.assertGreaterEqual(box["width"], 128)
                        self.assertGreaterEqual(box["x"], 0)
                        self.assertLessEqual(box["x"] + box["width"], width)
                        proof["native_controls_geometry"].append({"viewport": width, **box})
                    player.press("Space")
                    for _ in range(100):
                        state = player.evaluate(
                            "e => ({time:e.currentTime,paused:e.paused,error:e.error?.code || null})"
                        )
                        if state["time"] >= 0.15 and not state["paused"] and state["error"] is None:
                            player.press("Space")
                            break
                        reader.wait_for_timeout(50)
                    else:
                        self.fail(f"actual native lesson playback did not advance: {state!r}")
                    proof["actual_native_playback"] = {
                        "time": state["time"],
                        "native_keyboard": True,
                        "exact_source_sha256": source_hash,
                    }
                    self.capture(reader, "actual-original-lesson", proof)
                    self.click(reader, reader.locator('a[rel="next"]'))
                    self.assertIn(second[1], reader.url)
                    self.click(reader, reader.locator('a[rel="prev"]'))
                    self.assertIn(first[1], reader.url)

                    self.click(
                        reader,
                        reader.get_by_role("link", name="العودة إلى الدروس والسلاسل", exact=True),
                    )
                    self.click(
                        reader, reader.get_by_role("link", name=scholar.payload["name"], exact=True)
                    )
                    self.assertEqual(
                        reader.get_by_role("heading", name="الفتاوى المنسوبة", exact=True).count(),
                        1,
                    )
                    self.assertEqual(
                        reader.get_by_role("heading", name="الدروس المنسوبة", exact=True).count(), 1
                    )
                    self.assertEqual(
                        reader.locator("#scholar-general-materials article").count(), 1
                    )
                    self.assertNotIn("PRIVATE", reader.locator("main").inner_text())
                    self.capture(reader, "scholar-fatwas-lessons-material", proof)
                    self.click(
                        reader,
                        reader.get_by_role("link", name="المادة العامة المنسوبة", exact=True),
                    )
                    with reader.expect_download() as copied:
                        reader.get_by_role("link", name="تنزيل الملف المصرح به", exact=True).click()
                    raw = Path(copied.value.path()).read_bytes()
                    self.assertEqual(raw, MATERIAL)
                    proof["actual_material_download_sha256"] = sha256(raw).hexdigest()

                    self.native_decision(publisher, first[0], "WITHDRAW")
                    refused = reader.goto(origin + f"/library-preview/teaching/lessons/{first[1]}/")
                    self.assertEqual(refused.status, 404)
                    refused_bytes = reader.context.request.get(
                        origin + f"/library-preview/teaching/lessons/{first[1]}/1/media/",
                        headers={"Range": "bytes=0-43"},
                    )
                    self.assertEqual(refused_bytes.status, 404)
                    self.assertNotEqual(refused_bytes.body(), audio()[:44])
                    self.assertEqual(
                        reader.goto(
                            origin + f"/library-preview/teaching/series/{ordered[1]}/"
                        ).status,
                        404,
                    )
                    self.assertEqual(
                        self.sync(lambda: sha256(media.raw_for_part(self.part)).hexdigest()),
                        source_hash,
                    )
                    self.assertEqual(
                        self.sync(
                            lambda: (
                                TeachingItem.objects.count(),
                                TeachingVersion.objects.count(),
                                TeachingAction.objects.count(),
                            )
                        ),
                        (4, 4, 13),
                    )
                    self.assertEqual(proof["external_requests"], [])
                    self.assertEqual(proof["page_errors"], [])
                    proof.update(
                        status="PASS",
                        independent_native_review=True,
                        native_public_entry=True,
                        exact_series_order=[first[1], second[1]],
                        previous_next_stable_ids=True,
                        withdrawn_lesson_and_dependent_series_denied=True,
                        original_sources_unchanged=True,
                    )
                finally:
                    for label, context in contexts:
                        name = "trace.zip" if label == "editor" else f"trace-{label}.zip"
                        context.tracing.stop(path=str(OUT / name))
                        proof["traces"].append(name)
                        context.close()
                    browser.close()
        finally:
            (OUT / "result.json").write_text(json.dumps(proof, ensure_ascii=False, indent=2) + "\n")
