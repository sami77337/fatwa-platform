"""HTTP/browser checks in the new restored process, using only restored DB/assets.

No migration, seed, approval or signing operation runs here. Public verification
keys and scoped synthetic identities are explicitly reattached by the test owner.
"""

import json
import os
from dataclasses import replace
from pathlib import Path
from unittest import TestCase

from django.conf import settings
from django.db import connection, connections
from django.test import override_settings
from django.test.testcases import LiveServerThread, _StaticFilesHandler
from playwright.sync_api import sync_playwright

from apps.composite_delivery import services as composite
from apps.delivery_planner.planner import Capabilities
from apps.delivery_planner.trusted_identity import Ed25519ApprovalVerifier, IdentityStatus
from apps.delivery_queue.signed_provider_receipts import Ed25519ProviderEventVerifier
from apps.private_media.fixtures import synthetic_files
from tests.casework.test_http import WEB_SETTINGS
from tests.casework.test_v10_browser import OUT, BrowserHarness
from tests.casework.v10_fixtures import DRAFT, PRIVATE_NOTE, QUESTION, V10Directory


class RestoredDirectory(V10Directory):
    def resolve(self, subject_id):
        if subject_id == "synthetic-outsider":
            return replace(
                super().resolve("synthetic-publisher"),
                subject_id=subject_id,
                case_keys=frozenset({"unrelated-synthetic-case"}),
            )
        return super().resolve(subject_id)

    def authenticate(self, credential):
        if credential == "U" * 64:
            return self.resolve("synthetic-outsider")
        return super().authenticate(credential)


class TargetProofMiddleware:
    """Fail the HTTP request if a thread uses the source database or storage."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        proof = settings.V10_RESTORED_HTTP_PROOF
        with connection.cursor() as cursor:
            cursor.execute("SELECT current_database()")
            actual_database = cursor.fetchone()[0]
        actual_root = str(settings.FATWA_PRIVATE_MEDIA_STORAGE.root.resolve())
        assert actual_database == proof["database"] != proof["source_database"]
        assert actual_root == proof["private_root"] != proof["source_private_root"]
        proof["requests"].append((actual_database, actual_root))
        return self.get_response(request)


class RestoredHTTPChecks(BrowserHarness, TestCase):
    def exercise(self, spec, directory, proof):
        self.errors, self.external = [], []
        files = {name: raw for name, _, raw in synthetic_files()}
        server = LiveServerThread("127.0.0.1", _StaticFilesHandler)
        server.start()
        server.is_ready.wait(timeout=15)
        self.assertTrue(server.is_ready.is_set())
        self.assertIsNone(server.error)
        self.live_server_url = f"http://127.0.0.1:{server.port}"
        sandbox = os.environ.get("FATWA_BROWSER_SANDBOX", "1") != "0"
        try:
            with sync_playwright() as p:
                browser = p.chromium.launch(
                    executable_path=os.environ.get("FATWA_FASTBUILD_BROWSER", "/usr/bin/chromium"),
                    headless=True,
                    chromium_sandbox=sandbox,
                    args=["--disable-dev-shm-usage"],
                )
                try:
                    staff, requester, outsider, guest = [
                        self.context(browser).new_page() for _ in range(4)
                    ]
                    for page, credential in ((staff, "M" * 64), (outsider, "U" * 64)):
                        page.goto(self.live_server_url + "/casework/staff/login/")
                        page.locator("#credential").fill(credential)
                        self.click(page, "دخول المكتب")
                    self.click(staff, spec["public_ref"])
                    self.assert_case_header(staff, spec["public_ref"])
                    self.assertIn(QUESTION, staff.content())
                    self.assertEqual(staff.locator("#mufti-answer-revision").inner_text(), "2")
                    self.capture(staff, "restored-mufti-case")
                    requester.goto(self.live_server_url + "/casework/status/")
                    requester.locator("#portal-token").fill(spec["token"])
                    self.click(requester, "فتح قضيتي")
                    self.assertEqual(requester.locator("#authorized-answer").inner_text(), DRAFT)
                    self.assertEqual(
                        requester.locator("[data-answer-state]").get_attribute("data-answer-state"),
                        "PRIVATE_AVAILABLE",
                    )
                    self.assertEqual(
                        requester.locator("[data-delivery-state]").get_attribute(
                            "data-delivery-state"
                        ),
                        "SIGNED_DELIVERED",
                    )
                    self.assertNotIn(PRIVATE_NOTE, requester.content())
                    attachment = requester.get_by_role(
                        "link", name="فتح المرفق 1", exact=True
                    ).get_attribute("href")
                    audio = requester.locator("audio").get_attribute("src")
                    self.assertIn(spec["expected"]["attachment_id"], attachment)
                    self.assertTrue(any(part in audio for part in spec["expected"]["part_ids"]))
                    for url, expected in (
                        (attachment, files["synthetic.txt"]),
                        (audio, files["synthetic.wav"]),
                    ):
                        for page, path in (
                            (requester, url),
                            (staff, url.replace("/status/", "/staff/")),
                        ):
                            response = page.request.get(self.live_server_url + path)
                            self.assertEqual(response.status, 200)
                            self.assertEqual(response.body(), expected)
                            self.assertIn("no-store", response.headers["cache-control"])
                        for page, path in (
                            (guest, url),
                            (outsider, url.replace("/status/", "/staff/")),
                        ):
                            response = page.request.get(self.live_server_url + path)
                            self.assertEqual(response.status, 404)
                            self.assertNotEqual(response.body(), expected)
                    # Exercise the actual media element, not just an HTTP byte download.
                    requester.locator("audio").evaluate("async e => { await e.play(); }")
                    requester.wait_for_function("document.querySelector('audio').readyState >= 2")
                    self.capture(requester, "restored-private-portal")
                    self.assertNotIn(spec["public_ref"], outsider.content())
                    csrf = outsider.locator('[name="csrfmiddlewaretoken"]').first.input_value()
                    denied = outsider.request.post(
                        self.live_server_url + "/casework/staff/",
                        form={
                            "csrfmiddlewaretoken": csrf,
                            "action": "case_workspace",
                            "case_ref": spec["public_ref"],
                        },
                    )
                    self.assertEqual(denied.status, 403)
                    self.assertNotIn(QUESTION, denied.text())
                    guest.goto(self.live_server_url + "/casework/status/")
                    self.assertEqual(guest.locator("#authorized-answer").count(), 0)
                    self.assertNotIn(QUESTION, guest.content())
                    # A restored release must still depend on live, current scoped authority.
                    directory.refs = frozenset()
                    requester.reload(wait_until="domcontentloaded")
                    self.assertEqual(requester.locator("#authorized-answer").count(), 0)
                    self.assertEqual(
                        requester.request.get(self.live_server_url + audio).status, 404
                    )
                    self.capture(requester, "restored-revoked-authority")
                    self.assertEqual(self.external, [])
                    self.assertEqual(self.errors, [])
                    self.assertGreater(len(proof["requests"]), 10)
                    (OUT / "restored-http.json").write_text(
                        json.dumps(
                            {
                                "status": "PASS",
                                "browser": browser.version,
                                "sandbox": sandbox,
                                "new_process": True,
                                "restored_database_per_request": True,
                                "restored_private_root_per_request": True,
                                "checked_requests": len(proof["requests"]),
                                "explicit_public_verifiers": True,
                                "signed_delivery": "PASS",
                                "authorized_bytes": "PASS",
                                "out_of_scope_identity": "DENIED",
                                "anonymous_files": "DENIED",
                                "revoked_authority": "DENIED",
                                "external_requests": self.external,
                                "page_errors": self.errors,
                            },
                            indent=2,
                        )
                    )
                finally:
                    browser.close()
        finally:
            server.terminate()
            self.assertFalse(server.is_alive())
            connections.close_all()


def verify_restored_http(spec, storage):
    directory = RestoredDirectory()
    directory.refs = frozenset({spec["public_ref"]})

    def identity(subject):
        found = directory.resolve(subject)
        return IdentityStatus(subject, found.role, found.active) if found else None

    approval = Ed25519ApprovalVerifier(
        issuer="synthetic-mufti",
        audience="synthetic-case-return",
        trusted_public_keys={"mufti-key": bytes.fromhex(spec["approval_public_key"])},
        identity_lookup=identity,
        is_revoked_or_consumed=lambda *_: False,
    )
    provider = Ed25519ProviderEventVerifier(
        issuer="offline-composite-fixture",
        audience="synthetic-composite-delivery",
        provider=composite.SIMULATOR_PROVIDER,
        trusted_public_keys={"ephemeral-fixture": bytes.fromhex(spec["provider_public_key"])},
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
        frozenset({"text/plain", "audio/wav", "application/pdf", "image/png"}),
    )
    proof = {key: spec[key] for key in ("database", "source_database")}
    proof.update(
        private_root=str(storage.root.resolve()),
        source_private_root=str(Path(spec["source_private_root"]).resolve()),
        requests=[],
    )
    with override_settings(
        **{
            **WEB_SETTINGS,
            "ROOT_URLCONF": "config.campaign_urls",
            "MIDDLEWARE": [
                "tests.casework.v10_restored_browser.TargetProofMiddleware",
                "apps.library_preview.guard.PreviewCompositionGuard",
                "django.middleware.csrf.CsrfViewMiddleware",
            ],
            "V10_RESTORED_HTTP_PROOF": proof,
            "FATWA_MUFTI_WORKSPACE_ENABLED": True,
            "FATWA_REQUESTER_PORTAL_ENABLED": True,
            "FATWA_CASEWORK_IDENTITY_PROVIDER": directory,
            "FATWA_PRIVATE_MEDIA_STORAGE": storage,
            "FATWA_COMPOSITE_DELIVERY_ENABLED": True,
            "FATWA_CASE_DELIVERY_APPROVAL_VERIFIER": approval,
            "FATWA_COMPOSITE_DELIVERY_PROVIDER_VERIFIER": provider,
            "FATWA_COMPOSITE_DELIVERY_CAPABILITIES": lambda _: profile,
        }
    ):
        RestoredHTTPChecks().exercise(spec, directory, proof)
    print("V10_RESTORED_HTTP_BROWSER_PASS")
