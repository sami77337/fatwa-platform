"""Finite synthetic grants and service-created cases for operational read evidence."""

import unittest
import uuid
from dataclasses import replace
from datetime import timedelta

from django.test import override_settings
from django.utils import timezone

from apps.answer_media import services as answer_media
from apps.answer_media.tests import audio_fixture
from apps.case_organization import services as organization
from apps.casework import services as cases
from apps.composite_delivery.services import SIMULATOR_PROVIDER, ChannelProfile
from apps.delivery_planner.planner import Capabilities
from apps.experimental_publication import services as publication
from apps.experimental_publication.tests import Authority as PublicationAuthority
from apps.experimental_publication.tests import Directory as ScholarlyDirectory
from apps.mufti_review.identity import MuftiIdentity, MuftiIdentityProvider
from tests.casework.test_http import WEB_SETTINGS

from .authority import OperationalAuthority
from .boundary import ACTIONS, digest, source_rows
from .identity import pin

FEATURES = {
    **{key: value for key, value in WEB_SETTINGS.items() if not key.startswith("DATA_UPLOAD_")},
    "ROOT_URLCONF": "config.campaign_urls",
    "FATWA_OPERATIONAL_WORKSPACE_ENABLED": True,
    "FATWA_CASE_ORGANIZATION_ENABLED": True,
    "FATWA_ANSWER_MEDIA_ENABLED": True,
    "FATWA_COMPOSITE_DELIVERY_ENABLED": True,
    "FATWA_EXPERIMENTAL_PUBLICATION_ENABLED": True,
}
CREDENTIALS = {
    "operator": "synthetic-operational-operator-credential-32-characters",
    "admin": "synthetic-operational-admin-credential-32-characters",
    "mufti": "synthetic-operational-mufti-credential-32-characters",
}


class Directory(MuftiIdentityProvider):
    provider_id = "synthetic-operational-directory"

    def __init__(self, refs):
        self.identities = {
            subject: MuftiIdentity(
                subject,
                role,
                True,
                frozenset(refs),
                "epoch-1",
                timezone.now() + timedelta(minutes=30),
            )
            for subject, role in (
                ("operator", "ORGANIZER"),
                ("admin", "ORGANIZER_ADMIN"),
                ("mufti", "MUFTI"),
            )
        }
        self.hook = None

    def projection_epoch(self):
        return repr(
            (
                self.provider_id,
                sorted(
                    (subject, pin(actor), actor.valid_until.isoformat())
                    for subject, actor in self.identities.items()
                ),
            )
        )

    def resolve(self, subject_id):
        if self.hook:
            self.hook(subject_id)
        return self.identities.get(subject_id)

    def authenticate(self, credential):
        return self.resolve(
            next((key for key, value in CREDENTIALS.items() if value == credential), "")
        )


class Authority(OperationalAuthority):
    def __init__(self, cases_by_kind):
        self.until = timezone.now() + timedelta(minutes=30)
        self.hook = None
        sections = {
            "READ_QUEUE": "queue",
            "READ_CASE": "case",
            "READ_METADATA": "metadata",
            "READ_DELIVERY": "delivery",
            "READ_PUBLICATION": "publication",
            "READ_TRANSCRIPT": "transcript",
            "READ_CAPABILITY": "capability",
        }
        self.grants = {
            (subject, role, row["public_ref"], action, sections[action], row["case_id"])
            for subject, role in (
                ("operator", "ORGANIZER"),
                ("admin", "ORGANIZER_ADMIN"),
                ("mufti", "MUFTI"),
            )
            for key, row in cases_by_kind.items()
            if key not in {"hidden", "unscoped"}
            for action in ACTIONS
        }

    def projection_epoch(self):
        return repr((sorted(self.grants), self.until.isoformat()))

    def _allows(self, values):
        resource = values["resource"]
        return (
            values["provider_id"] == Directory.provider_id
            and values["auth_epoch"] == "epoch-1"
            and resource["kind"] == "CASE_OPERATIONAL_SECTION"
            and (
                values["subject_id"],
                values["role"],
                values["case_ref"],
                values["action"],
                resource["section"],
                resource["case_id"],
            )
            in self.grants
            and timezone.now() < self.until
        )

    def permits(self, **values):
        if self.hook:
            self.hook(values)
        return self._allows(values)

    def grant_deadline(self, **values):
        return self.until if self._allows(values) else None

    def revoke(self, *, subject="operator", action=None, case_ref=None):
        self.grants = {
            row
            for row in self.grants
            if not (
                row[0] == subject
                and (action is None or row[3] == action)
                and (case_ref is None or row[2] == case_ref)
            )
        }


class Profiles:
    def __init__(self):
        self.value = ChannelProfile(
            Capabilities(
                SIMULATOR_PROVIDER, "operational-fixture-v1", frozenset({"text"}), 6000, True
            ),
            192000,
            frozenset({"text/plain", "audio/wav", "application/pdf", "image/png"}),
        )
        self.hook = None

    def projection_epoch(self):
        return repr(self.value)

    def __call__(self, channel):
        if self.hook:
            self.hook(channel)
        return self.value


def intake(kind):
    key = "operational-" + kind + "-" + uuid.uuid4().hex
    return cases.intake_case(
        original_question="أصل سؤال اصطناعي خاص لمساحة التشغيل: " + kind,
        source_event_id=key,
        requester_id=key,
        idempotency_key=key,
        synthetic_fixtures_only=True,
    )


def approved(kind, *, audio=False):
    receipt = intake(kind)
    directory = ScholarlyDirectory([receipt["public_ref"]])
    common = dict(
        case_id=receipt["case_id"],
        subject_id="editor",
        provider=directory,
        synthetic_fixtures_only=True,
    )
    with override_settings(FATWA_CASEWORK_IDENTITY_PROVIDER=directory):
        if audio:
            answer = answer_media.save_multipart_answer(
                **common,
                text="جواب اصطناعي من إنسان",
                files=[audio_fixture()],
                expected_revision=1,
                expected_evidence_version=1,
            )
        else:
            answer = cases.save_answer(
                **common,
                text="جواب اصطناعي من إنسان",
                expected_revision=1,
                expected_evidence_version=1,
            )
        cases.record_decision(
            **common,
            answer_id=answer["answers"][-1]["id"],
            action="APPROVE",
            expected_revision=2,
            expected_evidence_version=1,
        )
    return receipt, common


def seed():
    """All domain states use actual core/editorial/provider services, never INSERT fixtures."""
    from apps.composite_delivery.tests import CompositeTests
    from apps.public_answer_media.test_support import FEATURES as MEDIA_FEATURES
    from apps.public_answer_media.test_support import MediaFixture

    result = {key: intake(key) for key in ("metadata", "hidden", "unscoped")}
    result["capability"], _ = approved("capability", audio=True)
    result["publication"], common = approved("publication")
    with override_settings(
        FATWA_CASEWORK_IDENTITY_PROVIDER=common["provider"],
        FATWA_EXPERIMENTAL_PUBLICATION_AUTHORITY=PublicationAuthority(
            result["publication"]["public_ref"]
        ),
    ):
        publication.create_edition(
            **common,
            title="مسودة نشر اصطناعية",
            category="مراجعة",
            body="نسخة تحريرية تحتاج مراجعة بشرية",
            expected_revision=3,
            expected_evidence_version=1,
        )
        organization.save(
            **common,
            tags=["وسم تنظيمي محفوظ"],
            question_types=["EDUCATION"],
            note="ملاحظة داخلية لا تعرضها قائمة التشغيل",
            command_id=uuid.uuid4(),
            expected_metadata_version=0,
            expected_revision=3,
            expected_evidence_version=1,
        )

    class DeliverySeed(CompositeTests):
        def intake(self, suffix):
            return super().intake("operational-delivery-" + uuid.uuid4().hex + suffix)

    delivery = DeliverySeed()
    try:
        delivery.setUp()
        delivery.approve()
        delivery.stage()
        lease = delivery.reserve()
        delivery.outcome(lease, delivery.resolve(lease), "FAILED")
        result["delivery"] = delivery.a
    finally:
        delivery.doCleanups()

    class TranscriptSeed(MediaFixture, unittest.TestCase):
        pass

    recording = TranscriptSeed()
    with override_settings(**MEDIA_FEATURES):
        try:
            recording.setUp()
            recording.save(change_kind="MEANING_REVIEW", segments=[])
            result["transcript"] = recording.receipt
        finally:
            recording.doCleanups()
    return {
        key: {field: row[field] for field in ("case_id", "public_ref")}
        for key, row in result.items()
    }


class OperationalFixture:
    def setUp(self):
        super().setUp()
        self.receipts = seed()
        refs = [row["public_ref"] for key, row in self.receipts.items() if key != "unscoped"]
        self.directory, self.authority, self.profiles = (
            Directory(refs),
            Authority(self.receipts),
            Profiles(),
        )
        configured = override_settings(
            FATWA_CASEWORK_IDENTITY_PROVIDER=self.directory,
            FATWA_OPERATIONAL_WORKSPACE_AUTHORITY=self.authority,
            FATWA_COMPOSITE_DELIVERY_CAPABILITIES=self.profiles,
        )
        configured.enable()
        self.addCleanup(configured.disable)
        self.common = dict(
            subject_id="operator", provider=self.directory, synthetic_fixtures_only=True
        )
        self.originals = self.state()

    def state(self):
        return digest(source_rows([row["case_id"] for row in self.receipts.values()]))

    def revoke_identity(self, subject="operator"):
        self.directory.identities[subject] = replace(
            self.directory.identities[subject], active=False
        )
