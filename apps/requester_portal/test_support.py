"""Synthetic fixture helpers only; no signer or identity enabled by the profile."""

from django.test import Client, override_settings

from apps.answer_media import services as media
from apps.answer_media.models import AnswerManifest
from apps.casework import services as cases
from apps.composite_delivery import services as composite
from apps.composite_delivery import tests as contracts
from apps.composite_delivery.simulator import OfflineProviderSimulator
from apps.delivery_planner.planner import Capabilities
from tests.casework.delivery_fixtures import CaseDeliveryFixture
from tests.casework.test_http import WEB_SETTINGS, post

PORTAL_SETTINGS = {
    **WEB_SETTINGS,
    "ROOT_URLCONF": "apps.requester_portal.urls",
    "FATWA_REQUESTER_PORTAL_ENABLED": True,
    "FATWA_CASE_ATTACHMENTS_ENABLED": True,
    "FATWA_CASE_CITATIONS_ENABLED": True,
    "FATWA_COMPOSITE_DELIVERY_ENABLED": True,
    "FATWA_ANSWER_MEDIA_ENABLED": True,
    "FATWA_ANSWER_MEDIA_PRIVATE_ENABLED": True,
}


class PortalFixture(CaseDeliveryFixture):
    save = contracts.CompositeTests.save
    approve = contracts.CompositeTests.approve
    request = contracts.CompositeTests.request
    stage = contracts.CompositeTests.stage
    reserve = contracts.CompositeTests.reserve
    resolve = contracts.CompositeTests.resolve
    record = contracts.CompositeTests.record
    outcome = contracts.CompositeTests.outcome

    def setUp(self):
        super().setUp()
        self.profile = composite.ChannelProfile(
            Capabilities(
                composite.SIMULATOR_PROVIDER,
                "synthetic.v1",
                frozenset({"text", "document", "audio", "image"}),
                6000,
                True,
            ),
            192000,
            frozenset({"text/plain", "audio/wav"}),
        )
        self.simulator = OfflineProviderSimulator(synthetic_fixtures_only=True)
        self.channel_verifier = self.simulator.verifier
        configured = override_settings(
            FATWA_CASEWORK_IDENTITY_PROVIDER=self.directory,
            FATWA_COMPOSITE_DELIVERY_CAPABILITIES=lambda _: self.profile,
            FATWA_COMPOSITE_DELIVERY_PROVIDER_VERIFIER=self.channel_verifier,
            FATWA_CASEWORK_PRIVATE_ANSWER_ENABLED=True,
        )
        configured.enable()
        self.addCleanup(configured.disable)

    def release(self):
        current = cases.read_case(**self.staff())
        manifest = AnswerManifest.objects.get(answer_id=current["approved_answer_id"])
        return media.release_private(
            **self.staff(),
            expected_revision=current["revision"],
            expected_evidence_version=current["evidence_version"],
            manifest_sha256=manifest.sha256,
            confirmed=True,
        )

    def client_for(self, token=None):
        client = Client(enforce_csrf_checks=True, REMOTE_ADDR="127.0.0.1", HTTP_HOST="127.0.0.1")
        page = client.get("/casework/status/")
        response = post(
            client,
            "/casework/status/",
            {"action": "unlock", "token": token or self.a["token"]},
            page,
        )
        self.assertEqual(response.status_code, 303, response.content)
        return client
