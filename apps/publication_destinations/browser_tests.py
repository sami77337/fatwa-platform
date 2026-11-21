"""Protected native, independently signed per-destination simulation journey."""

import json
import os
from pathlib import Path
from urllib.parse import urlsplit

from django.test import LiveServerTestCase, override_settings

from apps.public_answer_media.browser_tests import PublicAnswerMediaBrowserTests

from . import services
from .models import DestinationEvent, DestinationRecord, DestinationVersion
from .recovery_support import digest, source_rows
from .test_support import CREDENTIALS, FEATURES, Fixture

OUT = Path(".local/qa/functional-continuation/publication-destinations-browser")


@override_settings(**{**FEATURES, "ROOT_URLCONF": "config.campaign_urls"})
class PublicationDestinationsBrowserTests(Fixture, LiveServerTestCase):
    host = "127.0.0.1"
    sync = PublicAnswerMediaBrowserTests.sync
    submit = PublicAnswerMediaBrowserTests.submit
    send = PublicAnswerMediaBrowserTests.send

    def capture(self, page, label, proof):
        for width in (320, 1280):
            page.set_viewport_size({"width": width, "height": 900})
            self.assertEqual(page.locator("html").get_attribute("dir"), "rtl")
            self.assertLessEqual(page.evaluate("document.documentElement.scrollWidth"), width)
            name = f"{label}-{width}.png"
            page.screenshot(path=str(OUT / name), full_page=True)
            proof["screenshots"].append(name)

    def login_browser(self, page, subject):
        self.assertEqual(page.goto(self.live_server_url + "/casework/staff/login/").status, 200)
        page.locator("#credential").fill(CREDENTIALS[subject])
        self.submit(page, page.get_by_role("button", name="دخول المكتب", exact=True))

    def open_desk(self, page):
        self.assertEqual(page.goto(self.live_server_url + "/casework/staff/").status, 200)
        self.submit(page, page.get_by_role("button", name=self.receipt["public_ref"], exact=True))
        self.submit(
            page, page.get_by_role("button", name="سجلات النشر المستقلة للوجهات", exact=True)
        )
        self.assertEqual(
            page.locator("#destination-simulation").get_attribute(
                "data-external-publication-verified"
            ),
            "false",
        )
        self.assertNotIn("PRIVATE SYNTHETIC", page.locator("main").inner_text())

    def select_native(self, page, destination, source):
        self.open_desk(page)
        record = page.locator(f'section[data-destination="{destination}"]')
        form = record.locator("form.destination-select")
        selected = services.selection(source)
        self.assertEqual(form.locator(f'option[value="{selected}"]').count(), 1)
        form.locator('[name="source_selection"]').select_option(selected)
        form.locator('[name="note"]').fill("اختيار بشري لنص عام محدد لهذه الوجهة")
        form.locator('[name="confirmed"]').check()
        self.send(page, form)
        article = page.locator(
            f'section[data-destination="{destination}"] article[data-destination-version]'
        ).first
        self.assertEqual(article.locator(".destination-public-copy").inner_text(), source.body)
        return article.get_attribute("data-destination-version")

    def decision_native(self, page, identifier, command):
        self.open_desk(page)
        form = page.locator(
            f'article[data-destination-version="{identifier}"] form.destination-decision[data-command="{command}"]'
        )
        self.assertEqual(form.count(), 1)
        form.locator('[name="note"]').fill("راجعت النسخة والوجهة وتفويضي الحالي بصورة مستقلة")
        form.locator('[name="confirmed"]').check()
        self.send(page, form)

    def outcome_native(self, page, identifier, reported, *, forged=False):
        self.open_desk(page)
        article = page.locator(f'article[data-destination-version="{identifier}"]')
        details = article.locator("details:has(form.destination-provider-event)")
        details.locator("summary").click()
        form = details.locator("form.destination-provider-event")
        envelope = (
            {"reported": "PUBLISHED", "verified": True}
            if forged
            else self.sync(
                lambda: self.signed(
                    DestinationVersion.objects.select_related("record", "source").get(
                        pk=identifier
                    ),
                    reported,
                )
            )
        )
        form.locator('[name="envelope"]').fill(json.dumps(envelope))
        form.locator('[name="note"]').fill("نتيجة محاكاة موقعة للخطة والنسخة والوجهة المحددة")
        form.locator('[name="confirmed"]').check()
        if forged:
            with page.expect_navigation(wait_until="domcontentloaded") as navigation:
                form.locator("button").press("Enter")
            self.assertEqual(navigation.value.status, 409)
            self.assertNotIn("SIMULATED_PUBLISHED", page.content())
            return
        self.send(page, form)
        expected = "SIMULATED_PUBLISHED" if reported == "PUBLISHED" else reported
        self.assertEqual(
            page.locator(f'article[data-destination-version="{identifier}"]').get_attribute(
                "data-state"
            ),
            expected,
        )

    def test_native_distinct_destination_versions_signed_outcomes_correction_and_withdrawal_isolation(
        self,
    ):
        from playwright.sync_api import sync_playwright

        self.seed_delivery()
        corrected_source = self.edition("نص قناة مصحح اصطناعي مستقل بعد النسخة الأولى.")
        case = {key: self.receipt[key] for key in ("case_id", "public_ref")}
        original_state = source_rows(case)
        OUT.mkdir(parents=True, exist_ok=True)
        proof = dict(
            status="ERROR",
            sandbox=True,
            protected_browser=True,
            widths=[320, 1280],
            screenshots=[],
            traces=[],
            trace="trace.zip",
            external_requests=[],
            page_errors=[],
            console_errors=[],
            external_publication_verified=False,
        )
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
                        context = browser.new_context(viewport={"width": 320, "height": 900})
                        context.route("**/*", local_only)
                        context.tracing.start(screenshots=True, snapshots=True, sources=True)
                        contexts.append((label, context))
                        page = context.new_page()
                        page.on(
                            "pageerror",
                            lambda error: proof["page_errors"].append(type(error).__name__),
                        )
                        return page

                    editor, reviewer, publisher = [
                        page_for(label) for label in ("editor", "reviewer", "publisher")
                    ]
                    for page, subject in (
                        (editor, "editor"),
                        (reviewer, "other"),
                        (publisher, "publisher"),
                    ):
                        self.login_browser(page, subject)
                    website = self.select_native(editor, "WEBSITE", self.first)
                    channel = self.select_native(editor, "TELEGRAM_CHANNEL", self.second)
                    for identifier in (website, channel):
                        self.decision_native(reviewer, identifier, "REVIEW")
                        self.decision_native(publisher, identifier, "APPROVE")
                        self.decision_native(publisher, identifier, "PREPARE")
                    self.outcome_native(publisher, website, "PUBLISHED", forged=True)
                    self.outcome_native(publisher, website, "ACCEPTED")
                    self.assertEqual(
                        publisher.locator(
                            'section[data-destination="WEBSITE"] .destination-current'
                        ).get_attribute("data-current-version"),
                        "",
                    )
                    self.capture(publisher, "accepted-is-not-published", proof)
                    self.outcome_native(publisher, website, "PUBLISHED")
                    self.outcome_native(publisher, channel, "FAILED")
                    self.assertEqual(
                        publisher.locator(
                            'section[data-destination="WEBSITE"] .destination-current'
                        ).get_attribute("data-current-version"),
                        "1",
                    )
                    self.assertEqual(
                        publisher.locator(
                            'section[data-destination="TELEGRAM_CHANNEL"] .destination-current'
                        ).get_attribute("data-current-version"),
                        "",
                    )
                    self.assertEqual(
                        publisher.locator(
                            f'article[data-destination-version="{website}"] .destination-public-copy'
                        ).inner_text(),
                        self.first.body,
                    )
                    self.assertEqual(
                        publisher.locator(
                            f'article[data-destination-version="{channel}"] .destination-public-copy'
                        ).inner_text(),
                        self.second.body,
                    )
                    self.capture(publisher, "distinct-destination-results", proof)

                    correction = self.select_native(editor, "TELEGRAM_CHANNEL", corrected_source)
                    self.decision_native(reviewer, correction, "REVIEW")
                    self.decision_native(publisher, correction, "APPROVE")
                    self.decision_native(publisher, correction, "PREPARE")
                    self.outcome_native(publisher, correction, "PUBLISHED")
                    self.assertEqual(
                        publisher.locator(
                            f'article[data-destination-version="{channel}"]'
                        ).get_attribute("data-state"),
                        "FAILED",
                    )
                    self.assertEqual(
                        publisher.locator(
                            'section[data-destination="TELEGRAM_CHANNEL"] .destination-current'
                        ).get_attribute("data-current-version"),
                        "2",
                    )
                    self.capture(publisher, "corrected-independent-channel", proof)
                    self.decision_native(publisher, correction, "WITHDRAW")
                    self.assertEqual(
                        publisher.locator(
                            'section[data-destination="WEBSITE"] .destination-current'
                        ).get_attribute("data-current-version"),
                        "1",
                    )
                    self.assertEqual(
                        publisher.locator(
                            'section[data-destination="TELEGRAM_CHANNEL"] .destination-current'
                        ).get_attribute("data-current-version"),
                        "",
                    )
                    self.capture(publisher, "destination-withdrawal-isolation", proof)
                    self.assertEqual(self.sync(lambda: source_rows(case)), original_state)

                    # Source withdrawal uses the existing independent publication form.
                    self.submit(
                        publisher,
                        publisher.get_by_role(
                            "button",
                            name="تحرير نسخة عامة ومراجعتها قبل اختيارها للوجهة",
                            exact=True,
                        ),
                    )
                    form = publisher.locator(
                        f'form:has(input[name="action"][value="pub_withdraw"]):has(input[name="edition_id"][value="{self.first.pk}"])'
                    )
                    self.assertEqual(form.count(), 1)
                    form.locator('[name="confirm"]').check()
                    self.send(publisher, form)
                    self.open_desk(publisher)
                    self.assertEqual(
                        publisher.locator(
                            f'article[data-destination-version="{website}"]'
                        ).get_attribute("data-state"),
                        "UNAVAILABLE",
                    )
                    self.assertEqual(
                        publisher.locator(
                            f'article[data-destination-version="{website}"] .destination-public-copy'
                        ).count(),
                        0,
                    )
                    self.assertEqual(
                        publisher.locator(
                            f'article[data-destination-version="{channel}"]'
                        ).get_attribute("data-state"),
                        "FAILED",
                    )
                    self.capture(publisher, "exact-source-withdrawal", proof)
                    self.assertEqual(
                        self.sync(lambda: source_rows(case)["delivery"]), original_state["delivery"]
                    )
                    self.authority.denied.add("READ")
                    with publisher.expect_navigation(wait_until="domcontentloaded") as navigation:
                        publisher.get_by_role(
                            "button", name="تحديث سجلات المحاكاة", exact=True
                        ).press("Enter")
                    self.assertEqual(navigation.value.status, 409)
                    self.assertNotIn(self.first.body, publisher.content())
                    self.assertNotIn(self.second.body, publisher.content())
                    self.authority.denied.clear()
                    self.open_desk(publisher)
                    counts = self.sync(
                        lambda: [
                            DestinationRecord.objects.count(),
                            DestinationVersion.objects.count(),
                            DestinationEvent.objects.count(),
                        ]
                    )
                    self.assertEqual(counts, [2, 3, 14])
                    self.assertEqual(proof["external_requests"], [])
                    self.assertEqual(proof["page_errors"], [])
                    proof.update(
                        status="PASS",
                        native_distinct_copies=True,
                        current_profile_and_source_actors=True,
                        accepted_not_publication=True,
                        independent_failure_preserved=True,
                        corrected_version_history_retained=True,
                        destination_withdrawal_isolated=True,
                        exact_source_withdrawal=True,
                        unsigned_success_denied=True,
                        revoked_reader_denied=True,
                        original_delivery_sha256=digest(original_state["delivery"]),
                        record_count=2,
                        version_count=3,
                        event_count=14,
                    )
                finally:
                    for index, (label, context) in enumerate(contexts):
                        trace = "trace.zip" if index == 0 else f"trace-{label}.zip"
                        context.tracing.stop(path=str(OUT / trace))
                        proof["traces"].append(trace)
                        context.close()
                    browser.close()
        finally:
            (OUT / "result.json").write_text(json.dumps(proof, ensure_ascii=False, indent=2) + "\n")
