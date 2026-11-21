"""No role defaults, inherited publication rights, or production grant provider."""

from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True, slots=True)
class Grant:
    valid_until: datetime


class PrivacyAuthority(ABC):
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
