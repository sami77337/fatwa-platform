"""Advisory classifications with exact source pins and independent human decisions.

No taxonomy table, publication mutation, semantic inference or automatic approval.
Locked adapters deliberately reuse knowledge_links' current-source validators.
"""

from django.conf import settings

from apps.casework import services as cases
from apps.knowledge_links import services as knowledge
from apps.knowledge_links.models import KnowledgeRevision
from apps.platform_recovery.integration import mutation_service

from .authority import ClassificationAuthority
from .models import ClassificationAction, ClassificationRevision


def _enabled():
    knowledge._enabled()
    if getattr(settings, "FATWA_CLASSIFICATION_REVIEW_ENABLED", False) is not True:
        raise cases.CaseConflict("classification_disabled")


def _permit(actor, provider, case, action):
    authority = getattr(settings, "FATWA_CLASSIFICATION_REVIEW_AUTHORITY", None)
    if not isinstance(authority, ClassificationAuthority):
        raise cases.CaseConflict("classification_authority_required")
    try:
        allowed = authority.permits(
            provider_id=provider.provider_id,
            subject_id=actor.subject_id,
            auth_epoch=actor.auth_epoch,
            case_ref=case.public_ref,
            action=action,
        )
    except Exception as exc:
        raise cases.CaseConflict("classification_authority_unavailable") from exc
    if allowed is not True:
        raise cases.CaseConflict("classification_action_denied")
    knowledge._recheck(case, actor, provider)


def _allowed(actor, provider, case, action):
    try:
        _permit(actor, provider, case, action)
        return True
    except cases.CaseConflict:
        return False


def _text(value, limit):
    cases._text(value)
    if len(value) > limit:
        raise cases.CaseConflict("classification_text_invalid")


def _source(edition, knowledge_id, subject_id, provider):
    row = KnowledgeRevision.objects.filter(
        pk=cases._uuid(knowledge_id), publication=edition
    ).first()
    if row is None or row.heading_id is None:
        raise cases.CaseConflict("classification_reference_required")
    knowledge._latest(row)
    if knowledge._state(row) != "APPROVED":
        raise cases.CaseConflict("classification_reviewed_source_required")
    knowledge._verified(row, edition, subject_id, provider)
    if not knowledge._row_permitted(edition.case, row, "READ"):
        raise cases.CaseConflict("classification_source_unavailable")
    snapshot = dict(
        knowledge_id=str(row.pk),
        knowledge_number=row.number,
        source=row.snapshot,
        source_digest=row.snapshot_sha256,
        publication_id=str(edition.pk),
        publication_number=edition.number,
        publication_digest=edition.content_sha256,
        existing_category=edition.category,
        namespace="EXPERIMENTAL_GENERAL_LABEL",
    )
    return row, snapshot


def _latest(row):
    if ClassificationRevision.objects.filter(series=row.series, number__gt=row.number).exists():
        raise cases.CaseConflict("classification_revision_changed")


def _state(row):
    actions = set(row.actions.values_list("action", flat=True))
    return next(
        (
            state
            for action, state in (
                ("WITHDRAW", "WITHDRAWN"),
                ("REJECT", "REJECTED"),
                ("APPROVE", "APPROVED"),
            )
            if action in actions
        ),
        "PROPOSED",
    )


def _row(edition, revision_id):
    row = ClassificationRevision.objects.filter(
        pk=cases._uuid(revision_id), knowledge__publication=edition
    ).first()
    if row is None:
        raise cases.CaseConflict("classification_unavailable")
    return row


def _verify(row, edition, subject_id, provider):
    if row.snapshot_sha256 != knowledge._digest(row.snapshot):
        raise cases.CaseConflict("classification_snapshot_changed")
    _, snapshot = _source(edition, row.knowledge_id, subject_id, provider)
    if snapshot != row.snapshot:
        raise cases.CaseConflict("classification_source_changed")


@mutation_service
def propose(
    *,
    publication_id,
    knowledge_id,
    label,
    reason,
    subject_id,
    provider,
    replaces_id=None,
    synthetic_fixtures_only=False,
):
    _enabled()
    _text(label, 80)
    _text(reason, 1000)
    with knowledge._edition(publication_id, subject_id, provider, synthetic_fixtures_only) as (
        edition,
        _,
        case,
        actor,
    ):
        _permit(actor, provider, case, "PROPOSE")
        source, snapshot = _source(edition, knowledge_id, subject_id, provider)
        previous = _row(edition, replaces_id) if replaces_id else None
        if previous:
            _latest(previous)
            if previous.number >= 64:
                raise cases.CaseConflict("classification_revision_capacity")
        elif (
            ClassificationRevision.objects.filter(knowledge__publication=edition, number=1).count()
            >= 32
        ):
            raise cases.CaseConflict("classification_capacity")
        row = ClassificationRevision.objects.create(
            knowledge=source,
            number=previous.number + 1 if previous else 1,
            label=label,
            reason=reason,
            snapshot=snapshot,
            snapshot_sha256=knowledge._digest(snapshot),
            subject_id=actor.subject_id,
            provider_id=provider.provider_id,
            auth_epoch=actor.auth_epoch,
            **({"series": previous.series} if previous else {}),
        )
        _permit(actor, provider, case, "PROPOSE")
        return {"id": str(row.pk), "number": row.number, "state": "PROPOSED"}


@mutation_service
def act(
    *,
    publication_id,
    revision_id,
    action,
    note,
    confirmed,
    subject_id,
    provider,
    synthetic_fixtures_only=False,
):
    _enabled()
    if action not in {"APPROVE", "REJECT", "WITHDRAW"} or confirmed is not True:
        raise cases.CaseConflict("classification_human_confirmation_required")
    _text(note, 1000)
    # Withdrawal must still work when source rights, knowledge, or publication lapse.
    scope = knowledge._withdrawal_edition if action == "WITHDRAW" else knowledge._edition
    with scope(publication_id, subject_id, provider, synthetic_fixtures_only) as (
        edition,
        _,
        case,
        actor,
    ):
        _permit(actor, provider, case, action)
        row = _row(edition, revision_id)
        _latest(row)
        if _state(row) == "WITHDRAWN" or (action != "WITHDRAW" and _state(row) != "PROPOSED"):
            raise cases.CaseConflict("classification_decision_conflict")
        if action != "WITHDRAW":
            _verify(row, edition, subject_id, provider)
            if (row.provider_id, row.subject_id) == (provider.provider_id, actor.subject_id):
                raise cases.CaseConflict("classification_independent_human_required")
        ClassificationAction.objects.create(
            revision=row,
            action=action,
            note=note,
            subject_id=actor.subject_id,
            provider_id=provider.provider_id,
            auth_epoch=actor.auth_epoch,
        )
        _permit(actor, provider, case, action)
        return {"id": str(row.pk), "state": _state(row)}


@mutation_service
def desk(*, publication_id, subject_id, provider, synthetic_fixtures_only=False, history=False):
    _enabled()
    scope = knowledge._withdrawal_edition if history else knowledge._edition
    with scope(publication_id, subject_id, provider, synthetic_fixtures_only) as (
        edition,
        _,
        case,
        actor,
    ):
        _permit(actor, provider, case, "VIEW")
        can_propose = _allowed(actor, provider, case, "PROPOSE")
        grants = {
            action: _allowed(actor, provider, case, action)
            for action in ("APPROVE", "REJECT", "WITHDRAW")
        }
        candidates = []
        if not history:
            for source in KnowledgeRevision.objects.filter(
                publication=edition, heading__isnull=False
            ):
                try:
                    _, snapshot = _source(edition, source.pk, subject_id, provider)
                except cases.CaseConflict:
                    continue
                candidates.append({"id": str(source.pk), "source": snapshot["source"]["source"]})
        rows, seen = [], set()
        for row in (
            ClassificationRevision.objects.filter(knowledge__publication=edition)
            .select_related("knowledge")
            .order_by("series", "-number")
        ):
            current = row.series not in seen
            seen.add(row.series)
            available = False
            if not history:
                try:
                    _verify(row, edition, subject_id, provider)
                    available = True
                except cases.CaseConflict:
                    pass
            state = _state(row)
            independent = (row.provider_id, row.subject_id) != (
                provider.provider_id,
                actor.subject_id,
            )
            can_review = current and available and state == "PROPOSED" and independent
            can_approve = can_review and grants["APPROVE"]
            can_reject = can_review and grants["REJECT"]
            can_withdraw = current and state != "WITHDRAWN" and grants["WITHDRAW"]
            # Audit after upstream withdrawal keeps IDs/state/time only. No stale source,
            # candidate label, rationale or decision text escapes through history.
            rows.append(
                dict(
                    id=str(row.pk),
                    number=row.number,
                    state=state,
                    can_approve=can_approve,
                    can_reject=can_reject,
                    can_withdraw=can_withdraw,
                    can_decide=can_approve or can_reject or can_withdraw,
                    current=current,
                    available=available,
                    label=row.label if available else "",
                    reason=row.reason if available else "",
                    source=row.snapshot["source"]["source"] if available else None,
                    created_at=row.created_at,
                    subject_id=row.subject_id,
                    actions=list(
                        row.actions.order_by("created_at", "id").values(
                            "action", "subject_id", "created_at", *(["note"] if available else [])
                        )
                    ),
                    effective=current and available and _state(row) == "APPROVED",
                )
            )
        _permit(actor, provider, case, "VIEW")
        return {
            "publication_id": str(edition.pk),
            "existing_category": edition.category if not history else "",
            "candidates": candidates,
            "history": rows,
            "audit_only": history,
            "can_propose": can_propose,
        }
