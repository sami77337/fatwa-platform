"""No role defaults, inherited publication rights, or production grant provider."""

from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True, slots=True)
class Grant:
    valid_until: datetime


@dataclass(frozen=True, slots=True)
class UnclassifiedWorkGrant:
    """A separate exact private-read grant; never a recorded classification."""

    valid_until: datetime
    binding_sha256: str


class PrivacyAuthority(ABC):
    def authorize_unclassified_work(self, **values):
        """Optionally authorize exact STAFF/READ work before human classification.

        The default denies. A provider opting in returns UnclassifiedWorkGrant
        bound to the canonical digest of all supplied identity/source/action
        values. Its projection_epoch must include this policy and its grants.
        It cannot grant PUBLIC, SEARCH, EXPORT, PUBLISH, AI or classification.
        """
        return None

    @abstractmethod
    def authorize(
        self,
        *,
        audience,
        provider_id,
        subject_id,
        auth_epoch,
        role,
        case_ref,
        target_kind,
        target_id,
        source_digest,
        classification,
        previous_level,
        action,
    ):
        """Return an exact explicit Grant, or None to deny this current operation.

        READ/SEARCH/EXPORT/PUBLISH/AI and VIEW_CLASSIFICATION/CLASSIFY are
        independent actions. PUBLIC is a label, never an implicit permission.
        CLASSIFY receives both the current and proposed levels so the configured
        policy must explicitly authorize the particular human transition.
        """
        raise NotImplementedError

    @abstractmethod
    def projection_epoch(self):
        """A pure revision of every permission/configuration value above."""
        raise NotImplementedError
