"""Explicit server policy and fresh-verification adapter; neither defaults to a grant."""

from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime

from apps.mufti_review.identity import MuftiIdentity


@dataclass(frozen=True, slots=True)
class ReauthenticationRule:
    required: bool
    max_age_seconds: int


@dataclass(frozen=True, slots=True)
class FreshResult:
    identity: MuftiIdentity | None
    challenge: str
    verified_at: datetime
    method_id: str


class FreshAuthentication(ABC):
    """A configured adapter must actively reverify this credential for the challenge.

    Resolving a directory identity, replaying cached login metadata or claiming MFA
    is insufficient. The adapter declares its actual method. No adapter is supplied
    for production; the test adapter explicitly uses a SYNTHETIC credential.
    """

    fresh_method_id: str

    @abstractmethod
    def authenticate_fresh(self, credential, *, challenge):
        raise NotImplementedError


class SessionAuthority(ABC):
    """Exact ISSUE/USE/LIST/READ/REVOKE/LOGOUT/AUDIT grants, never role inference.

    projection_epoch is pure, atomic and non-reused; it covers policy, revocations
    and deadlines. Reauthentication policy supplies freshness, not the browser.
    No ORGANIZER_ADMIN or MUFTI default administration permission exists.
    """

    @abstractmethod
    def permits(self, *, provider_id, subject_id, role, auth_epoch, action, resource):
        raise NotImplementedError

    @abstractmethod
    def reauthentication(self, *, provider_id, subject_id, role, auth_epoch, operation, resource):
        raise NotImplementedError

    @abstractmethod
    def projection_epoch(self):
        raise NotImplementedError
