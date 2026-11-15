"""Explicit server identity boundary. No live provider or permissive default."""
from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime, timedelta
import re
from django.utils import timezone

REF = re.compile(r'[A-Za-z0-9][A-Za-z0-9._:-]{0,127}')


class IdentityUnavailable(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class MuftiIdentity:
    subject_id: str
    role: str
    active: bool
    case_keys: frozenset[str]
    auth_epoch: str
    valid_until: datetime


class MuftiIdentityProvider(ABC):
    """Configure on the server from a trusted directory; never browser JSON."""
    provider_id: str

    @abstractmethod
    def authenticate(self, credential: str) -> MuftiIdentity | None:
        raise NotImplementedError

    @abstractmethod
    def resolve(self, subject_id: str) -> MuftiIdentity | None:
        raise NotImplementedError


def _ref(value, maximum=128):
    return type(value) is str and len(value) <= maximum and REF.fullmatch(value) is not None


def require_provider(provider):
    if not isinstance(provider, MuftiIdentityProvider) or not _ref(getattr(provider, 'provider_id', None)):
        raise IdentityUnavailable('trusted_mufti_identity_provider_required')


def validate_identity(identity, *, subject_id=None, case_key=None):
    now = timezone.now()
    if (not isinstance(identity, MuftiIdentity) or not _ref(identity.subject_id)
        or identity.role != 'MUFTI' or identity.active is not True
        or not _ref(identity.auth_epoch, 64) or type(identity.case_keys) is not frozenset
        or not 1 <= len(identity.case_keys) <= 64 or any(not _ref(case) for case in identity.case_keys)
        or not isinstance(identity.valid_until, datetime) or not timezone.is_aware(identity.valid_until)
        or identity.valid_until.utcoffset() != timedelta(0)
        or not now < identity.valid_until <= now + timedelta(hours=1)
        or (subject_id is not None and identity.subject_id != subject_id)
        or (case_key is not None and case_key not in identity.case_keys)):
        raise IdentityUnavailable('active_scoped_mufti_identity_required')
    return identity


def resolve_identity(provider, subject_id, *, case_key=None):
    require_provider(provider)
    if not _ref(subject_id):
        raise IdentityUnavailable('invalid_identity_subject')
    try:
        identity = provider.resolve(subject_id)
    except Exception as exc:
        raise IdentityUnavailable('mufti_identity_directory_unavailable') from exc
    return validate_identity(identity, subject_id=subject_id, case_key=case_key)


def authenticate_identity(provider, credential):
    require_provider(provider)
    if (type(credential) is not str or not 32 <= len(credential) <= 1024
        or not credential.isascii() or any(c.isspace() or ord(c) < 33 for c in credential)):
        raise IdentityUnavailable('invalid_identity_credential')
    try:
        identity = provider.authenticate(credential)
    except Exception as exc:
        raise IdentityUnavailable('identity_authentication_denied') from exc
    return validate_identity(identity)
