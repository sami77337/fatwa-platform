"""Validate actual operational roles without changing the MUFTI-only core validator."""

from datetime import datetime, timedelta

from django.conf import settings
from django.utils import timezone

from apps.casework.services import CaseConflict
from apps.mufti_review.identity import MuftiIdentity, MuftiIdentityProvider, _ref

ROLES = frozenset({"MUFTI", "ORGANIZER_ADMIN", "ORGANIZER"})


def pin(actor):
    return actor.subject_id, actor.role, actor.active, actor.case_keys, actor.auth_epoch


def valid_deadline(value):
    return (
        isinstance(value, datetime)
        and timezone.is_aware(value)
        and value.utcoffset() == timedelta(0)
        and timezone.now() < value <= timezone.now() + timedelta(hours=1)
    )


def validate(actor, *, subject_id=None, case_ref=None):
    if (
        type(actor) is not MuftiIdentity
        or not _ref(actor.subject_id)
        or type(actor.role) is not str
        or actor.role not in ROLES
        or actor.active is not True
        or not _ref(actor.auth_epoch, 64)
        or type(actor.case_keys) is not frozenset
        or not 1 <= len(actor.case_keys) <= 64
        or any(not _ref(value) for value in actor.case_keys)
        or not valid_deadline(actor.valid_until)
        or (subject_id is not None and actor.subject_id != subject_id)
        or (case_ref is not None and case_ref not in actor.case_keys)
    ):
        raise CaseConflict("operational_identity_unavailable")
    return actor


def configured(provider):
    directory = getattr(settings, "FATWA_CASEWORK_IDENTITY_PROVIDER", None)
    if (
        not isinstance(directory, MuftiIdentityProvider)
        or not _ref(getattr(directory, "provider_id", None))
        or not (
            provider is directory
            or (type(provider) is RequestDirectory and provider.directory is directory)
        )
    ):
        raise CaseConflict("operational_configured_directory_required")
    return directory


def epoch(provider):
    try:
        value = provider.projection_epoch()
    except Exception as exc:
        raise CaseConflict("operational_directory_snapshot_required") from exc
    if type(value) is not str or not 1 <= len(value) <= 131072:
        raise CaseConflict("operational_directory_snapshot_required")
    return value


def resolve(provider, subject_id, *, case_ref=None):
    configured(provider)
    if not _ref(subject_id):
        raise CaseConflict("operational_identity_unavailable")
    try:
        actor = provider.resolve(subject_id)
    except Exception as exc:
        raise CaseConflict("operational_identity_unavailable") from exc
    return validate(actor, subject_id=subject_id, case_ref=case_ref)


def authenticate(provider, credential):
    if configured(provider) is not provider or (
        type(credential) is not str
        or not 32 <= len(credential) <= 1024
        or not credential.isascii()
        or any(char.isspace() or ord(char) < 33 for char in credential)
    ):
        raise CaseConflict("operational_login_denied")
    before = epoch(provider)
    try:
        actor = validate(provider.authenticate(credential))
        fresh = resolve(provider, actor.subject_id)
    except Exception as exc:
        raise CaseConflict("operational_login_denied") from exc
    if epoch(provider) != before or pin(actor) != pin(fresh):
        raise CaseConflict("operational_login_changed")
    return actor


class RequestDirectory(MuftiIdentityProvider):
    """An operational session remains bound to its real subject, role and epoch."""

    def __init__(self, directory, actor):
        if configured(directory) is not directory:
            raise CaseConflict("operational_configured_directory_required")
        self.directory = directory
        self.provider_id = directory.provider_id
        self.expected = pin(validate(actor))

    def authenticate(self, credential):
        raise CaseConflict("operational_request_cannot_authenticate")

    def resolve(self, subject_id):
        if subject_id != self.expected[0] or self.provider_id != self.directory.provider_id:
            raise CaseConflict("operational_request_identity_changed")
        actor = resolve(self.directory, subject_id)
        if pin(actor) != self.expected:
            raise CaseConflict("operational_request_identity_changed")
        return actor

    def projection_epoch(self):
        return repr((id(self.directory), self.provider_id, self.expected, epoch(self.directory)))
