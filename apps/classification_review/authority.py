"""Explicit development authority, never a U03 grant or browser-supplied identity."""

from abc import ABC, abstractmethod


class ClassificationAuthority(ABC):
    @abstractmethod
    def permits(self, *, provider_id, subject_id, auth_epoch, case_ref, action):
        """Literal True grants VIEW/PROPOSE/APPROVE/REJECT/WITHDRAW for this exact case."""
        raise NotImplementedError
