"""Explicit first-factor verification and finite second-factor policy contracts."""

from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime

from apps.mufti_review.identity import MuftiIdentity


@dataclass(frozen=True, slots=True)
class PrimaryResult:
    identity: MuftiIdentity | None
    challenge: str
    verified_at: datetime
    method_id: str
    factor_kind: str


class PrimaryAuthentication(ABC):
    """Actively verify a KNOWLEDGE factor for this fresh challenge.

    The configured actual identity directory must implement this contract. An
    existing cookie, bearer token, cached identity or method label is insufficient.
    The directory owns its credential verification and primary-attempt limits.
    This package supplies no production credentials or identity provider.
    """

    primary_method_id: str

    @abstractmethod
    def authenticate_primary(self, credential, *, challenge):
        raise NotImplementedError


@dataclass(frozen=True, slots=True)
class MfaRule:
    algorithm: str
    digits: int
    period: int
    window: int
    max_failures: int
    challenge_seconds: int
    session_seconds: int
    recovery_codes: int


class MfaAuthority(ABC):
    """No role or historical row supplies an ENROLL, VERIFY or RECOVER grant.

    An enabled composition always requires MFA for both actual MUFTI and
    ORGANIZER_ADMIN identities. ORGANIZER is supported by the same explicit
    policy and never gains an exemption by assuming a more privileged role.
    projection_epoch is pure, atomic, non-reused and covers every policy change.
    """

    @abstractmethod
    def permits(self, *, provider_id, subject_id, role, auth_epoch, action, resource):
        raise NotImplementedError

    @abstractmethod
    def grant_deadline(self, *, provider_id, subject_id, role, auth_epoch, action, resource):
        """Aware UTC expiry of this exact grant; no implicit indefinitely valid grant."""
        raise NotImplementedError

    @abstractmethod
    def parameters(self, *, provider_id, subject_id, role, auth_epoch):
        raise NotImplementedError

    @abstractmethod
    def projection_epoch(self):
        raise NotImplementedError
