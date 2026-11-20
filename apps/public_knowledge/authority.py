"""No role implies curation, translation approval, or anonymous release."""

from abc import ABC, abstractmethod


class PublicKnowledgeAuthority(ABC):
    @abstractmethod
    def permits(self, *, provider_id, subject_id, auth_epoch, case_ref, action, kind, language):
        """Literal True for this current EDIT/READ/REVIEW/APPROVE/RELEASE/WITHDRAW grant."""
        raise NotImplementedError

    def projection_epoch(self):
        """Atomic side-effect-free revision of every grant input, including expiry."""
        from apps.casework.services import CaseConflict

        raise CaseConflict("public_knowledge_policy_snapshot_required")
