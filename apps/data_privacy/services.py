"""Human classification ledger and current policy checks through final composition.

This extra boundary never replaces a domain's identity, source, release or export
permission. It retains pure pins after all policy/identity callbacks have run.
"""

import json
import os
import uuid
from contextlib import contextmanager, nullcontext
from contextvars import ContextVar
from dataclasses import dataclass
from datetime import datetime, timedelta

from django.apps import apps
from django.conf import settings
from django.db import connection
from django.utils import timezone

from apps.answer_media.editor_boundary import identity_snapshot
from apps.casework import services as cases
from apps.delivery_queue.models import RequesterTrackingToken
from apps.delivery_queue.services import synthetic_queue_atomic
from apps.mufti_review.identity import MuftiIdentityProvider
from apps.operational_workspace import identity as operational_identity
from apps.platform_recovery.integration import mutation_service

from .authority import Grant, PrivacyAuthority, UnclassifiedWorkGrant
from .catalog import ACTIONS, LEVELS, Target, digest, locate

ZERO = "0" * 64
SCOPES = ContextVar("data_privacy_projections", default=())


class PrivacyDenied(cases.CaseConflict):
    pass


def enabled():
    return getattr(settings, "FATWA_DATA_PRIVACY_ENABLED", False) is True


def _model():
    if not apps.is_installed("apps.data_privacy"):
        raise PrivacyDenied("privacy_application_required")
    return apps.get_model("data_privacy.ClassificationRevision")


def recorded(kind, identifier):
    """Restored labels cannot disappear because an older profile omits the app."""
    if apps.is_installed("apps.data_privacy"):
        return _model().objects.filter(target_kind=kind, target_id=identifier).exists()
    with connection.cursor() as cursor:
        cursor.execute("SELECT to_regclass('data_privacy_classificationrevision')")
        if cursor.fetchone()[0] is None:
            return False
        cursor.execute(
            "SELECT EXISTS (SELECT 1 FROM data_privacy_classificationrevision "
            "WHERE target_kind=%s AND target_id=%s)",
            [kind, identifier],
        )
        return cursor.fetchone()[0]


def applicable(kind, identifier):
    from apps.record_suppression.integration import require as current_material

    current_material(kind, identifier)
    if enabled():
        return True
    if recorded(kind, identifier):
        raise PrivacyDenied("privacy_recorded_policy_required")
    return False


def policy():
    authority = getattr(settings, "FATWA_DATA_PRIVACY_AUTHORITY", None)
    if (
        not enabled()
        or os.environ.get("FATWA_PRODUCTION") != "0"
        or not isinstance(authority, PrivacyAuthority)
    ):
        raise PrivacyDenied("privacy_explicit_policy_required")
    _model()
    try:
        epoch = authority.projection_epoch()
    except Exception as exc:
        raise PrivacyDenied("privacy_policy_snapshot_required") from exc
    if type(epoch) is not str or not 1 <= len(epoch) <= 131072:
        raise PrivacyDenied("privacy_policy_snapshot_required")
    return authority, epoch


def assert_policy(expected):
    current = policy()
    if current[0] is not expected[0] or current[1] != expected[1]:
        raise PrivacyDenied("privacy_policy_changed")


def _lock(target):
    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT pg_advisory_xact_lock(hashtextextended(%s, 391395))",
            [target.kind + ":" + target.identifier],
        )


def _body(row):
    result = {}
    for field in row._meta.concrete_fields:
        if field.name in {"canonical_payload", "digest", "created_at"}:
            continue
        value = getattr(row, field.attname)
        result[field.attname] = str(value) if isinstance(value, uuid.UUID) else value
    return result


def _verify(row):
    if (
        json.loads(row.canonical_payload) != _body(row)
        or digest(_body(row)) != row.digest
        or row.level not in LEVELS
    ):
        raise PrivacyDenied("privacy_ledger_changed")


def history(target):
    rows = list(
        _model()
        .objects.filter(target_kind=target.kind, target_id=target.identifier)
        .order_by("number")[:257]
    )
    if len(rows) > 256:
        raise PrivacyDenied("privacy_history_bound")
    previous = ZERO
    for number, row in enumerate(rows, 1):
        _verify(row)
        if row.number != number or row.previous_digest != previous:
            raise PrivacyDenied("privacy_ledger_changed")
        previous = row.digest
    return rows


def current(target):
    rows = history(target)
    if not rows:
        raise PrivacyDenied("privacy_classification_required")
    row = rows[-1]
    if (
        row.source_digest != target.source_digest
        or (str(row.case_id) if row.case_id else None) != target.case_id
    ):
        raise PrivacyDenied("privacy_classification_source_changed")
    return row


@dataclass(frozen=True, slots=True)
class Principal:
    audience: str
    provider_id: str = ""
    subject_id: str = ""
    auth_epoch: str = ""
    role: str = ""
    valid_until: datetime | None = None
    provider: object = None
    actor: object = None
    token_digest: str = ""
    case_id: str = ""
    identity_pin: object = None


def staff_principal(provider, actor):
    directory = getattr(settings, "FATWA_CASEWORK_IDENTITY_PROVIDER", None)
    from apps.ai_gateway.identity import SessionDirectory
    from apps.casework_web.access import RequestDirectory

    if not isinstance(directory, MuftiIdentityProvider) or not (
        provider is directory
        or (type(provider) is RequestDirectory and provider._provider is directory)
        or (type(provider) is SessionDirectory and provider._provider is directory)
        or (
            type(provider) is operational_identity.RequestDirectory
            and provider.directory is directory
        )
    ):
        raise PrivacyDenied("privacy_current_directory_required")
    operational_identity.validate(actor)
    pin = identity_snapshot(provider)
    fresh = operational_identity.validate(
        provider.resolve(actor.subject_id), subject_id=actor.subject_id
    )
    if operational_identity.pin(fresh) != operational_identity.pin(actor):
        raise PrivacyDenied("privacy_identity_changed")
    return Principal(
        "STAFF",
        provider.provider_id,
        actor.subject_id,
        actor.auth_epoch,
        actor.role,
        min(actor.valid_until, fresh.valid_until),
        provider,
        actor,
        identity_pin=(pin, id(directory)),
    )


def requester_principal(case, token_digest):
    grant = RequesterTrackingToken.objects.filter(pk=token_digest, case_id=case.tracking_id).first()
    if grant is None or grant.revoked_at is not None or grant.expires_at <= timezone.now():
        raise PrivacyDenied("privacy_requester_unavailable")
    return Principal(
        "REQUESTER",
        "casework-requester",
        case.requester_id,
        token_digest,
        "REQUESTER",
        grant.expires_at,
        token_digest=token_digest,
        case_id=str(case.pk),
        identity_pin=(str(case.tracking_id), grant.expires_at),
    )


def public_principal():
    return Principal("PUBLIC")


def _identity_callbacks(principal):
    if principal.audience == "STAFF":
        fresh = operational_identity.validate(
            principal.provider.resolve(principal.subject_id), subject_id=principal.subject_id
        )
        if operational_identity.pin(fresh) != operational_identity.pin(principal.actor):
            raise PrivacyDenied("privacy_identity_changed")
        return min(principal.valid_until, fresh.valid_until)
    return principal.valid_until


def _identity_pins(principal):
    if principal.audience == "STAFF":
        if (
            identity_snapshot(principal.provider),
            id(getattr(settings, "FATWA_CASEWORK_IDENTITY_PROVIDER", None)),
        ) != principal.identity_pin:
            raise PrivacyDenied("privacy_identity_changed")
    elif principal.audience == "REQUESTER":
        grant = RequesterTrackingToken.objects.filter(pk=principal.token_digest).first()
        if (
            grant is None
            or grant.revoked_at is not None
            or (str(grant.case_id), grant.expires_at) != principal.identity_pin
            or grant.expires_at <= timezone.now()
        ):
            raise PrivacyDenied("privacy_requester_unavailable")
    elif principal.audience != "PUBLIC":
        raise PrivacyDenied("privacy_audience_invalid")
    if principal.valid_until is not None and principal.valid_until <= timezone.now():
        raise PrivacyDenied("privacy_identity_expired")


def _permission(selected, principal, target, level, action, previous_level=""):
    if action not in ACTIONS:
        raise PrivacyDenied("privacy_action_invalid")
    if principal.audience == "PUBLIC" and level != "PUBLIC":
        raise PrivacyDenied("privacy_classification_denied")
    if principal.audience == "REQUESTER" and target.case_id != principal.case_id:
        raise PrivacyDenied("privacy_requester_scope_denied")
    try:
        grant = selected[0].authorize(
            audience=principal.audience,
            provider_id=principal.provider_id,
            subject_id=principal.subject_id,
            auth_epoch=principal.auth_epoch,
            role=principal.role,
            case_ref=target.case_ref,
            target_kind=target.kind,
            target_id=target.identifier,
            source_digest=target.source_digest,
            classification=level,
            previous_level=previous_level,
            action=action,
        )
    except Exception as exc:
        raise PrivacyDenied("privacy_authority_unavailable") from exc
    if (
        type(grant) is not Grant
        or not isinstance(grant.valid_until, datetime)
        or not timezone.is_aware(grant.valid_until)
        or grant.valid_until.utcoffset() != timedelta(0)
        or not timezone.now() < grant.valid_until <= timezone.now() + timedelta(hours=1)
    ):
        raise PrivacyDenied("privacy_action_denied")
    return min(value for value in (grant.valid_until, principal.valid_until) if value is not None)


@dataclass(frozen=True, slots=True)
class UnclassifiedWork:
    """A pinned absence of human classification, never a fifth ledger level."""

    digest: str
    level: str = "UNCLASSIFIED_WORK"
    number: int = 0


def _work_permission(selected, principal, target, action):
    # A core human answer must not depend on completing classification. This
    # narrow opt-in remains a separate exact private-read permission; no label,
    # broad role default or implicit source/recipient permission is manufactured.
    if (
        principal.audience != "STAFF"
        or action != "READ"
        or target.kind.startswith("PUBLIC")
        or not target.case_ref
        or target.case_ref not in principal.actor.case_keys
    ):
        raise PrivacyDenied("privacy_classification_required")
    values = dict(
        audience=principal.audience,
        provider_id=principal.provider_id,
        subject_id=principal.subject_id,
        auth_epoch=principal.auth_epoch,
        role=principal.role,
        case_ref=target.case_ref,
        target_kind=target.kind,
        target_id=target.identifier,
        source_digest=target.source_digest,
        provenance="UNCLASSIFIED_WORK",
        action=action,
    )
    try:
        grant = selected[0].authorize_unclassified_work(**values)
    except Exception as exc:
        raise PrivacyDenied("privacy_authority_unavailable") from exc
    if (
        type(grant) is not UnclassifiedWorkGrant
        or grant.binding_sha256 != digest(values)
        or not isinstance(grant.valid_until, datetime)
        or not timezone.is_aware(grant.valid_until)
        or grant.valid_until.utcoffset() != timedelta(0)
        or not timezone.now() < grant.valid_until <= timezone.now() + timedelta(hours=1)
    ):
        raise PrivacyDenied("privacy_classification_required")
    return min(grant.valid_until, principal.valid_until)


@dataclass(slots=True)
class Use:
    target: Target
    classification: object
    principal: Principal
    action: str
    selected: tuple
    deadline: datetime

    def callbacks(self):
        deadline = (
            _work_permission(self.selected, self.principal, self.target, self.action)
            if type(self.classification) is UnclassifiedWork
            else _permission(
                self.selected, self.principal, self.target, self.classification.level, self.action
            )
        )
        identity_deadline = _identity_callbacks(self.principal)
        self.deadline = min(
            value for value in (self.deadline, deadline, identity_deadline) if value is not None
        )

    def final_pins(self):
        assert_policy(self.selected)
        _identity_pins(self.principal)
        if locate(self.target.kind, self.target.identifier) != self.target:
            raise PrivacyDenied("privacy_source_changed")
        if type(self.classification) is UnclassifiedWork:
            if history(self.target):
                raise PrivacyDenied("privacy_classification_changed")
        elif current(self.target).digest != self.classification.digest:
            raise PrivacyDenied("privacy_classification_changed")
        if timezone.now() >= self.deadline:
            raise PrivacyDenied("privacy_permission_expired")


class Projection:
    def __init__(self):
        self.flag = (type(getattr(settings, "FATWA_DATA_PRIVACY_ENABLED", None)), enabled())
        self.uses = []
        self.retained_suppression = []

    def callbacks(self):
        for use in self.uses:
            use.callbacks()

    def final_pins(self):
        if (type(getattr(settings, "FATWA_DATA_PRIVACY_ENABLED", None)), enabled()) != self.flag:
            raise PrivacyDenied("privacy_configuration_changed")
        for use in self.uses:
            use.final_pins()
        for use in self.retained_suppression:
            use.final_pins()

    def finish(self):
        # Mandatory current callbacks ran in require(), before source consumption.
        # A new callback here could revoke a source AFTER its domain's final pins.
        # Adapters may explicitly call callbacks() before all final source pins.
        self.final_pins()


@contextmanager
def projection(*, atomic=True):
    guard = Projection()
    token = SCOPES.set((*SCOPES.get(), guard))
    try:
        with synthetic_queue_atomic() if enabled() and atomic else nullcontext():
            yield guard
            guard.finish()
    finally:
        SCOPES.reset(token)


def require(kind, identifier, *, principal, action="READ"):
    """Call before building a DTO, filename, result count, link or output bytes."""
    identifier = str(cases._uuid(identifier))
    if not applicable(kind, identifier):
        return None
    if not SCOPES.get():
        with projection():
            return require(kind, identifier, principal=principal, action=action)
    if not connection.in_atomic_block:
        # A response may retain pins across multiple short reads and an external
        # call. Only each current source admission holds the owned transaction.
        with synthetic_queue_atomic():
            return require(kind, identifier, principal=principal, action=action)
    selected = policy()
    target = locate(kind, identifier)
    _lock(target)
    target = locate(kind, identifier)
    if history(target):
        # A recorded stale/corrupt label must never fall back to unclassified use.
        row = current(target)
        deadline = _permission(selected, principal, target, row.level, action)
    else:
        deadline = _work_permission(selected, principal, target, action)
        row = UnclassifiedWork(digest(["unclassified-work.v1", target.source_digest, ZERO]))
    use = Use(target, row, principal, action, selected, deadline)
    use.final_pins()
    for scope in SCOPES.get():
        scope.uses.append(use)
    return {"level": row.level, "revision": row.number, "digest": row.digest}


@mutation_service
def classify(
    *,
    kind,
    identifier,
    level,
    note,
    expected_digest,
    expected_source_digest,
    request_key,
    provider,
    subject_id,
    synthetic_fixtures_only=False,
    session_deadline=None,
):
    cases._guard(synthetic_fixtures_only)
    selected = policy()
    if level not in LEVELS or type(note) is not str or not 1 <= len(note.strip()) <= 1000:
        raise PrivacyDenied("privacy_classification_invalid")
    key = cases._uuid(request_key)
    target = locate(kind, identifier)
    actor = operational_identity.validate(provider.resolve(subject_id), subject_id=subject_id)
    if session_deadline is not None:
        from dataclasses import replace

        if not operational_identity.valid_deadline(session_deadline):
            raise PrivacyDenied("privacy_session_expired")
        actor = replace(actor, valid_until=min(actor.valid_until, session_deadline))
    principal = staff_principal(provider, actor)
    if target.case_ref and target.case_ref not in actor.case_keys:
        raise PrivacyDenied("privacy_classification_scope_denied")
    with synthetic_queue_atomic():
        with connection.cursor() as cursor:
            cursor.execute("SELECT pg_advisory_xact_lock(546131,1)")
        if target.case_id:
            cases.Case.objects.select_for_update().get(pk=target.case_id)
        _lock(target)
        if locate(kind, identifier) != target or target.source_digest != expected_source_digest:
            raise PrivacyDenied("privacy_source_changed")
        rows = history(target)
        old = rows[-1] if rows else None
        before = old.digest if old else ZERO
        previous_level = old.level if old else ""
        deadline = _permission(selected, principal, target, level, "CLASSIFY", previous_level)
        request = digest(
            [
                kind,
                target.identifier,
                target.source_digest,
                level,
                note,
                expected_digest,
                provider.provider_id,
                actor.subject_id,
                actor.auth_epoch,
            ]
        )
        existing = _model().objects.filter(request_key=key).first()
        if existing:
            _verify(existing)
            if existing.request_digest != request or before != existing.digest:
                raise PrivacyDenied("privacy_request_replay_conflict")
            result = existing
        else:
            if expected_digest != before or len(rows) >= 256:
                raise PrivacyDenied("privacy_classification_stale")
            result = _model()(
                target_kind=kind,
                target_id=target.identifier,
                case_id=target.case_id,
                source_digest=target.source_digest,
                number=len(rows) + 1,
                previous_digest=before,
                level=level,
                note=note,
                request_key=key,
                request_digest=request,
                provider_id=provider.provider_id,
                subject_id=actor.subject_id,
                auth_epoch=actor.auth_epoch,
                policy_digest=digest(selected[1]),
            )
            result.canonical_payload = json.dumps(
                _body(result), ensure_ascii=False, sort_keys=True, separators=(",", ":")
            )
            result.digest = digest(_body(result))
            result.save(force_insert=True)
            result.refresh_from_db(fields=("created_at",))
        final_deadline = _permission(selected, principal, target, level, "CLASSIFY", previous_level)
        identity_deadline = _identity_callbacks(principal)
        assert_policy(selected)
        _identity_pins(principal)
        if locate(kind, identifier) != target or current(target).digest != result.digest:
            raise PrivacyDenied("privacy_classification_changed")
        if timezone.now() >= min(deadline, final_deadline, identity_deadline):
            raise PrivacyDenied("privacy_permission_expired")
        return {
            "id": str(result.pk),
            "target_kind": kind,
            "target_id": target.identifier,
            "source_digest": target.source_digest,
            "level": level,
            "revision": result.number,
            "digest": result.digest,
            "previous_digest": result.previous_digest,
            "created_at": result.created_at,
        }
