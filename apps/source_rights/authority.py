"""Explicit server permission, separate from scholarly/publication approval."""

from abc import ABC, abstractmethod


class SourceRightsAuthority(ABC):
    @abstractmethod
    def permits(self, *, provider_id, subject_id, auth_epoch, case_ref, action, source_sha256):
        """Literal True for VIEW/REGISTER/PROPOSE/APPROVE/REJECT/REVOKE.

        Scoped MUFTI identity is required independently. Empty source_sha256 is used
        only for VIEW of the current case's rights workspace. No implicit U03 grants.
        """
        raise NotImplementedError
