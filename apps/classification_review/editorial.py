"""Explicit synthetic transfer to canonical publication, never an approval side effect.

The existing publication create/act APIs remain authoritative. This adapter adds
classification provenance and a default-deny simulation policy, under their native
ownership unit and canonical case lock. No source/rights guard is bypassed.
"""

from contextlib import contextmanager

from django.conf import settings
from django.db import connection

from apps.case_citations import services as citations
from apps.casework import services as cases
from apps.delivery_queue.services import synthetic_queue_atomic
from apps.experimental_publication import services as publications
from apps.experimental_publication.models import PublicationEdition
from apps.knowledge_links import services as knowledge
from apps.platform_recovery.integration import mutation_service

from . import services
from .authority import EditorialSimulationPolicy
from .models import EditorialBinding


def _enabled():
    services._enabled()
    if getattr(settings, "FATWA_CLASSIFICATION_EDITORIAL_SIMULATION_ENABLED", False) is not True:
        raise cases.CaseConflict("classification_editorial_simulation_disabled")
    if any(
        getattr(settings, name, False) is not True
        for name in (
            "FATWA_SOURCE_RIGHTS_ENABLED",
            "FATWA_SOURCE_RIGHTS_ENFORCED",
            "FATWA_RECOVERY_MAINTENANCE_REQUIRED",
        )
    ):
        raise cases.CaseConflict("classification_editorial_strict_composition_required")
    policy = getattr(settings, "FATWA_CLASSIFICATION_EDITORIAL_SIMULATION_POLICY", None)
    if not isinstance(policy, EditorialSimulationPolicy):
        raise cases.CaseConflict("classification_editorial_policy_required")
    services._text(policy.policy_id, 128)
    return policy


def _permit(actor, provider, case, row, action, policy_id=None):
    policy = _enabled()
    if policy_id is not None and policy.policy_id != policy_id:
        raise cases.CaseConflict("classification_editorial_policy_changed")
    granted_policy_id = policy.policy_id
    try:
        allowed = policy.permits(
            provider_id=provider.provider_id,
            subject_id=actor.subject_id,
            auth_epoch=actor.auth_epoch,
            case_ref=case.public_ref,
            revision_id=str(row.pk),
            action=action,
        )
    except Exception as exc:
        raise cases.CaseConflict("classification_editorial_policy_unavailable") from exc
    if allowed is not True:
        raise cases.CaseConflict("classification_editorial_action_denied")
    if _enabled() is not policy or policy.policy_id != granted_policy_id:
        raise cases.CaseConflict("classification_editorial_policy_changed")
    services._permit(actor, provider, case, "VIEW")
    return granted_policy_id


def _classification(row, source, case, subject_id, provider):
    services._latest(row)
    if services._state(row) != "APPROVED":
        raise cases.CaseConflict("classification_editorial_approval_required")
    services._verify(row, source, subject_id, provider)
    publications._verify(source)
    publications._approved(case, source)
    if source.actions.filter(action="WITHDRAW").exists():
        raise cases.CaseConflict("classification_editorial_source_withdrawn")
    if source.citations != publications._citation_snapshot(source.answer):
        raise cases.CaseConflict("classification_editorial_source_changed")
    publications._require_publication_sources(case, source.citations)


def _snapshot(row, source, edition, policy_id):
    return dict(
        classification_id=str(row.pk),
        classification_number=row.number,
        classification_digest=row.snapshot_sha256,
        label=row.label,
        source_edition_id=str(source.pk),
        source_edition_number=source.number,
        source_edition_digest=source.content_sha256,
        target_edition_id=str(edition.pk),
        target_edition_number=edition.number,
        target_edition_digest=edition.content_sha256,
        policy_id=policy_id,
        mode="CLOSED_SYNTHETIC_SIMULATION",
    )


def _binding(binding, case, subject_id, provider):
    row, target = binding.revision, binding.edition
    source = row.knowledge.publication
    if source.case_id != case.pk or target.case_id != case.pk:
        raise cases.CaseConflict("classification_editorial_binding_invalid")
    _classification(row, source, case, subject_id, provider)
    publications._verify(target)
    publications._approved(case, target)
    if (
        target.category != row.label
        or target.title != source.title
        or target.body != source.body
        or target.citations != source.citations
        or target.answer_id != source.answer_id
        or target.decision_id != source.decision_id
        or target.evidence_version != source.evidence_version
    ):
        raise cases.CaseConflict("classification_editorial_copy_changed")
    expected = _snapshot(row, source, target, binding.policy_id)
    if binding.snapshot != expected or binding.snapshot_sha256 != knowledge._digest(expected):
        raise cases.CaseConflict("classification_editorial_snapshot_changed")
    latest = (
        PublicationEdition.objects.filter(case=case, actions__action="APPROVE")
        .order_by("-number")
        .first()
    )
    if latest is None or latest.pk not in {source.pk, target.pk}:
        raise cases.CaseConflict("classification_editorial_publication_changed")
    if target.actions.filter(action="WITHDRAW").exists():
        raise cases.CaseConflict("classification_editorial_target_withdrawn")
    return row, source, target


@mutation_service
def prepare_edition(
    *,
    publication_id,
    revision_id,
    expected_revision,
    expected_evidence_version,
    confirmed,
    subject_id,
    provider,
    synthetic_fixtures_only=False,
):
    _enabled()
    if confirmed is not True:
        raise cases.CaseConflict("classification_editorial_confirmation_required")
    cases._mutation_versions(expected_revision, expected_evidence_version)
    # Sole ownership preflight precedes transaction; canonical APIs nest through
    # their existing execution-local composition unit, not an arbitrary atomic.
    with (
        synthetic_queue_atomic(),
        knowledge._edition(publication_id, subject_id, provider, synthetic_fixtures_only) as (
            source,
            _,
            case,
            actor,
        ),
    ):
        cases._versions(case, expected_revision, expected_evidence_version)
        row = services._row(source, revision_id)
        policy_id = _permit(actor, provider, case, row, "PREPARE")
        _classification(row, source, case, subject_id, provider)
        if EditorialBinding.objects.filter(revision=row).exists():
            raise cases.CaseConflict("classification_editorial_already_prepared")
        candidate = publications.create_edition(
            case_id=case.pk,
            subject_id=subject_id,
            provider=provider,
            expected_revision=expected_revision,
            expected_evidence_version=expected_evidence_version,
            title=source.title,
            category=row.label,
            body=source.body,
            source_edition_id=source.pk,
            synthetic_fixtures_only=synthetic_fixtures_only,
        )
        edition = PublicationEdition.objects.get(pk=candidate["id"])
        snapshot = _snapshot(row, source, edition, policy_id)
        binding = EditorialBinding.objects.create(
            revision=row,
            edition=edition,
            policy_id=policy_id,
            snapshot=snapshot,
            snapshot_sha256=knowledge._digest(snapshot),
            subject_id=actor.subject_id,
            provider_id=provider.provider_id,
            auth_epoch=actor.auth_epoch,
        )
        _permit(actor, provider, case, row, "PREPARE", policy_id)
        _binding(binding, case, subject_id, provider)
        return {
            "binding_id": str(binding.pk),
            "edition_id": str(edition.pk),
            "number": edition.number,
            "state": "CANDIDATE",
            "mode": snapshot["mode"],
        }


@contextmanager
def _native_action(binding, action):
    # Transaction-local admission for the bound edition's DB action trigger.
    # General publication endpoints cannot skip this policy/source adapter.
    with connection.cursor() as cursor:
        cursor.execute("SELECT current_setting('fatwa.classification_editorial', true)")
        previous = cursor.fetchone()[0] or ""
        cursor.execute(
            "SELECT set_config('fatwa.classification_editorial', %s, true)",
            [f"{binding.pk}:{action}"],
        )
    try:
        yield
    finally:
        # Failed DB statements leave their savepoint unusable; the surrounding
        # transaction rolls the local marker back along with the failed action.
        if not connection.needs_rollback:
            with connection.cursor() as cursor:
                cursor.execute(
                    "SELECT set_config('fatwa.classification_editorial', %s, true)", [previous]
                )


def _lookup(publication_id, binding_id, subject_id, provider, ack):
    cases._guard(ack)
    binding = (
        EditorialBinding.objects.select_related("revision__knowledge__publication", "edition")
        .filter(
            pk=cases._uuid(binding_id),
            revision__knowledge__publication_id=cases._uuid(publication_id),
        )
        .first()
    )
    if binding is None:
        raise cases.CaseConflict("classification_editorial_unavailable")
    return binding


@mutation_service
def act(
    *,
    publication_id,
    binding_id,
    action,
    confirmed,
    subject_id,
    provider,
    synthetic_fixtures_only=False,
):
    _enabled()
    if action not in {"REVIEW", "APPROVE"} or confirmed is not True:
        raise cases.CaseConflict("classification_editorial_confirmation_required")
    with synthetic_queue_atomic():
        binding = _lookup(publication_id, binding_id, subject_id, provider, synthetic_fixtures_only)
        with (
            cases._staff_case(
                binding.edition.case_id, subject_id, provider, synthetic_fixtures_only
            ) as (case, actor),
            citations._projection_expiry_guard(),
        ):
            row = binding.revision
            _permit(actor, provider, case, row, action, binding.policy_id)
            _binding(binding, case, subject_id, provider)
            if action == "APPROVE":
                classification_approver = row.actions.get(action="APPROVE")
                if (provider.provider_id, actor.subject_id) in {
                    (row.provider_id, row.subject_id),
                    (classification_approver.provider_id, classification_approver.subject_id),
                }:
                    raise cases.CaseConflict(
                        "classification_editorial_independent_publisher_required"
                    )
            with _native_action(binding, action):
                result = publications.act(
                    case_id=case.pk,
                    edition_id=binding.edition_id,
                    subject_id=subject_id,
                    provider=provider,
                    action=action,
                    reviewed=action == "REVIEW",
                    synthetic_fixtures_only=synthetic_fixtures_only,
                )
            _permit(actor, provider, case, row, action, binding.policy_id)
            _binding(binding, case, subject_id, provider)
            knowledge._recheck(case, actor, provider)
            return {
                "binding_id": str(binding.pk),
                "edition_id": result["id"],
                "state": result["state"],
                "mode": "CLOSED_SYNTHETIC_SIMULATION",
            }


@mutation_service
def inspect(*, publication_id, binding_id, subject_id, provider, synthetic_fixtures_only=False):
    _enabled()
    with synthetic_queue_atomic():
        binding = _lookup(publication_id, binding_id, subject_id, provider, synthetic_fixtures_only)
        with (
            cases._staff_case(
                binding.edition.case_id, subject_id, provider, synthetic_fixtures_only
            ) as (case, actor),
            citations._projection_expiry_guard(),
        ):
            _permit(actor, provider, case, binding.revision, "INSPECT", binding.policy_id)
            row, source, target = _binding(binding, case, subject_id, provider)
            actions = set(target.actions.values_list("action", flat=True))
            latest_candidate = target.number == PublicationEdition.objects.filter(case=case).count()

            def permitted(action):
                try:
                    _permit(actor, provider, case, row, action, binding.policy_id)
                    return True
                except cases.CaseConflict:
                    return False

            reviewer = target.actions.filter(action="REVIEW").first()
            classification_approver = row.actions.get(action="APPROVE")
            independent = (provider.provider_id, actor.subject_id) not in {
                (row.provider_id, row.subject_id),
                (classification_approver.provider_id, classification_approver.subject_id),
                (target.provider_id, target.subject_id),
                (target.decision.provider_id, target.decision.subject_id),
                (reviewer.provider_id, reviewer.subject_id) if reviewer else (None, None),
            }
            can_review = latest_candidate and not actions and permitted("REVIEW")
            can_approve = (
                latest_candidate
                and actions == {"REVIEW"}
                and independent
                and permitted("APPROVE")
                and publications._permitted(actor, provider, case, "APPROVE")
            )
            result = dict(
                binding_id=str(binding.pk),
                publication_id=str(source.pk),
                revision_id=str(row.pk),
                policy_id=binding.policy_id,
                edition=publications._projection(target, editorial=True),
                classification_reason=row.reason,
                source=row.snapshot["source"]["source"],
                mode="CLOSED_SYNTHETIC_SIMULATION",
                public_ref=case.public_ref,
                can_review=can_review,
                can_approve=can_approve,
            )
            _permit(actor, provider, case, row, "INSPECT", binding.policy_id)
            _binding(binding, case, subject_id, provider)
            knowledge._recheck(case, actor, provider)
            return result
