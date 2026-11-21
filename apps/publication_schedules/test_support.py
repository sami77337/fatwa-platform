"""Generated synthetic editions; every scheduler and publisher grant is explicit."""

import uuid
from datetime import timedelta

from django.test import override_settings
from django.utils import timezone

from apps.casework import services as cases
from apps.casework.models import Case
from apps.experimental_publication import services as publication
from apps.experimental_publication.tests import Authority, Directory
from apps.research_library.test_support import bind_identity_snapshot
from tests.casework.test_http import WEB_SETTINGS

from . import services
from .authority import ScheduleAuthority

FEATURES = {
    **WEB_SETTINGS,
    "ROOT_URLCONF": "config.campaign_urls",
    "FATWA_PUBLICATION_SCHEDULES_ENABLED": True,
    "FATWA_EXPERIMENTAL_PUBLICATION_ENABLED": True,
    "FATWA_MUFTI_WORKSPACE_ENABLED": True,
    "DATA_UPLOAD_MAX_NUMBER_FIELDS": 32,
}
CREDENTIAL = "synthetic-scheduler-credential-32-characters"


class PublishingAuthority(Authority):
    def __init__(self, ref):
        super().__init__(ref)
        self.denied = False

    def permits(self, **values):
        return not self.denied and super().permits(**values)

    def projection_epoch(self):
        return repr((self.ref, self.subject, self.denied))


class FixtureAuthority(ScheduleAuthority):
    def __init__(self, ref):
        self.ref, self.denied, self.hook = ref, set(), None

    def projection_epoch(self):
        return repr((self.ref, sorted(self.denied)))

    def permits(self, **values):
        if self.hook:
            self.hook(values)
        return (
            values["provider_id"] == Directory.provider_id
            and values["subject_id"] == "publisher"
            and values["auth_epoch"] == "epoch-1"
            and values["case_ref"] == self.ref
            and values["target"] == services.TARGET
            and values["action"] in {"SCHEDULE", "CANCEL", "RUN", "VIEW", "EXECUTE"}
            and values["action"] not in self.denied
        )


class ScheduleFixture:
    def setUp(self):
        super().setUp()
        identifier = uuid.uuid4().hex
        self.receipt = cases.intake_case(
            original_question="PRIVATE synthetic scheduled case",
            source_event_id=identifier,
            requester_id=identifier,
            idempotency_key=identifier,
            synthetic_fixtures_only=True,
        )
        self.directory = bind_identity_snapshot(Directory([self.receipt["public_ref"]]))
        self.directory.authenticate = lambda credential: (
            self.directory.resolve("publisher") if credential == CREDENTIAL else None
        )
        self.authority = FixtureAuthority(self.receipt["public_ref"])
        self.publisher = PublishingAuthority(self.receipt["public_ref"])
        configured = override_settings(
            FATWA_CASEWORK_IDENTITY_PROVIDER=self.directory,
            FATWA_PUBLICATION_SCHEDULES_AUTHORITY=self.authority,
            FATWA_EXPERIMENTAL_PUBLICATION_AUTHORITY=self.publisher,
        )
        configured.enable()
        self.addCleanup(configured.disable)
        self.common = dict(
            case_id=self.receipt["case_id"],
            subject_id="publisher",
            provider=self.directory,
            synthetic_fixtures_only=True,
        )
        editor = {**self.common, "subject_id": "editor"}
        answer = cases.save_answer(
            **editor,
            text="Original synthetic approved answer",
            expected_revision=1,
            expected_evidence_version=1,
        )
        self.answer_id = answer["answers"][-1]["id"]
        cases.record_decision(
            **editor,
            answer_id=self.answer_id,
            action="APPROVE",
            expected_revision=2,
            expected_evidence_version=1,
        )
        self.edition = self.new_edition()

    def new_edition(self):
        case = Case.objects.get(pk=self.common["case_id"])
        edition = publication.create_edition(
            **{**self.common, "subject_id": "editor"},
            title="نسخة اصطناعية للنشر في موعد",
            category="موضوع اصطناعي",
            body="هذا نص محرر اصطناعي محدد للنشر بعد مراجعة الموعد.",
            expected_revision=case.revision,
            expected_evidence_version=case.evidence_version,
        )
        publication.act(
            **{**self.common, "subject_id": "other"},
            edition_id=edition["id"],
            action="REVIEW",
            reviewed=True,
        )
        return edition

    def schedule(self, **changes):
        case = Case.objects.get(pk=self.common["case_id"])
        values = dict(
            edition_id=self.edition["id"],
            scheduled_at=timezone.now() + timedelta(minutes=5),
            target=services.TARGET,
            expected_revision=case.revision,
            expected_evidence_version=case.evidence_version,
            request_key=uuid.uuid4(),
            reason="اختيار بشري للنسخة والموعد والوجهة",
            confirmed=True,
        )
        values.update(changes)
        return services.prepare(**self.common, **values)
