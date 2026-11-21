"""Whole-batch authorization, including the last callback and final HTTP render."""

import os
from contextlib import contextmanager

from django.apps import apps
from django.conf import settings

from apps.case_citations.services import _projection_expiry_guard
from apps.casework import services as cases
from apps.delivery_queue.services import synthetic_queue_atomic
from apps.platform_recovery.integration import mutation_context
from apps.research_workspace.reference_batch import _epoch
from apps.research_workspace.rights import ResearchRights
from apps.research_workspace.source_rights_adapter import SourceRightsAdapter

from .authority import ExportAuthority


def enabled():
    if (
        os.environ.get("FATWA_PRODUCTION") != "0"
        or getattr(settings, "FATWA_SELECTED_EXPORTS_ENABLED", False) is not True
    ):
        raise cases.CaseConflict("selected_exports_disabled")


def epoch(policy):
    try:
        value = policy.projection_epoch()
    except Exception as exc:
        raise cases.CaseConflict("export_policy_snapshot_required") from exc
    if type(value) is not str or not value or len(value) > 1000:
        raise cases.CaseConflict("export_policy_snapshot_required")
    return value


def authority():
    value = getattr(settings, "FATWA_SELECTED_EXPORTS_AUTHORITY", None)
    if not isinstance(value, ExportAuthority):
        raise cases.CaseConflict("export_authority_required")
    return value


def permit(case, actor, provider, action, resource=None):
    try:
        allowed = authority().permits(
            provider_id=provider.provider_id,
            subject_id=actor.subject_id,
            auth_epoch=actor.auth_epoch,
            case_ref=case.public_ref,
            action=action,
            resource=resource,
        )
    except cases.CaseConflict:
        raise
    except Exception as exc:
        raise cases.CaseConflict("export_authority_unavailable") from exc
    if allowed is not True:
        raise cases.CaseConflict("export_not_authorized")


def _snapshot(case, kinds):
    export = authority()
    policies = [(id(export), epoch(export), export)]
    if kinds:
        research = getattr(settings, "FATWA_RESEARCH_WORKSPACE_RIGHTS", None)
        if not isinstance(research, ResearchRights):
            raise cases.CaseConflict("export_source_policy_required")
        policies.append((id(research), _epoch(research), research))
        if isinstance(research, SourceRightsAdapter) and kinds & {"ATTACHMENT", "ANSWER_MEDIA"}:
            media = research.media_rights
            policies.append((id(media), epoch(media), media))
        if kinds & {"TRANSCRIPT", "KNOWLEDGE"}:
            knowledge = getattr(settings, "FATWA_KNOWLEDGE_LINKS_AUTHORITY", None)
            policies.append((id(knowledge), epoch(knowledge), knowledge))
    configuration = tuple(
        (name, getattr(settings, name, None))
        for name in (
            "FATWA_RESEARCH_WORKSPACE_ENABLED",
            "FATWA_KNOWLEDGE_LINKS_ENABLED",
            "FATWA_EXPERIMENTAL_PUBLICATION_ENABLED",
            "FATWA_SOURCE_RIGHTS_ENFORCED",
            "FATWA_SOURCE_RIGHTS_ENABLED",
            "FATWA_ANSWER_MEDIA_ENABLED",
            "FATWA_CASE_ATTACHMENTS_ENABLED",
            "FATWA_PRIVATE_MEDIA_STORAGE",
        )
    )
    ledger = []
    if kinds and apps.is_installed("apps.source_rights"):
        from apps.source_rights.models import (
            RightsAction,
            RightsRevision,
            SourceRegistration,
            SourceVersion,
        )

        registrations = list(SourceRegistration.objects.filter(case=case).order_by("pk").values())
        ledger = [
            registrations,
            list(RightsRevision.objects.filter(case=case).order_by("pk").values()),
            list(RightsAction.objects.filter(revision__case=case).order_by("pk").values()),
            list(
                SourceVersion.objects.filter(pk__in=[r["source_id"] for r in registrations])
                .order_by("pk")
                .values()
            ),
        ]
    knowledge_state = []
    if "KNOWLEDGE" in kinds:
        from apps.experimental_publication.models import PublicationAction, PublicationEdition
        from apps.knowledge_links.models import KnowledgeAction, KnowledgeRevision

        knowledge_state = [
            list(
                PublicationEdition.objects.filter(case=case)
                .order_by("pk")
                .values("id", "number", "content_sha256")
            ),
            list(PublicationAction.objects.filter(edition__case=case).order_by("pk").values()),
            list(
                KnowledgeRevision.objects.filter(publication__case=case)
                .order_by("pk")
                .values("id", "number", "snapshot_sha256")
            ),
            list(
                KnowledgeAction.objects.filter(revision__publication__case=case)
                .order_by("pk")
                .values()
            ),
        ]
    canonical = (
        type(case)
        .objects.filter(pk=case.pk)
        .values_list("revision", "evidence_version", "answer_revision", "approved_answer_id")
        .get()
    )
    return policies, configuration, ledger, knowledge_state, canonical


def _identity(actor):
    return actor.subject_id, actor.role, actor.active, actor.case_keys, actor.auth_epoch


@mutation_context
@contextmanager
def boundary(
    *, case_id, subject_id, provider, kinds=(), action="VIEW", synthetic_fixtures_only=False
):
    enabled()
    kinds = frozenset(kinds)
    provider_id = getattr(provider, "provider_id", None)
    with (
        synthetic_queue_atomic(),
        cases._staff_case(case_id, subject_id, provider, synthetic_fixtures_only) as (case, actor),
        _projection_expiry_guard(),
    ):
        initial = _snapshot(case, kinds)
        permit(case, actor, provider, action)
        from apps.data_privacy.integration import staff as privacy

        privacy("CASE", case.pk, provider=provider, actor=actor, action="EXPORT")
        yield case, actor
        enabled()
        permit(case, actor, provider, action)
        fresh = cases._identity(provider, subject_id, case)
        if provider.provider_id != provider_id or _identity(fresh) != _identity(actor):
            raise cases.CaseConflict("export_identity_changed")
        # No permission callback runs after this snapshot. Epoch getters are an
        # explicit atomic, side-effect-free integration contract.
        if _snapshot(case, kinds) != initial:
            raise cases.CaseConflict("export_policy_or_source_changed")
