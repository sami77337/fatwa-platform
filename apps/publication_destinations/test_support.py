"""Generated local sources, ephemeral signatures and explicit finite fixture grants."""

import base64
import uuid
from dataclasses import asdict, replace
from datetime import timedelta

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from django.test import Client, override_settings
from django.utils import timezone

from apps.case_citations import services as citations
from apps.case_citations.tests import source_fixture
from apps.casework import services as cases
from apps.casework.models import Case
from apps.experimental_publication import services as publication
from apps.experimental_publication.models import PublicationEdition
from apps.experimental_publication.tests import Authority as BasePublicationAuthority
from apps.experimental_publication.tests import Directory as BaseDirectory
from apps.reference.models import ReferenceHeading
from apps.source_rights import services as rights
from apps.source_rights.tests import Authority as RightsAuthority
from tests.casework.test_http import WEB_SETTINGS, post

from . import services
from .authority import DestinationAuthority
from .profiles import DestinationProfile
from .signatures import (
    AUDIENCE,
    PROVIDER,
    DestinationOutcomeVerifier,
    SignedDestinationOutcome,
    signing_payload,
)

FEATURES = {
    **WEB_SETTINGS,
    "ROOT_URLCONF": "apps.publication_destinations.urls",
    "DATA_UPLOAD_MAX_NUMBER_FIELDS": 32,
    "FATWA_PUBLICATION_DESTINATIONS_ENABLED": True,
    "FATWA_EXPERIMENTAL_PUBLICATION_ENABLED": True,
    "FATWA_CASE_CITATIONS_ENABLED": True,
    "FATWA_SOURCE_RIGHTS_ENABLED": True,
    "FATWA_SOURCE_RIGHTS_ENFORCED": True,
}
NATIVE_FEATURES = {
    **FEATURES,
    "ROOT_URLCONF": "config.campaign_urls",
    # The browser enters through this current-case navigation, not a crafted POST.
    "FATWA_MUFTI_WORKSPACE_ENABLED": True,
}
PROFILES = (
    DestinationProfile("WEBSITE", "site.v1", 24000),
    DestinationProfile("TELEGRAM_CHANNEL", "channel.v1", 6000),
)
CREDENTIALS = {
    "editor": "synthetic-destination-editor-credential-32-characters",
    "other": "synthetic-destination-reviewer-credential-32-characters",
    "publisher": "synthetic-destination-publisher-credential-32-characters",
}


class Directory(BaseDirectory):
    def projection_epoch(self):
        return repr((self.provider_id, sorted(self.identities.items())))

    def authenticate(self, credential):
        return next(
            (
                self.resolve(subject)
                for subject, expected in CREDENTIALS.items()
                if credential == expected
            ),
            None,
        )


class PublicationAuthority(BasePublicationAuthority):
    def projection_epoch(self):
        return repr((self.ref, self.subject))


class FixtureAuthority(DestinationAuthority):
    def __init__(self, ref):
        self.ref = ref
        self.denied = set()
        self.until = timezone.now() + timedelta(minutes=30)
        self.hook = None

    def projection_epoch(self):
        return repr((self.ref, sorted(self.denied, key=repr), self.until.isoformat()))

    def permits(self, **values):
        if self.hook:
            self.hook(values)
        return (
            values["provider_id"] == Directory.provider_id
            and values["subject_id"] in CREDENTIALS
            and values["auth_epoch"] == "epoch-1"
            and values["case_ref"] == self.ref
            and values["destination"] in ("", "WEBSITE", "TELEGRAM_CHANNEL")
            and values["action"]
            in {"READ", "SELECT", "REVIEW", "APPROVE", "PREPARE", "OBSERVE", "WITHDRAW"}
            and (values["destination"] != "" or values["action"] == "READ")
            and values["action"] not in self.denied
            and (values["destination"], values["action"]) not in self.denied
            and (values["subject_id"], values["action"]) not in self.denied
            and (values["action"], values["resource_id"]) not in self.denied
            and timezone.now() < self.until
        )

    def grant_deadline(self, **values):
        return self.until if self.permits(**values) else None


class Fixture:
    def setUp(self):
        super().setUp()
        self.catalog_id = source_fixture()
        self.heading = ReferenceHeading.objects.get(edition_id=self.catalog_id, source_row_id=2)
        token = uuid.uuid4().hex
        self.receipt = cases.intake_case(
            original_question="PRIVATE SYNTHETIC QUESTION requester@example.test",
            source_event_id="destination-event-" + token,
            requester_id="destination-requester-" + token,
            idempotency_key="destination-intake-" + token,
            synthetic_fixtures_only=True,
        )
        self.directory = Directory([self.receipt["public_ref"]])
        self.common = dict(
            case_id=self.receipt["case_id"],
            subject_id="editor",
            provider=self.directory,
            synthetic_fixtures_only=True,
        )
        self.authority = FixtureAuthority(self.receipt["public_ref"])
        self.publication_authority = PublicationAuthority(self.receipt["public_ref"])
        self.rights_authority = RightsAuthority(self.receipt["public_ref"])
        self.signer = Ed25519PrivateKey.generate()
        self.verifier = DestinationOutcomeVerifier(
            issuer="synthetic-publication-fixture",
            trusted_public_keys={"ephemeral-fixture": self.signer.public_key().public_bytes_raw()},
        )
        overlay = override_settings(
            FATWA_CASEWORK_IDENTITY_PROVIDER=self.directory,
            FATWA_EXPERIMENTAL_PUBLICATION_AUTHORITY=self.publication_authority,
            FATWA_SOURCE_RIGHTS_AUTHORITY=self.rights_authority,
            FATWA_PUBLICATION_DESTINATIONS_AUTHORITY=self.authority,
            FATWA_PUBLICATION_DESTINATION_PROFILES=PROFILES,
            FATWA_PUBLICATION_DESTINATIONS_PROVIDER_VERIFIER=self.verifier,
        )
        overlay.enable()
        self.addCleanup(overlay.disable)
        source = rights.register(**self.common, kind="TOC_METADATA", target_id=self.heading.pk)
        self.rights_revision = rights.propose(
            **self.common,
            source_id=source["id"],
            expected_number=0,
            uses=["READ", "CITE", "PREVIEW_METADATA"],
            basis="Explicit synthetic grant",
            note="Reviewed source and finite scope",
            ttl_minutes=60,
        )
        rights.review(
            **{**self.common, "subject_id": "publisher"},
            revision_id=self.rights_revision["id"],
            action="APPROVE",
            confirmed=True,
            note="Independent explicit source rights",
        )
        selected = citations.read_source(**self.common, edition_id=self.catalog_id, source_row_id=2)
        draft = citations.save_cited_answer(
            **self.common,
            expected_revision=1,
            expected_evidence_version=1,
            text="PRIVATE SYNTHETIC APPROVED ANSWER",
            selections=[
                dict(
                    edition_id=self.catalog_id,
                    source_row_id=2,
                    source_sha256=selected["source_sha256"],
                    editorial_note="Reviewed synthetic exact source",
                )
            ],
        )
        cases.record_decision(
            **self.common,
            answer_id=draft["answers"][-1]["id"],
            expected_revision=2,
            expected_evidence_version=1,
            action="APPROVE",
            note="Synthetic approval",
        )
        self.first = self.edition("نص الموقع الاصطناعي الأول محفوظ كما اعتمد.")
        self.second = self.edition("نص القناة الاصطناعي الثاني مستقل ومختلف.")

    def pins(self):
        case = Case.objects.get(pk=self.common["case_id"])
        return dict(
            expected_revision=case.revision, expected_evidence_version=case.evidence_version
        )

    def edition(self, body):
        result = publication.create_edition(
            **self.common,
            **self.pins(),
            title="نسخة عامة اصطناعية",
            category="تصنيف اصطناعي",
            body=body,
        )
        publication.act(
            **{**self.common, "subject_id": "other"},
            edition_id=result["id"],
            action="REVIEW",
            reviewed=True,
        )
        publication.act(
            **{**self.common, "subject_id": "publisher"}, edition_id=result["id"], action="APPROVE"
        )
        return PublicationEdition.objects.get(pk=result["id"])

    def select(self, destination="WEBSITE", source=None, **changes):
        values = dict(
            **self.common,
            **self.pins(),
            destination=destination,
            source_selection=services.selection(source or self.first),
            expected_version=0,
            request_key=uuid.uuid4(),
            confirmed=True,
            note="اختيار بشري للنسخة المحددة",
        )
        return services.select(**{**values, **changes})

    def decide(self, row, command, subject=None, **changes):
        subject = subject or ("other" if command == "REVIEW" else "publisher")
        values = dict(
            **{**self.common, "subject_id": subject},
            **self.pins(),
            version_id=str(row.pk),
            command=command,
            expected_events=row.events.count(),
            request_key=uuid.uuid4(),
            confirmed=True,
            note="قرار مستقل محدد للنسخة والوجهة",
        )
        return services.decide(**{**values, **changes})

    def prepare(self, row):
        for command in ("REVIEW", "APPROVE", "PREPARE"):
            row = self.decide(row, command)
        return row

    def signed(self, row, reported="PUBLISHED", **changes):
        preparation = row.events.get(action="PREPARE")
        now = timezone.now()
        unsigned = SignedDestinationOutcome(
            **{
                "issuer": "synthetic-publication-fixture",
                "audience": AUDIENCE,
                "key_id": "ephemeral-fixture",
                "provider": PROVIDER,
                "event_id": str(uuid.uuid4()),
                "record_id": str(row.record_id),
                "version_id": str(row.pk),
                "version_sha256": row.digest,
                "preparation_id": str(preparation.pk),
                "preparation_sha256": preparation.digest,
                "destination": row.record.destination,
                "profile_sha256": row.profile_sha256,
                "plan_sha256": row.plan_sha256,
                "source_id": str(row.source_id),
                "source_sha256": row.source.content_sha256,
                "reported": reported,
                "issued_at": now.isoformat(),
                "expires_at": (now + timedelta(minutes=10)).isoformat(),
                "signature_b64url": "",
                **changes,
            }
        )
        return asdict(
            replace(
                unsigned,
                signature_b64url=base64.urlsafe_b64encode(
                    self.signer.sign(signing_payload(unsigned))
                )
                .decode()
                .rstrip("="),
            )
        )

    def observe(self, row, reported="PUBLISHED", **changes):
        values = dict(
            **{**self.common, "subject_id": "publisher"},
            **self.pins(),
            version_id=str(row.pk),
            envelope=self.signed(row, reported),
            expected_events=row.events.count(),
            request_key=uuid.uuid4(),
            confirmed=True,
            note="تحقق بشري من نتيجة محاكاة موقعة",
        )
        return services.observe(**{**values, **changes})

    def read(self):
        with services.desk_projection(**self.common) as result:
            return result

    def login(self, subject="editor"):
        client = Client(enforce_csrf_checks=True, REMOTE_ADDR="127.0.0.1", HTTP_HOST="127.0.0.1")
        page = client.get("/casework/staff/login/")
        result = post(client, "/casework/staff/login/", {"credential": CREDENTIALS[subject]}, page)
        self.assertEqual(result.status_code, 303, result.content)
        return client, client.get("/casework/staff/")

    def open(self, client, page):
        return post(
            client,
            "/casework/staff/",
            dict(action="pd_open", case_ref=self.receipt["public_ref"]),
            page,
        )

    def seed_delivery(self):
        """Retain a nonempty real queue/audit history for this same synthetic case."""
        from apps.delivery_planner.trusted_identity import Ed25519ApprovalVerifier, IdentityStatus
        from tests.casework.delivery_fixtures import CaseDeliveryFixture

        seed = CaseDeliveryFixture()
        seed.now = timezone.now()
        seed.approval_key = Ed25519PrivateKey.generate()
        seed.channel_key = Ed25519PrivateKey.generate()
        seed.directory, seed.a = self.directory, self.receipt
        seed.staff = lambda case=None, **unused: self.common
        seed.approval_verifier = Ed25519ApprovalVerifier(
            issuer="synthetic-mufti",
            audience="synthetic-case-return",
            trusted_public_keys={"mufti-key": seed.approval_key.public_key().public_bytes_raw()},
            identity_lookup=lambda subject: IdentityStatus(subject, "MUFTI", subject == "editor"),
            is_revoked_or_consumed=lambda *_: False,
            clock=lambda: seed.now,
        )
        seed.channel_verifier = seed.verifier()
        seed.receipt = lambda request, **changes: CaseDeliveryFixture.receipt(
            seed, request, approver_id="editor", **changes
        )
        seed.stage()
        seed.deliver()
        self.assertTrue(seed.status()["delivery_verified"])
        return seed
