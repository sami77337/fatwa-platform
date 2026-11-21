"""Finite current synthetic mandates; real SQL decisions and a separate file floor."""

import tempfile
import uuid
from datetime import timedelta

from django.test import override_settings
from django.utils import timezone

from apps.casework import services as cases
from apps.casework.models import Case
from apps.operational_workspace.authority import OperationalAuthority
from apps.operational_workspace.test_support import Directory
from config.settings import campaign_review
from tests.casework.test_http import WEB_SETTINGS

from . import catalog, services, store
from .authority import Grant, SuppressionAuthority
from .journal import LocalJournal

FEATURES = {
    **{key: value for key, value in WEB_SETTINGS.items() if not key.startswith("DATA_UPLOAD_")},
    "ROOT_URLCONF": "config.campaign_urls",
    "FATWA_OPERATIONAL_WORKSPACE_ENABLED": True,
    "FATWA_REQUESTER_PORTAL_ENABLED": True,
    "FATWA_STAFF_SESSIONS_ENABLED": False,
    "FATWA_DATA_PRIVACY_ENABLED": False,
    "FATWA_RECORD_SUPPRESSION_ENABLED": False,
    "MIDDLEWARE": list(campaign_review.MIDDLEWARE),
}


class OperationalReadAuthority(OperationalAuthority):
    def __init__(self, directory, receipt):
        self.directory, self.receipt = directory, receipt
        self.until = timezone.now() + timedelta(minutes=20)

    def projection_epoch(self):
        return repr((self.directory.provider_id, self.receipt["case_id"], self.until.isoformat()))

    def permits(self, **values):
        actor = self.directory.resolve(values["subject_id"])
        section = {"READ_QUEUE": "queue", "READ_CASE": "case", "READ_METADATA": "metadata"}.get(
            values["action"]
        )
        return bool(
            actor
            and section
            and values["role"] == actor.role
            and values["auth_epoch"] == actor.auth_epoch
            and values["provider_id"] == self.directory.provider_id
            and values["case_ref"] == self.receipt["public_ref"]
            and values["resource"]
            == {
                "kind": "CASE_OPERATIONAL_SECTION",
                "case_id": self.receipt["case_id"],
                "section": section,
            }
        )

    def grant_deadline(self, **values):
        return self.until if self.permits(**values) else None


class Authority(SuppressionAuthority):
    def __init__(self, directory, resources, subjects=("admin", "mufti")):
        self.directory = directory
        self.choices = tuple(resources)
        self.until = timezone.now() + timedelta(minutes=20)
        self.hook = None
        self.grants = {(subject, "ENTER", "", "", "") for subject in subjects}
        for subject in subjects:
            for kind, identifier in resources:
                target = catalog.target(kind, identifier)
                for action in ("READ_AUDIT", "SOFT_DELETE", "RESTORE", "RECONCILE"):
                    self.grants.add((subject, action, kind, identifier, target.source_digest))

    def projection_epoch(self):
        return catalog.canonical([sorted(self.grants), self.choices, self.until.isoformat()])

    def resources(self, **kwargs):
        return self.choices

    def authorize(self, **values):
        resource = values["resource"]
        key = (
            values["subject_id"],
            values["action"],
            resource["kind"] if resource else "",
            resource["id"] if resource else "",
            resource["source_digest"] if resource else "",
        )
        actor = self.directory.resolve(values["subject_id"])
        allowed = (
            actor is not None
            and actor.role == values["role"]
            and actor.auth_epoch == values["auth_epoch"]
            and values["provider_id"] == self.directory.provider_id
            and key in self.grants
        )
        if self.hook:
            self.hook(values)
        return Grant(self.until) if allowed else None

    def revoke(self, action, *, subject="admin"):
        self.grants = {
            entry for entry in self.grants if not (entry[0] == subject and entry[1] == action)
        }


class SuppressionFixture:
    def enable_suppression(self, resources, *, subjects=("admin", "mufti")):
        if not callable(getattr(self.directory, "projection_epoch", None)):
            from apps.research_library.test_support import bind_identity_snapshot

            bind_identity_snapshot(self.directory)
        self.journal_root = tempfile.TemporaryDirectory(prefix="fatwa-suppression-")
        self.addCleanup(self.journal_root.cleanup)
        self.journal = LocalJournal(root=self.journal_root.name, ledger_id=str(uuid.uuid4()))
        self.journal.initialize()
        self.suppression_authority = Authority(self.directory, resources, subjects)
        configured = override_settings(
            FATWA_RECORD_SUPPRESSION_ENABLED=True,
            FATWA_RECORD_SUPPRESSION_AUTHORITY=self.suppression_authority,
            FATWA_RECORD_SUPPRESSION_JOURNAL=self.journal,
        )
        configured.enable()
        self.addCleanup(configured.disable)

    def suppression_common(self, subject="admin"):
        return dict(provider=self.directory, subject_id=subject, synthetic_fixtures_only=True)

    def proposal(self, action="SOFT_DELETE", *, kind="CASE", identifier=None, subject="admin"):
        if action == "RECONCILE":
            return dict(
                action=action,
                kind="",
                identifier="",
                source_digest="",
                head="",
                watermark=store.snapshot(allow_pending=True).watermark,
                reason="مصالحة قرارات لاحقة للنسخة المستعادة",
                request_key=str(uuid.uuid4()),
            )
        identifier = identifier or self.receipt["case_id"]
        with services.inspect(
            kind=kind, identifier=identifier, **self.suppression_common(subject)
        ) as item:
            return dict(
                action=action,
                kind=kind,
                identifier=identifier,
                source_digest=item["item"]["source_digest"],
                head=item["item"]["head"],
                watermark=item["watermark"],
                reason="قرار بشري محدد لا يتضمن متن المصدر",
                request_key=str(uuid.uuid4()),
            )

    def plan(self, action="SOFT_DELETE", *, subject="admin", **values):
        with services.preview(
            proposal=self.proposal(action, subject=subject, **values),
            **self.suppression_common(subject),
        ) as plan:
            return plan

    def change(self, action="SOFT_DELETE", *, subject="admin", **values):
        plan = self.plan(action, subject=subject, **values)
        with services.apply(
            plan=plan, confirmed=True, **self.suppression_common(subject)
        ) as result:
            return result


class Fixture(SuppressionFixture):
    def setUp(self):
        super().setUp()
        suffix = uuid.uuid4().hex
        self.intake = dict(
            original_question="أصل سؤال محفوظ لا يظهر في دفتر الحذف",
            source_event_id="suppression-source-" + suffix,
            requester_id="suppression-requester-" + suffix,
            idempotency_key="suppression-intake-" + suffix,
            synthetic_fixtures_only=True,
        )
        self.receipt = cases.intake_case(**self.intake)
        self.case = Case.objects.get(pk=self.receipt["case_id"])
        self.directory = Directory([self.case.public_ref])
        self.directory.provider_id = "synthetic-record-suppression-directory"
        self.operational_authority = OperationalReadAuthority(self.directory, self.receipt)
        self.identity_settings = override_settings(
            FATWA_CASEWORK_IDENTITY_PROVIDER=self.directory,
            FATWA_OPERATIONAL_WORKSPACE_AUTHORITY=self.operational_authority,
        )
        self.identity_settings.enable()
        self.addCleanup(self.identity_settings.disable)
        result = cases.save_answer(
            case_id=self.receipt["case_id"],
            provider=self.directory,
            subject_id="mufti",
            text="جواب محفوظ لا يتلفه القرار الإداري",
            expected_revision=self.case.revision,
            expected_evidence_version=self.case.evidence_version,
            synthetic_fixtures_only=True,
        )
        self.answer_id = result["answers"][-1]["id"]
        self.enable_suppression([("CASE", self.receipt["case_id"]), ("ANSWER", self.answer_id)])
        self.case.refresh_from_db()

    def read(self, **kwargs):
        return cases.read_case(
            case_id=self.receipt["case_id"], **self.suppression_common("mufti"), **kwargs
        )
