"""Default-deny integration seam for source_rights; never grants a case role."""

from abc import ABC, abstractmethod
from dataclasses import dataclass

from django.conf import settings

from apps.casework.services import CaseConflict


@dataclass(frozen=True, slots=True)
class Resource:
    kind: str
    identifier: str
    sha256: str
    edition_id: int | None = None
    source_namespace: str = ""
    source_book_id: str = ""
    edition_key: str = ""
    source_archive_sha256: str = ""
    source_input_sha256: str = ""


class ResearchRights(ABC):
    @abstractmethod
    def permits(self, *, provider_id, subject_id, auth_epoch, case_ref, action, resource):
        """Literal True only for the current identity, exact resource and action.

        DISCOVER: metadata listing; READ_METADATA: full catalog/link metadata;
        SEARCH_TEXT / READ_TEXT: actual authorized transcript text;
        CITE: exact reference into a new canonical answer revision;
        READ_MEDIA: exact bytes through the existing private storage reader.
        A grant here never replaces case scope or KnowledgeAuthority.
        """
        raise NotImplementedError


def allowed(actor, provider, case, action, resource):
    policy = getattr(settings, "FATWA_RESEARCH_WORKSPACE_RIGHTS", None)
    if not isinstance(policy, ResearchRights):
        return False
    try:
        return (
            policy.permits(
                provider_id=provider.provider_id,
                subject_id=actor.subject_id,
                auth_epoch=actor.auth_epoch,
                case_ref=case.public_ref,
                action=action,
                resource=resource,
            )
            is True
        )
    except Exception as exc:
        raise CaseConflict("research_rights_unavailable") from exc


def require(actor, provider, case, action, resource):
    if not allowed(actor, provider, case, action, resource):
        raise CaseConflict("research_resource_not_authorized")
