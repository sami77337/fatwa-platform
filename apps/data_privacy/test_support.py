"""Explicit synthetic grants only. Never installed or selected by default."""

import uuid
from datetime import timedelta

from django.test import override_settings
from django.utils import timezone

from apps.case_attachments.tests import new_case
from tests.casework.test_http import Directory

from . import services
from .authority import Grant, PrivacyAuthority
from .catalog import digest, locate


class Authority(PrivacyAuthority):
    def __init__(self):
        self.grants = {}
        self.calls = []

    @staticmethod
    def key(values):
        return tuple(sorted(values.items()))

    def authorize(self, **values):
        self.calls.append(values)
        return self.grants.get(self.key(values))

    def projection_epoch(self):
        return digest(
            [
                [list(key), grant.valid_until.isoformat()]
                for key, grant in sorted(self.grants.items())
            ]
        )


class PrivacyFixture:
    def setUp(self):
        super().setUp()
        with override_settings(FATWA_DATA_PRIVACY_ENABLED=False):
            self.receipt = new_case()
        self.directory = Directory()
        self.directory.projection_epoch = lambda: repr(self.directory.current)
        self.directory.grant(self.receipt["public_ref"])
        self.authority = Authority()
        configured = override_settings(
            FATWA_DATA_PRIVACY_ENABLED=True,
            FATWA_DATA_PRIVACY_AUTHORITY=self.authority,
            FATWA_CASEWORK_IDENTITY_PROVIDER=self.directory,
        )
        configured.enable()
        self.addCleanup(configured.disable)
        self.target = locate("CASE", self.receipt["case_id"])

    def principal(self):
        return services.staff_principal(self.directory, self.directory.current)

    def allow(self, target, level, action, *, previous_level="", principal=None):
        principal = principal or self.principal()
        values = dict(
            audience=principal.audience,
            provider_id=principal.provider_id,
            subject_id=principal.subject_id,
            auth_epoch=principal.auth_epoch,
            role=principal.role,
            case_ref=target.case_ref,
            target_kind=target.kind,
            target_id=target.identifier,
            source_digest=target.source_digest,
            classification=level,
            previous_level=previous_level,
            action=action,
        )
        key = self.authority.key(values)
        self.authority.grants[key] = Grant(timezone.now() + timedelta(minutes=10))
        return key

    def classify(self, target=None, level="CONFIDENTIAL", **changes):
        target = target or self.target
        rows = services.history(target)
        previous = rows[-1].level if rows else ""
        self.allow(target, level, "CLASSIFY", previous_level=previous)
        fields = dict(
            kind=target.kind,
            identifier=target.identifier,
            level=level,
            note="تصنيف بشري اصطناعي مستقل؛ لا إذن نشر أو تصدير",
            expected_digest=rows[-1].digest if rows else services.ZERO,
            expected_source_digest=target.source_digest,
            request_key=uuid.uuid4(),
            provider=self.directory,
            subject_id=self.directory.current.subject_id,
            synthetic_fixtures_only=True,
        )
        return services.classify(**{**fields, **changes})
