"""Separate server-side, default-deny permission for relationship review/source access."""

from abc import ABC, abstractmethod


class KnowledgeAuthority(ABC):
    @abstractmethod
    def permits(self, *, provider_id, subject_id, auth_epoch, case_ref, action, kind):
        """Return literal True for this current synthetic identity and exact case.

        Actions: APPROVE, WITHDRAW, OPEN_TRANSCRIPT. Kinds: REFERENCE, TRANSCRIPT.
        Never derives a grant from submitted form fields or historical policy rows.
        """
        raise NotImplementedError
