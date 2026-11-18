"""Explicit development authority, never a U03 grant or browser-supplied identity."""

from abc import ABC, abstractmethod


class ClassificationAuthority(ABC):
    @abstractmethod
    def permits(self, *, provider_id, subject_id, auth_epoch, case_ref, action):
        """Literal True grants VIEW/PROPOSE/APPROVE/REJECT/WITHDRAW for this exact case."""
        raise NotImplementedError


class EditorialSimulationPolicy(ABC):
    """Closed V14 drill contract; not an approved product/U03 publication policy."""

    policy_id = ""

    @abstractmethod
    def permits(self, *, provider_id, subject_id, auth_epoch, case_ref, revision_id, action):
        """Literal True for exact revision and INSPECT/PREPARE/REVIEW/APPROVE."""
        raise NotImplementedError
