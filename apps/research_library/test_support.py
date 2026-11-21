"""Fabricated source records and current scoped identities; no scholarly corpus."""

import base64
import uuid
from datetime import timedelta
from pathlib import Path

from django.test import override_settings
from django.utils import timezone

from apps.casework import services as cases
from apps.experimental_publication.tests import Directory
from apps.library_preview.policy import PreviewPolicy
from tests.casework.test_http import WEB_SETTINGS

from . import services
from .authority import LibraryAuthority

FEATURES = {
    **WEB_SETTINGS,
    "ROOT_URLCONF": "config.campaign_urls",
    "DATA_UPLOAD_MAX_NUMBER_FIELDS": 32,
    "FATWA_RESEARCH_LIBRARY_ENABLED": True,
    "FATWA_RESEARCH_LIBRARY_PUBLIC_ENABLED": True,
    "FATWA_LIBRARY_PREVIEW_ENABLED": True,
    "FATWA_EXPERIMENTAL_PUBLICATION_ENABLED": True,
    "FATWA_CASE_CITATIONS_ENABLED": True,
    "FATWA_KNOWLEDGE_LINKS_ENABLED": True,
    "MIDDLEWARE": [
        "apps.library_preview.guard.PreviewCompositionGuard",
        "django.middleware.csrf.CsrfViewMiddleware",
    ],
}


class FixtureAuthority(LibraryAuthority):
    def __init__(self, *refs):
        self.refs, self.denied, self.hook = set(refs), set(), None

    def projection_epoch(self):
        return repr((sorted(self.refs), sorted(self.denied, key=repr)))

    def permits(self, **values):
        if self.hook:
            self.hook(values)
        return (
            values["provider_id"] == "synthetic-publication-directory"
            and values["subject_id"] in {"editor", "other", "publisher"}
            and values["auth_epoch"] == "epoch-1"
            and values["case_ref"] in self.refs
            and values["action"]
            in {
                "VIEW",
                "EDIT",
                "REVIEW",
                "APPROVE",
                "RELEASE",
                "REVOKE",
                "WITHDRAW",
                "READ",
                "DOWNLOAD",
                "CITE",
                "EXPORT",
                "OFFLINE",
            }
            and values["action"] not in self.denied
            and (values["action"], values["version_digest"]) not in self.denied
        )


def payload(kind="BOOK", **changes):
    values = {
        "kind": kind,
        "title": "مادة اصطناعية للتطوير",
        "work_title": "مصدر اصطناعي مستقل",
        "edition_label": "نسخة تجريبية أولى",
        "creator": "اسم مؤلف اصطناعي",
        "description": "بيانات اختبار؛ ليست مادة علمية حقيقية",
        "source_locator": "موضع وصفي تجريبي",
        "provenance": "مولدة محليًا للاختبار؛ لم تنسخ من مصدر خارجي",
        "rights_basis": "محتوى اصطناعي أعده الاختبار، لا ترخيص لمادة خارجية",
        "source_version": "fixture-v1",
        "recorded_text": "",
        "language": "ar",
        "synthetic": True,
    }
    return {**values, **changes}


def video():
    return base64.b64decode(Path(__file__).with_name("synthetic_video.b64").read_text())


def bind_identity_snapshot(directory):
    """Explicit fixture capability; its pure digest includes every identity grant input."""
    directory.projection_epoch = lambda: repr(
        (
            directory.provider_id,
            [
                (
                    key,
                    value.subject_id,
                    value.role,
                    value.active,
                    sorted(value.case_keys),
                    value.auth_epoch,
                    value.valid_until.isoformat(),
                    value.valid_until > timezone.now(),
                )
                for key, value in sorted(directory.identities.items())
            ],
        )
    )
    return directory


class LibraryFixture:
    def setUp(self):
        super().setUp()
        key = uuid.uuid4().hex
        self.receipt = cases.intake_case(
            original_question="سؤال خاص اصطناعي لا يدخل المكتبة",
            source_event_id=key,
            requester_id="private-" + key,
            idempotency_key=key,
            synthetic_fixtures_only=True,
        )
        self.directory = bind_identity_snapshot(Directory([self.receipt["public_ref"]]))
        self.directory.authenticate = lambda credential: self.directory.resolve(
            {
                "synthetic-editor-credential-32-characters": "editor",
                "synthetic-reviewer-credential-32-characters": "other",
                "synthetic-publisher-credential-32-characters": "publisher",
            }.get(credential, "")
        )
        self.authority = FixtureAuthority(self.receipt["public_ref"])
        self.common = dict(
            case_id=self.receipt["case_id"],
            subject_id="editor",
            provider=self.directory,
            synthetic_fixtures_only=True,
        )
        configured = override_settings(
            FATWA_RESEARCH_LIBRARY_AUTHORITY=self.authority,
            FATWA_CASEWORK_IDENTITY_PROVIDER=self.directory,
            FATWA_LIBRARY_PREVIEW_POLICY=PreviewPolicy(
                (), (), timezone.now() + timedelta(minutes=30), True
            ),
        )
        configured.enable()
        self.addCleanup(configured.disable)

    def write(self, **changes):
        values = dict(
            self.common,
            namespace="synthetic-library",
            external_id=uuid.uuid4().hex,
            payload=payload(),
            expected_revision=1,
            expected_evidence_version=1,
            expected_version=0,
            request_key=uuid.uuid4(),
        )
        return services.write_material(**{**values, **changes})

    def decide(self, record, action, **changes):
        values = dict(
            self.common,
            subject_id="other" if action == "REVIEW" else "publisher",
            version_id=record["version_id"],
            action=action,
            note="قرار بشري مستقل لبيانات اختبار",
            expected_actions=record["action_count"],
            request_key=uuid.uuid4(),
            confirmed=True,
            expected_revision=1,
            expected_evidence_version=1,
            uses=sorted(services.USES) if action == "APPROVE" else [],
            minutes=30 if action == "APPROVE" else (15 if action == "RELEASE" else 0),
        )
        return services.decide(**{**values, **changes})

    def approve(self, record, uses=None):
        reviewed = self.decide(record, "REVIEW")
        return self.decide(reviewed, "APPROVE", **({"uses": uses} if uses is not None else {}))

    def release(self, record, uses=None):
        return self.decide(self.approve(record, uses), "RELEASE")
