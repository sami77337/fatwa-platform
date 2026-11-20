"""Reentrant import + canonical library policy boundary through the final renderer."""

import os
from contextlib import contextmanager
from contextvars import ContextVar

from django.conf import settings
from django.utils import timezone

from apps.casework import services as cases
from apps.delivery_queue.services import synthetic_queue_atomic
from apps.platform_recovery.integration import mutation_context

from .authority import ImportAuthority

_HEADS = ContextVar("material_import_expected_heads", default=())


def enabled():
    if (
        os.environ.get("FATWA_PRODUCTION") != "0"
        or getattr(settings, "FATWA_MATERIAL_IMPORT_ENABLED", False) is not True
    ):
        raise cases.CaseConflict("material_import_disabled")


def authority():
    selected = getattr(settings, "FATWA_MATERIAL_IMPORT_AUTHORITY", None)
    if not isinstance(selected, ImportAuthority):
        raise cases.CaseConflict("import_authority_required")
    return selected


def snapshot():
    selected = authority()
    try:
        epoch = selected.projection_epoch()
    except Exception as exc:
        raise cases.CaseConflict("import_policy_snapshot_required") from exc
    if type(epoch) is not str or not 1 <= len(epoch) <= 1000:
        raise cases.CaseConflict("import_policy_snapshot_required")
    return selected, epoch, getattr(settings, "FATWA_MATERIAL_IMPORT_ENABLED", None)


def assert_snapshot(expected):
    current = snapshot()
    if current[0] is not expected[0] or current[1:] != expected[1:]:
        raise cases.CaseConflict("import_policy_changed")


def history_fingerprint(case_id):
    """Pure append-only receipt heads, including empty-set and expiry transitions."""
    from .models import (
        GroupResult,
        ImportBatch,
        ImportDecision,
        ImportEvent,
        ImportPlan,
        MappingRevision,
    )

    now = timezone.now()
    batches = tuple(
        (str(pk), expires_at <= now)
        for pk, expires_at in ImportBatch.objects.filter(case_id=case_id)
        .order_by("pk")
        .values_list("pk", "expires_at")
    )
    children = []
    for model, relation in (
        (MappingRevision, "batch__case_id"),
        (ImportPlan, "batch__case_id"),
        (ImportDecision, "plan__batch__case_id"),
        (GroupResult, "plan__batch__case_id"),
        (ImportEvent, "batch__case_id"),
    ):
        children.append(
            tuple(
                str(pk)
                for pk in model.objects.filter(**{relation: case_id})
                .order_by("pk")
                .values_list("pk", flat=True)
            )
        )
    return (batches, *children)


def permit(case, actor, provider, action, namespace):
    try:
        result = authority().permits(
            provider_id=provider.provider_id,
            subject_id=actor.subject_id,
            auth_epoch=actor.auth_epoch,
            case_ref=case.public_ref,
            action=action,
            namespace=namespace,
        )
    except cases.CaseConflict:
        raise
    except Exception as exc:
        raise cases.CaseConflict("import_authority_unavailable") from exc
    if result is not True:
        raise cases.CaseConflict("import_not_authorized")


@mutation_context
@contextmanager
def boundary(*, action="VIEW", namespace="", allow_library_writes=False, **base):
    from apps.research_library import services as library

    enabled()
    with synthetic_queue_atomic():
        with library.staff_boundary(**base) as (case, actor):
            expected = {str(row[0]): tuple(row) for row in library.head_fingerprint(case.pk)}
            history = history_fingerprint(case.pk) if action == "VIEW" else None
            frame = (case.pk, expected, allow_library_writes)
            token = _HEADS.set((*_HEADS.get(), frame))
            try:
                initial = snapshot()
                identity = library.identity_snapshot(base["provider"])
                permit(case, actor, base["provider"], action, namespace)
                yield case, actor
                enabled()
                permit(case, actor, base["provider"], action, namespace)
                assert_snapshot(initial)
            finally:
                _HEADS.reset(token)
        # All library permission callbacks have now completed; this outer
        # transaction is still open, so a changed head rolls back the whole group.
        actual = {str(row[0]): tuple(row) for row in library.head_fingerprint(case.pk)}
        assert_snapshot(initial)
        if library.identity_snapshot(base["provider"]) != identity:
            raise cases.CaseConflict("import_final_authority_changed")
        if actual != expected:
            raise cases.CaseConflict("import_library_heads_changed")
        if history is not None and history_fingerprint(case.pk) != history:
            raise cases.CaseConflict("import_history_changed")


def record_material(case_id, namespace, external_id, result):
    """Accept only an explicitly executed canonical write, never hidden extras."""
    found = False
    for selected_case, heads, allowed in _HEADS.get():
        if selected_case == case_id and allowed:
            heads[result["item_id"]] = (
                result["item_id"],
                namespace,
                external_id,
                result["version_id"],
                result["number"],
                result["digest"],
            )
            found = True
    if not found:
        raise cases.CaseConflict("import_write_boundary_required")
