"""Fresh target process: HTTP proof, exact restored assets, current grants and revocation.

Only public fixture verification keys are reattached. No signing, source seeding,
answer creation or approval occurs after restoration.
"""

import json
import os
import sys
import time
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase

from django.conf import settings
from django.db import connection, connections
from django.test import override_settings
from django.test.testcases import LiveServerThread, _StaticFilesHandler

from apps.composite_delivery import services as composite
from apps.delivery_planner.planner import Capabilities
from apps.delivery_planner.trusted_identity import Ed25519ApprovalVerifier, IdentityStatus
from apps.delivery_queue.signed_provider_receipts import Ed25519ProviderEventVerifier
from apps.platform_recovery import maintenance
from apps.private_media.filesystem import FileSystemStorage
from apps.private_media.fixtures import synthetic_files
from apps.research_workspace.source_rights_adapter import SourceRightsAdapter
from tests.casework.test_v7_browser import BrowserPublicationAuthority
from tests.casework.test_v9_browser import KnowledgePolicy
from tests.casework.test_v11_browser import FEATURES, V11Harness
from tests.casework.v11_fixtures import (
    DRAFT,
    OUT,
    PRIVATE,
    QUESTION,
    Directory,
    RightsAuthority,
    inventory,
)


def respect_restored_budget_window():
    """Let preserved source request budgets expire naturally before target rehearsal.

    Read-only: no counter deletion/reset, request retry, policy override or clock patch.
    This is a new browser session, not a claim that restoring resets rate limits.
    """
    from apps.casework_web.models import ThrottleBucket

    before = list(ThrottleBucket.objects.order_by("pk").values("pk", "window", "requests"))
    now = time.time()
    current_window = int(now) // 60
    latest = max((row["window"] for row in before), default=-1)
    assert latest <= current_window, "a future restored throttle window requires clock review"
    started = time.monotonic()
    if latest == current_window:
        deadline = (current_window + 1) * 60
        while (remaining := deadline - time.time()) > 0:
            time.sleep(min(remaining, 1))
    after = list(ThrottleBucket.objects.order_by("pk").values("pk", "window", "requests"))
    assert before == after
    assert all(row["window"] < int(time.time()) // 60 for row in after)
    return {
        "throttle_wait_seconds": round(time.monotonic() - started, 3),
        "preserved_throttle_rows": len(after),
        "throttle_windows_naturally_expired": True,
    }


class TargetProofMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        proof = settings.V11_RESTORED_HTTP_PROOF
        with connection.cursor() as cursor:
            cursor.execute("SELECT current_database()")
            database = cursor.fetchone()[0]
        private_root = str(settings.FATWA_PRIVATE_MEDIA_STORAGE.root.resolve())
        assert database == proof["database"] != proof["source_database"]
        assert private_root == proof["private_root"] != proof["source_private_root"]
        proof["requests"] += 1
        return self.get_response(request)


class TargetChecks(V11Harness, TestCase):
    def exercise(self, spec, directory, proof):
        from playwright.sync_api import sync_playwright

        self.errors, self.external = [], []
        server = LiveServerThread("127.0.0.1", _StaticFilesHandler)
        server.start()
        server.is_ready.wait(timeout=15)
        self.assertTrue(server.is_ready.is_set())
        self.assertIsNone(server.error)
        self.live_server_url = f"http://127.0.0.1:{server.port}"
        files = {name: raw for name, _, raw in synthetic_files()}
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
                    staff, requester, outsider, guest, reviewer = [
                        self.context(browser).new_page() for _ in range(5)
                    ]
                    for page, credential in (
                        (staff, "M" * 64),
                        (outsider, "U" * 64),
                        (reviewer, "P" * 64),
                    ):
                        self.login(page, credential)
                    self.click(staff, spec["public_ref"])
                    self.assert_case_header(staff, spec["public_ref"])
                    self.assertEqual(
                        staff.locator("#mufti-answer-revision").inner_text(),
                        str(spec["expected"]["answer_revision"]),
                    )
                    self.assertIn(QUESTION, staff.content())
                    requester.goto(self.live_server_url + "/casework/status/")
                    requester.locator("#portal-token").fill(spec["token"])
                    self.click(requester, "فتح قضيتي")
                    self.assertEqual(requester.locator("#authorized-answer").inner_text(), DRAFT)
                    self.assertEqual(
                        requester.locator("[data-delivery-state]").get_attribute(
                            "data-delivery-state"
                        ),
                        "SIGNED_DELIVERED",
                    )
                    self.assertNotIn(PRIVATE, requester.content())
                    image = requester.locator("#attachments img")
                    image.scroll_into_view_if_needed()
                    image.evaluate("e=>e.decode()")
                    self.assertGreater(image.evaluate("e=>e.naturalWidth"), 0)
                    attachment = image.get_attribute("src")
                    audio = requester.locator("#answer audio")
                    audio_url = audio.get_attribute("src")
                    self.assertIn(spec["expected"]["attachments"][0]["id"], attachment)
                    self.assertTrue(
                        any(part["id"] in audio_url for part in spec["expected"]["parts"])
                    )
                    for url, raw in (
                        (attachment, files["synthetic.png"]),
                        (audio_url, files["synthetic.wav"]),
                    ):
                        for page, path in (
                            (requester, url),
                            (staff, url.replace("/status/", "/staff/")),
                        ):
                            response = page.request.get(self.live_server_url + path)
                            self.assertEqual(response.status, 200)
                            self.assertEqual(response.body(), raw)
                            self.assertIn("no-store", response.headers["cache-control"])
                        for page, path in (
                            (guest, url),
                            (outsider, url.replace("/status/", "/staff/")),
                        ):
                            self.assertEqual(
                                page.request.get(self.live_server_url + path).status, 404
                            )
                    audio.evaluate("async e=>{await e.play();}")
                    self.assertGreater(audio.evaluate("e=>e.duration"), 0)
                    self.capture(requester, "restored-current-private-package")
                    self.capture(staff, "restored-current-case")
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
                    # Scope revocation must close existing requester and native media access.
                    directory.refs = frozenset()
                    requester.reload(wait_until="domcontentloaded")
                    self.assertEqual(requester.locator("#authorized-answer").count(), 0)
                    self.assertEqual(
                        requester.request.get(self.live_server_url + audio_url).status, 404
                    )
                    directory.refs = frozenset({spec["public_ref"]})
                    self.click(reviewer, spec["public_ref"])
                    self.action(reviewer, "rights_desk")
                    review = self.form(reviewer, "rights_review")
                    review.locator('[name="decision"]').select_option("REVOKE")
                    review.locator('[name="note"]').fill(
                        "سحب بشري اصطناعي بعد التحقق من الاستعادة."
                    )
                    review.locator('[name="confirm"]').check()
                    self.submit_form(reviewer, "rights_review")
                    self.assertIn("REVOKED", reviewer.content())
                    requester.reload(wait_until="domcontentloaded")
                    self.assertEqual(requester.locator("#authorized-answer").count(), 0)
                    self.assertEqual(
                        requester.request.get(self.live_server_url + audio_url).status, 404
                    )
                    self.open_case(staff, spec["public_ref"])
                    self.action(staff, "research_open")
                    self.assertEqual(staff.locator("#edition option").count(), 1)
                    self.capture(requester, "restored-rights-revoked")
                    self.assertEqual(self.errors, [])
                    self.assertEqual(self.external, [])
                    self.assertGreater(proof["requests"], 20)
                    (OUT / "restored-http.json").write_text(
                        json.dumps(
                            {
                                "status": "PASS",
                                "browser": browser.version,
                                "sandbox": sandbox,
                                "new_process": True,
                                "target_database_per_request": True,
                                "target_private_root_per_request": True,
                                "checked_requests": proof["requests"],
                                **proof["budget_window"],
                                "exact_assets": "PASS",
                                "same_approved_answer": "PASS",
                                "signed_delivery": "PASS",
                                "outsider": "DENIED",
                                "scope_revocation": "DENIED",
                                "rights_revocation": "DENIED",
                                "page_errors": self.errors,
                                "external_requests": self.external,
                            },
                            indent=2,
                        )
                    )
                finally:
                    browser.close()
        finally:
            server.terminate()
            connections.close_all()


def verify():
    spec = json.load(sys.stdin)
    assert connection.settings_dict["NAME"] == spec["database"] != spec["source_database"]
    assert inventory(spec["expected"]["case_id"]) == spec["expected"]
    storage = FileSystemStorage(spec["private_root"], synthetic_fixtures_only=True)
    directory = Directory()
    directory.refs = frozenset({spec["public_ref"]})

    def identity(subject):
        actor = directory.resolve(subject)
        return IdentityStatus(subject, actor.role, actor.active) if actor else None

    approval = Ed25519ApprovalVerifier(
        issuer="synthetic-pilot-return-fixture",
        audience="synthetic-pilot-composite",
        trusted_public_keys={"ephemeral-pilot": bytes.fromhex(spec["approval_public_key"])},
        identity_lookup=identity,
        is_revoked_or_consumed=lambda *_: spec["public_ref"] not in directory.refs,
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
        frozenset({"text/plain", "audio/wav", "image/png"}),
    )
    proof = {key: spec[key] for key in ("database", "source_database")}
    proof.update(
        private_root=str(storage.root.resolve()),
        source_private_root=str(Path(spec["source_private_root"]).resolve()),
        requests=0,
    )
    with TemporaryDirectory(prefix="v11-restored-control-") as control:
        maintenance.initialize(root=control, storage=storage, synthetic_fixtures_only=True)
        with override_settings(
            **{
                **FEATURES,
                "MIDDLEWARE": [
                    "tests.casework.v11_restored_browser.TargetProofMiddleware",
                    *settings.MIDDLEWARE,
                ],
                "V11_RESTORED_HTTP_PROOF": proof,
                "FATWA_PRIVATE_MEDIA_STORAGE": storage,
                "FATWA_CASEWORK_IDENTITY_PROVIDER": directory,
                "FATWA_SOURCE_RIGHTS_AUTHORITY": RightsAuthority(directory),
                "FATWA_RESEARCH_WORKSPACE_RIGHTS": SourceRightsAdapter(),
                "FATWA_EXPERIMENTAL_PUBLICATION_AUTHORITY": BrowserPublicationAuthority(directory),
                "FATWA_KNOWLEDGE_LINKS_AUTHORITY": KnowledgePolicy(directory),
                "FATWA_CASE_DELIVERY_APPROVAL_VERIFIER": approval,
                "FATWA_COMPOSITE_DELIVERY_PROVIDER_VERIFIER": provider,
                "FATWA_COMPOSITE_DELIVERY_CAPABILITIES": lambda _: profile,
                "FATWA_RECOVERY_MAINTENANCE_REQUIRED": True,
                "FATWA_RECOVERY_MAINTENANCE_ROOT": control,
            }
        ):
            proof["budget_window"] = respect_restored_budget_window()
            TargetChecks().exercise(spec, directory, proof)
    print("V11_RESTORED_HTTP_PASS")
