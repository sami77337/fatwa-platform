"""Actual Chrome acceptance: one token sees one coarse status on two viewports."""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from pathlib import Path
import json
import os
import shutil
from urllib.parse import urlsplit

from django.db import close_old_connections, connections
from django.test import LiveServerTestCase, override_settings
from django.utils import timezone

from apps.delivery_queue import requester_tracking as tracking
from apps.delivery_queue.models import (
    RequesterTrackingCase, RequesterTrackingEvent, RequesterTrackingToken,
)

OUTPUT = Path(".local/qa/requester-tracking/browser")


@override_settings(
    ROOT_URLCONF="apps.delivery_queue.requester_urls",
    ALLOWED_HOSTS=["127.0.0.1", "localhost", "testserver"],
    MIDDLEWARE=[
        "apps.delivery_queue.requester_http.RequesterTrackingGuard",
        "django.middleware.csrf.CsrfViewMiddleware",
    ],
    CSRF_COOKIE_NAME="fatwa_tracking_csrf",
    CSRF_COOKIE_PATH="/requester/",
    CSRF_COOKIE_SAMESITE="Strict",
    CSRF_COOKIE_HTTPONLY=True,
    CSRF_COOKIE_SECURE=False,  # Test-only loopback HTTP; production remains secure.

    FATWA_REQUESTER_TRACKING_ENABLED=True,
)
class RequesterTrackingBrowserTests(LiveServerTestCase):
    host = "127.0.0.1"

    def setUp(self):
        self.alpha = tracking.provision_tracking_case(
            case_key="private-alpha",
            operator_id="synthetic-operator",
            authorize_operator=lambda who, case: who == "synthetic-operator",
            expires_at=timezone.now() + timedelta(days=1),
        )
        self.beta = tracking.provision_tracking_case(
            case_key="private-beta",
            operator_id="synthetic-operator",
            authorize_operator=lambda who, case: who == "synthetic-operator",
            expires_at=timezone.now() + timedelta(days=1),
        )
        tracking.advance_tracking_case(
            case_key="private-beta", expected_revision=1, stage="UNDER_REVIEW",
            actor_id="synthetic-operator", authorize_actor=lambda *args: True,
        )

    def snapshot(self):
        def inspect():
            close_old_connections()
            try:
                return {
                    model._meta.label: list(model.objects.order_by("pk").values())
                    for model in (
                        RequesterTrackingCase, RequesterTrackingEvent,
                        RequesterTrackingToken,
                    )
                }
            finally:
                connections.close_all()
        with ThreadPoolExecutor(max_workers=1) as pool:
            return pool.submit(inspect).result(timeout=12)

    def test_native_token_check_mobile_desktop_csrf_and_isolation(self):
        from playwright.sync_api import sync_playwright
        chrome = os.environ.get("FATWA_FASTBUILD_BROWSER") or shutil.which("google-chrome")
        self.assertTrue(chrome and Path(chrome).is_file())
        OUTPUT.mkdir(parents=True, exist_ok=True)
        evidence = {
            "status":"ERROR", "views":[], "page_errors":[],
            "external_requests":[], "journal_unchanged":False,
            "no_secret_in_response":False,
        }
        before = self.snapshot()
        origin = self.live_server_url
        expected = urlsplit(origin)
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(
                executable_path=chrome, headless=True,
                chromium_sandbox=True, args=["--disable-dev-shm-usage"],
            )
            try:
                context = browser.new_context()
                def only_origin(route):
                    uri = urlsplit(route.request.url)
                    if uri.scheme == expected.scheme and uri.netloc == expected.netloc:
                        route.continue_()
                    else:
                        evidence["external_requests"].append(route.request.url)
                        route.abort()
                context.route("**/*", only_origin)
                page = context.new_page()
                page.on("pageerror", lambda error: evidence["page_errors"].append(str(error)))
                forged = context.request.post(
                    origin + "/requester/tracking/", form={"token":self.alpha},
                )
                self.assertEqual(forged.status, 403)
                for width, height in ((320, 780), (1280, 900)):
                    page.set_viewport_size({"width":width,"height":height})
                    response = page.goto(origin + "/requester/tracking/")
                    self.assertEqual(response.status, 200)
                    self.assertIn("no-store", response.headers["cache-control"])
                    self.assertEqual(response.headers["referrer-policy"], "same-origin")
                    csrf_cookie = next(cookie for cookie in context.cookies()
                        if cookie["name"] == "fatwa_tracking_csrf")
                    self.assertFalse(csrf_cookie["secure"])
                    self.assertEqual(csrf_cookie["sameSite"], "Strict")
                    self.assertEqual(page.locator("html").get_attribute("dir"), "rtl")
                    page.keyboard.press("Tab")
                    self.assertEqual(
                        page.evaluate("document.activeElement.getAttribute('href')"),
                        "#main",
                    )
                    page.locator("#tracking-token").fill(self.alpha)
                    with page.expect_navigation():
                        page.get_by_role("button", name="استعلام عن الحالة").click()
                    body = page.locator("body").inner_text()
                    self.assertIn("RECEIVED", body)
                    self.assertNotIn("private-alpha", body)
                    self.assertNotIn("private-beta", body)
                    self.assertNotIn(self.alpha, page.content())
                    self.assertNotIn(self.beta, page.content())
                    self.assertNotIn(self.alpha, page.url)
                    self.assertLessEqual(
                        page.evaluate("document.documentElement.scrollWidth"), width,
                    )
                    page.screenshot(path=str(OUTPUT / f"status-{width}.png"), full_page=True)
                    evidence["views"].append({
                        "width":width,"height":height,
                        "rtl":True,"no_overflow":True,"scope_isolated":True,
                    })
                page.goto(origin + "/requester/tracking/")
                page.locator("#tracking-token").fill(self.beta)
                with page.expect_navigation():
                    page.get_by_role("button", name="استعلام عن الحالة").click()
                self.assertIn("UNDER_REVIEW", page.locator("body").inner_text())
                self.assertNotIn("private-alpha", page.content())
                invalid = context.request.get(origin + "/requester/tracking/?token=" + self.alpha)
                self.assertEqual(invalid.status, 400)
                self.assertEqual(evidence["page_errors"], [])
                self.assertEqual(evidence["external_requests"], [])
                context.close()
                self.assertEqual(self.snapshot(), before)
                evidence["status"] = "PASS"
                evidence["journal_unchanged"] = True
                evidence["no_secret_in_response"] = True
            finally:
                browser.close()
                (OUTPUT / "evidence.json").write_text(
                    json.dumps(evidence, ensure_ascii=False, indent=2), encoding="utf-8",
                )
