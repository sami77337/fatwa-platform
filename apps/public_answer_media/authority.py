"""No role, source read, transcript review or anonymous release is implied."""

from abc import ABC, abstractmethod


class AnswerMediaAuthority(ABC):
    @abstractmethod
    def projection_epoch(self):
        """Atomic, side-effect-free revision of every permission/expiry input."""
        raise NotImplementedError

    @abstractmethod
    def permits(self, *, provider_id, subject_id, auth_epoch, case_ref, action, resource):
        """Literal True for this exact current actor, source and operation only.

        READ_TRANSCRIPT, EDIT_TRANSCRIPT, REVIEW_TRANSCRIPT, REVIEW_MEANING,
        WITHDRAW_TRANSCRIPT, PREPARE_MEDIA, REVIEW_MEDIA, RELEASE_MEDIA,
        WITHDRAW_MEDIA, PUBLIC_AUDIO and PUBLIC_TRANSCRIPT are separate grants. The existing
        TimedMediaRights READ_MEDIA grant is additionally required for bytes.
        This seam never supplies a MUFTI identity or grants a canonical case.
        """
        raise NotImplementedError
