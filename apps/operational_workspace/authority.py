"""Current operational grants do not grant scholarly approval or account administration."""

from abc import ABC, abstractmethod


class OperationalAuthority(ABC):
    @abstractmethod
    def projection_epoch(self):
        """Atomic pure revision of all grants, overrides, revocations and expiry inputs."""
        raise NotImplementedError

    @abstractmethod
    def permits(self, *, provider_id, subject_id, role, auth_epoch, case_ref, action, resource):
        """Literal True for this actual actor and exact action/case/resource only.

        READ_QUEUE, READ_CASE, READ_METADATA, READ_DELIVERY, READ_PUBLICATION,
        READ_TRANSCRIPT and READ_CAPABILITY are independent read grants. No grant
        here may create/approve a scholarly answer, edit its original, publish,
        send, assign a staff role or administer any policy.

        The separately default-off internal-notes feature accepts independent
        READ_INTERNAL_NOTES and ADD_INTERNAL_NOTE grants. ADD permits only an
        append-only internal note with unchanged server-copied tags and types;
        it does not confer read access or any scholarly or metadata edit right.

        The separately default-off metadata feature accepts EDIT_TAGS and
        EDIT_QUESTION_TYPES on the metadata section, plus READ_CLASSIFICATION
        and BIND_CLASSIFICATION on an exact CASE_CLASSIFICATION_VERSION resource.
        Taxonomy policy and current scope on both cases remain independently
        necessary. These grants do not create/review trees or scholarly answers.

        The separately default-off coordination feature accepts READ_COORDINATION,
        SET_PRIMARY, CLEAR_PRIMARY and SET_PRIORITY on CASE_COORDINATION resources.
        Each write retains the real role, reason and canonical source versions.
        Target Mufti scope is independently resolved; assignment grants never
        create account roles or case permissions. Priority values come only from
        a separately configured, versioned finite human policy.
        The independently default-off lesson-link feature uses READ_LESSON_LINKS
        on its section and READ_OPERATIONAL_LESSON, READ_LESSON_LINK,
        PROPOSE_LESSON_LINK, APPROVE_LESSON_LINK, REJECT_LESSON_LINK and
        WITHDRAW_LESSON_LINK on exact CASE_LESSON_VERSION / CASE_LESSON_LINK
        resources. ScholarlyAuthority independently checks the same endpoints
        and immutable resource. Link approval is no scholarly answer approval,
        and these actions grant no media bytes or other relation kinds.

        The independently default-off transcript editor uses READ_TRANSCRIPT_EDITOR
        on its section and READ_RECORDING_TRANSCRIPT, EDIT_RECORDING_TRANSCRIPT,
        REVIEW_RECORDING_TRANSCRIPT, WITHDRAW_RECORDING_TRANSCRIPT and
        READ_RECORDING_AUDIO on exact CASE_RECORDING_SOURCE / CASE_RECORDING_TRANSCRIPT
        resources. APPROVE_TRANSCRIPT_MEANING additionally requires actual MUFTI,
        regardless of a true policy result. AnswerMediaAuthority and TimedMediaRights
        remain independent. Derivative editing never changes the original answer.

        The independently default-off publication manager uses READ_PUBLICATION_MANAGER
        on its section and READ_PUBLICATION_EDITION, REVIEW_PUBLICATION_EDITION,
        APPROVE_PUBLICATION_EDITION, WITHDRAW_PUBLICATION_EDITION on an exact
        CASE_PUBLICATION_EDITION. Versioned PublicationAuthority must independently
        permit READ / REVIEW / APPROVE / WITHDRAW. It manages existing editions
        prepared through the MUFTI workflow; it grants no free body editing,
        scientific approval, delivery or anonymous publication availability.
        """
        raise NotImplementedError

    @abstractmethod
    def grant_deadline(self, **values):
        """Aware UTC deadline of that exact current grant; never an implied grant."""
        raise NotImplementedError
