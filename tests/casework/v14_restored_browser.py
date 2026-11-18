"""Fresh target process: HTTP proof, exact restored assets, current grants and revocation.

Only public fixture verification keys are reattached. No signing, source seeding,
answer creation or approval occurs after restoration.
"""

import base64
import json
import os
import shutil
import subprocess
import sys
from datetime import datetime, timedelta
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase

from django.conf import settings
from django.db import connection, connections, transaction
from django.test import override_settings
from django.test.testcases import LiveServerThread, _StaticFilesHandler
from django.utils import timezone

from apps.composite_delivery import services as composite
from apps.delivery_planner.planner import Capabilities
from apps.delivery_planner.trusted_identity import Ed25519ApprovalVerifier, IdentityStatus
from apps.delivery_queue.signed_provider_receipts import Ed25519ProviderEventVerifier
from apps.platform_recovery import encrypted, maintenance
from apps.platform_recovery.service import RecoveryError
from apps.private_media.filesystem import FileSystemStorage
from tests.casework.test_v9_browser import KnowledgePolicy
from tests.casework.test_v14_browser import FEATURES, V14Harness
from tests.casework.v11_fixtures import (
    PRIVATE,
    RightsAuthority,
)
from tests.casework.v11_restored_browser import respect_restored_budget_window
from tests.casework.v14_fixtures import (
    APPROVED_TEXT,
    OUT,
    QUESTION,
    ClassificationPolicy,
    Directory,
    EvaluationPolicy,
    ExactRecordingRights,
    PublicationPolicy,
    SimulationPolicy,
    inventory,
    synthetic_files,
)


class TargetProofMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        proof = settings.V14_RESTORED_HTTP_PROOF
        with connection.cursor() as cursor:
            cursor.execute("SELECT current_database(), inet_server_port()")
            database, server_port = cursor.fetchone()
        private_root = str(settings.FATWA_PRIVATE_MEDIA_STORAGE.root.resolve())
        assert database == proof["database"] != proof["source_database"]
        assert private_root == proof["private_root"] != proof["source_private_root"]
        assert str(server_port) == proof["target_server_port"]
        assert str(connection.settings_dict["PORT"]) == proof["target_server_port"]
        assert proof["target_server_port"] != proof["source_server_port"]
        proof["requests"] += 1
        return self.get_response(request)


class TargetChecks(V14Harness, TestCase):
    def exercise(self, spec, directory, proof, rights):
        from playwright.sync_api import sync_playwright

        self.errors, self.external = [], []
        server = LiveServerThread("127.0.0.1", _StaticFilesHandler)
        server.start()
        server.is_ready.wait(timeout=15)
        self.assertTrue(server.is_ready.is_set())
        self.assertIsNone(server.error)
        self.live_server_url = f"http://127.0.0.1:{server.port}"
        files = {name: raw for name, _, raw in synthetic_files()}
        files["synthetic.wav"] = base64.b64decode(spec["recordings"]["answer"])
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
                    self.assertEqual(
                        requester.locator("#authorized-answer").inner_text(), APPROVED_TEXT
                    )
                    self.assertEqual(
                        requester.locator("[data-delivery-state]").get_attribute(
                            "data-delivery-state"
                        ),
                        "UNRESOLVED",
                    )
                    self.assertNotIn(PRIVATE, requester.content())
                    image = requester.locator("#attachments img")
                    image.scroll_into_view_if_needed()
                    image.evaluate("e=>e.decode()")
                    self.assertGreater(image.evaluate("e=>e.naturalWidth"), 0)
                    attachment = image.get_attribute("src")
                    audio = requester.locator("#answer audio")
                    audio_url = audio.get_attribute("src")
                    document_url = requester.locator("#answer iframe").get_attribute("src")
                    self.assertIn("1 / 3", requester.locator("#delivery").inner_text())
                    self.assertEqual(
                        self.sync(lambda: inventory(spec["expected"]["case_id"])["delivery"]),
                        spec["expected"]["delivery"],
                    )
                    self.assertTrue(
                        any(row["id"] in attachment for row in spec["expected"]["attachments"])
                    )
                    self.assertTrue(
                        any(part["id"] in audio_url for part in spec["expected"]["parts"])
                    )
                    for url, raw in (
                        (attachment, files["synthetic.png"]),
                        (audio_url, files["synthetic.wav"]),
                        (document_url, files["synthetic.pdf"]),
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
                    # Exact preserved evidence originals as well as answer media.
                    for asset in spec["expected"]["attachments"]:
                        url = "/casework/status/attachments/" + asset["id"] + "/"
                        response = requester.request.get(self.live_server_url + url)
                        self.assertEqual(response.status, 200)
                        from hashlib import sha256

                        self.assertEqual(sha256(response.body()).hexdigest(), asset["sha256"])
                    audio.evaluate("async e=>{await e.play();}")
                    self.assertGreater(audio.evaluate("e=>e.duration"), 0)
                    self.capture(requester, "restored-current-private-package")
                    self.capture(staff, "restored-current-case")
                    self.assertNotIn(spec["public_ref"], outsider.content())
                    self.action(staff, "timed_desk")
                    self.click(staff, "فتح الموضع المصرح به")
                    timed_url = staff.locator("main audio").get_attribute("src").split("#")[0]
                    self.assertEqual(timed_url, spec["final_timed"]["url"])
                    timed = staff.request.get(self.live_server_url + timed_url)
                    self.assertEqual(timed.status, 200)
                    self.assertEqual(timed.body(), base64.b64decode(spec["recordings"]["question"]))
                    self.assertEqual(
                        outsider.request.get(self.live_server_url + timed_url).status, 404
                    )
                    self.assertEqual(
                        self.sync(lambda: inventory(spec["expected"]["case_id"]))["timed"],
                        spec["expected"]["timed"],
                    )
                    self.action(staff, "pdf_desk")
                    self.click(staff, "فتح الموضع المصرح به")
                    pdf_url = (
                        staff.locator('iframe[title="معاينة ملف PDF الأصلي"]')
                        .get_attribute("src")
                        .split("#")[0]
                    )
                    self.assertEqual(pdf_url, spec["final_pdf"]["url"])
                    pdf = staff.request.get(self.live_server_url + pdf_url)
                    self.assertEqual(pdf.status, 200)
                    self.assertEqual(pdf.body(), files["synthetic.pdf"])
                    self.assertEqual(
                        outsider.request.get(self.live_server_url + pdf_url).status, 404
                    )
                    self.assertIn("الرقم المطبوع 7", staff.content())
                    self.capture(staff, "restored-pdf-citation-exact-original")
                    self.action(staff, "research_open")
                    self.click(staff, "إصدارات تقييم البحث والمراجعة البشرية")
                    self.assertIn("بانتظار المراجعة", staff.locator("main").inner_text())
                    self.assertIn("APPROVE", staff.locator("main").inner_text())
                    self.capture(staff, "restored-evaluation-history-pending-current-version")
                    # Read-only verifier reattachment cannot manufacture a sender.
                    self.assertFalse(getattr(settings, "FATWA_PILOT_WORKBENCH_ENABLED", False))
                    self.assertIsNone(getattr(settings, "FATWA_PILOT_WORKBENCH", None))
                    self.assertEqual(
                        self.sync(lambda: inventory(spec["expected"]["case_id"])["delivery"]),
                        spec["expected"]["delivery"],
                    )
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
                    self.assertEqual(
                        requester.request.get(self.live_server_url + document_url).status, 404
                    )
                    directory.refs = frozenset({spec["public_ref"]})

                    # Explicit synthetic grant withdrawal serializes on the same case lock.
                    def media_grant(enabled):
                        from apps.casework.models import Case

                        with transaction.atomic():
                            Case.objects.select_for_update().get(pk=spec["expected"]["case_id"])
                            rights.enabled = enabled

                    self.sync(lambda: media_grant(False))
                    requester.reload(wait_until="domcontentloaded")
                    self.assertEqual(requester.locator("#authorized-answer").count(), 0)
                    for path in (audio_url, document_url):
                        self.assertEqual(
                            requester.request.get(self.live_server_url + path).status, 404
                        )
                    self.assertEqual(
                        staff.request.get(self.live_server_url + timed_url).status, 404
                    )
                    self.assertEqual(staff.request.get(self.live_server_url + pdf_url).status, 404)
                    self.sync(lambda: media_grant(True))
                    # Time expiry is a different boundary from policy withdrawal.
                    # Change only this explicit synthetic grant deadline; no
                    # clock mocking, permanent ledger edit or permission broadening.
                    original_deadline = rights.deadline
                    rights.deadline = timezone.now() - timedelta(seconds=1)
                    requester.reload(wait_until="domcontentloaded")
                    self.assertEqual(requester.locator("#authorized-answer").count(), 0)
                    for path in (audio_url, document_url, timed_url, pdf_url):
                        reader = staff if path in {timed_url, pdf_url} else requester
                        self.assertEqual(
                            reader.request.get(self.live_server_url + path).status, 404
                        )
                    rights.deadline = original_deadline
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
                    self.assertEqual(
                        requester.request.get(self.live_server_url + document_url).status, 404
                    )
                    self.assertEqual(
                        self.sync(lambda: inventory(spec["expected"]["case_id"])["delivery"]),
                        spec["expected"]["delivery"],
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
                                "independent_target_server_per_request": True,
                                "target_private_root_per_request": True,
                                "checked_requests": proof["requests"],
                                **proof["budget_window"],
                                "exact_assets": "PASS",
                                "same_approved_answer": "PASS",
                                "partial_delivery_preserved": "PASS",
                                "no_automatic_retry": True,
                                "outsider": "DENIED",
                                "scope_revocation": "DENIED",
                                "rights_revocation": "DENIED",
                                "timed_media_revocation": "DENIED",
                                "timed_media_expiry": "DENIED",
                                "pdf_citation_revocation_and_expiry": "DENIED",
                                "pdf_original_bytes": "PASS",
                                "pdf_plugin_selected_page": "NOT_VERIFIED",
                                "restored_recorded_audio_bytes": "PASS",
                                "timed_and_classification_history": "PRESERVED",
                                "page_errors": self.errors,
                                "external_requests": self.external,
                                "bundled_pdf_resource_requests": len(self.bundled_pdf_requests),
                                "bundled_pdf_resource_origins": self.bundled_pdf_origins,
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

    directory.valid_until = datetime.fromisoformat(spec["identity_deadline"])
    rights = ExactRecordingRights(directory)
    simulation = SimulationPolicy(directory)
    simulation.revision_ids = frozenset(spec["simulation_revisions"])
    rights.deadline = datetime.fromisoformat(spec["media_deadline"])
    rights.pins = frozenset(tuple(pin) for pin in spec["media_pins"])

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
        frozenset({"text/plain", "audio/wav", "image/png", "application/pdf"}),
    )
    proof = {key: spec[key] for key in ("database", "source_database")}
    proof.update(
        target_server_port=str(connection.settings_dict["PORT"]),
        source_server_port=spec["source_server_port"],
        private_root=str(storage.root.resolve()),
        source_private_root=str(Path(spec["source_private_root"]).resolve()),
        requests=0,
    )
    with TemporaryDirectory(prefix="v14-restored-control-") as control:
        maintenance.initialize(root=control, storage=storage, synthetic_fixtures_only=True)
        with override_settings(
            **{
                **FEATURES,
                "MIDDLEWARE": [
                    "tests.casework.v14_restored_browser.TargetProofMiddleware",
                    *settings.MIDDLEWARE,
                ],
                "V14_RESTORED_HTTP_PROOF": proof,
                "FATWA_PRIVATE_MEDIA_STORAGE": storage,
                "FATWA_CASEWORK_IDENTITY_PROVIDER": directory,
                "FATWA_SOURCE_RIGHTS_AUTHORITY": RightsAuthority(directory),
                "FATWA_RESEARCH_WORKSPACE_RIGHTS": rights,
                "FATWA_CLASSIFICATION_REVIEW_AUTHORITY": ClassificationPolicy(directory),
                "FATWA_ARABIC_SEARCH_REVIEW_AUTHORITY": EvaluationPolicy(directory),
                "FATWA_EXPERIMENTAL_PUBLICATION_AUTHORITY": PublicationPolicy(directory),
                "FATWA_CLASSIFICATION_EDITORIAL_SIMULATION_POLICY": simulation,
                "FATWA_KNOWLEDGE_LINKS_AUTHORITY": KnowledgePolicy(directory),
                "FATWA_CASE_DELIVERY_APPROVAL_VERIFIER": approval,
                "FATWA_COMPOSITE_DELIVERY_PROVIDER_VERIFIER": provider,
                "FATWA_COMPOSITE_DELIVERY_CAPABILITIES": lambda _: profile,
                "FATWA_RECOVERY_MAINTENANCE_REQUIRED": True,
                "FATWA_RECOVERY_MAINTENANCE_ROOT": control,
            }
        ):
            proof["budget_window"] = respect_restored_budget_window()
            TargetChecks().exercise(spec, directory, proof, rights)
    print("V14_RESTORED_HTTP_PASS")


def restore_and_verify():
    """Runs under the fresh second PostgreSQL server, not the source connection."""
    spec = json.load(sys.stdin)
    assert str(connection.settings_dict["PORT"]) != spec["source_server_port"]
    scratch = Path(spec["scratch"])
    before = list(scratch.iterdir())
    with connection.cursor() as cursor:
        cursor.execute("SELECT datname FROM pg_database ORDER BY datname")
        before_databases = cursor.fetchall()
    with TemporaryDirectory(prefix="v14-wrong-key-") as keys:
        wrong_key = Path(keys) / "wrong.key"
        encrypted.generate_key(path=wrong_key, synthetic_fixtures_only=True)
        corrupted = Path(keys) / "corrupted"
        shutil.copytree(spec["bundle"], corrupted)
        ciphertext = corrupted / "backup.fernet"
        ciphertext.chmod(0o600)
        raw = bytearray(ciphertext.read_bytes())
        raw[len(raw) // 2] ^= 1
        ciphertext.write_bytes(raw)
        for bundle, key, pin in (
            (spec["bundle"], str(wrong_key), spec["ciphertext_sha256"]),
            (spec["bundle"], spec["key_file"], "0" * 64),
            (str(corrupted), spec["key_file"], spec["ciphertext_sha256"]),
        ):
            try:
                encrypted.restore(
                    bundle=bundle,
                    key_file=key,
                    expected_ciphertext_sha256=pin,
                    scratch=spec["scratch"],
                    pg_bin=spec["pg_bin"],
                    synthetic_fixtures_only=True,
                )
            except RecoveryError:
                pass
            else:
                raise AssertionError("invalid encrypted backup was accepted")
            assert list(scratch.iterdir()) == before
            with connection.cursor() as cursor:
                cursor.execute("SELECT datname FROM pg_database ORDER BY datname")
                assert cursor.fetchall() == before_databases
    restored = encrypted.restore(
        bundle=spec["bundle"],
        key_file=spec["key_file"],
        expected_ciphertext_sha256=spec["ciphertext_sha256"],
        scratch=spec["scratch"],
        pg_bin=spec["pg_bin"],
        synthetic_fixtures_only=True,
    )
    assert restored["state"] == "READY"
    # The HTTP process receives public verifier keys, never the backup key or
    # an executable sender/signer. It attaches only the restored DB and originals.
    target_spec = {
        key: value
        for key, value in spec.items()
        if key not in {"bundle", "key_file", "scratch", "pg_bin"}
    }
    target_spec.update(restored)
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            "import django; django.setup(); from tests.casework.v14_restored_browser import verify; verify()",
        ],
        input=json.dumps(target_spec),
        text=True,
        capture_output=True,
        timeout=120,
        env={
            **os.environ,
            "PGDATABASE": restored["database"],
            "PGTESTDATABASE": "test_" + restored["database"],
        },
    )
    assert result.returncode == 0, result.stderr
    assert "V14_RESTORED_HTTP_PASS" in result.stdout
    print("V14_RESTORED_HTTP_PASS")
