"""An explicit capability seam; neither lesson metadata nor a link grants access."""

from abc import ABC, abstractmethod


class ScholarlyAuthority(ABC):
    @abstractmethod
    def projection_epoch(self):
        """Atomic, side-effect-free revision of ALL current authorization inputs.

        Return a nonempty string, changed for every per-action, actor, endpoint
        or resource grant/revocation. A getter must never mutate policy, identity
        or application state. Callbacks that change authorization must advance
        this revision before returning.
        """
        raise NotImplementedError

    @abstractmethod
    def permits(
        self,
        *,
        provider_id,
        subject_id,
        auth_epoch,
        case_ref,
        target_case_ref,
        action,
        kind,
        resource_id,
        resource_sha256,
    ):
        """Literal True for this exact identity, endpoint pair and immutable resource.

        MANAGE_LESSONS, READ_LESSON, READ_MEDIA, READ_LINK, PROPOSE, APPROVE,
        REJECT and WITHDRAW are independent actions. Kinds are LESSON or one
        of RELATED, REFERRED_BY_SHEIKH, DUPLICATE_OF, SUPERSEDES.
        This policy never replaces current MUFTI scope on either endpoint.
        It provides no anonymous, publication, download or export permission.
        """
        raise NotImplementedError
