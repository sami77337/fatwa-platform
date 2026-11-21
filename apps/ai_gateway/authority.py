from abc import ABC, abstractmethod


class GatewayAuthority(ABC):
    """Independent USE and PROCESS_CONTEXT grants; READ/CITE never imply either.

    PROCESS_CONTEXT must explicitly cover the selected draft-fragment digest
    and exact source version, destination provider/model, actor, case and task.
    projection_epoch is a pure, atomic, non-reused revision that includes current
    revocations and expirations. Implementations must not grant wildcards.
    """

    @abstractmethod
    def permits(
        self,
        *,
        provider_id,
        subject_id,
        auth_epoch,
        case_ref,
        action,
        task,
        destination_provider,
        model_id,
        model_version,
        resource_kind,
        resource_id,
        resource_digest,
    ):
        raise NotImplementedError

    def projection_epoch(self):
        raise NotImplementedError
