"""Explicit synthetic classification grants for consumer integration tests only."""

import uuid
from datetime import timedelta

from django.test import override_settings
from django.utils import timezone

from apps.data_privacy import services
from apps.data_privacy.authority import Grant
from apps.data_privacy.catalog import locate
from apps.data_privacy.test_support import Authority


class ClassifiedSources:
    def __init__(self, test, directory, subject_id):
        self.directory, self.subject_id = directory, subject_id
        self.authority = Authority()
        configured = override_settings(
            FATWA_DATA_PRIVACY_ENABLED=True,
            FATWA_DATA_PRIVACY_AUTHORITY=self.authority,
            FATWA_CASEWORK_IDENTITY_PROVIDER=directory,
        )
        configured.enable()
        test.addCleanup(configured.disable)

    def principal(self):
        return services.staff_principal(self.directory, self.directory.resolve(self.subject_id))

    def allow(self, kind, identifier, action, *, level="CONFIDENTIAL", previous_level=""):
        target = locate(kind, identifier)
        principal = self.principal()
        values = dict(
            audience=principal.audience,
            provider_id=principal.provider_id,
            subject_id=principal.subject_id,
            auth_epoch=principal.auth_epoch,
            role=principal.role,
            case_ref=target.case_ref,
            target_kind=kind,
            target_id=target.identifier,
            source_digest=target.source_digest,
            classification=level,
            previous_level=previous_level,
            action=action,
        )
        key = self.authority.key(values)
        self.authority.grants[key] = Grant(timezone.now() + timedelta(minutes=10))
        return key

    def classify(self, kind, identifier, *, level="CONFIDENTIAL", actions=()):
        target = locate(kind, identifier)
        rows = services.history(target)
        self.allow(
            kind,
            identifier,
            "CLASSIFY",
            level=level,
            previous_level=rows[-1].level if rows else "",
        )
        result = services.classify(
            kind=kind,
            identifier=target.identifier,
            level=level,
            note="تصنيف اصطناعي محدد لا يمنح النشر أو المعالجة تلقائيًا",
            expected_digest=rows[-1].digest if rows else services.ZERO,
            expected_source_digest=target.source_digest,
            request_key=uuid.uuid4(),
            provider=self.directory,
            subject_id=self.subject_id,
            synthetic_fixtures_only=True,
        )
        for action in actions:
            self.allow(kind, identifier, action, level=level)
        return result
