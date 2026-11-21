"""Current exact authority retained through the complete taxonomy projection."""

import json
import os
from contextlib import contextmanager
from hashlib import sha256

from django.conf import settings
from django.db import connection
from django.utils import timezone

from apps.casework import services as cases
from apps.casework.models import AnswerRevision, Case, CaseDecision
from apps.casework_web.access import RequestDirectory
from apps.delivery_queue.services import synthetic_queue_atomic
from apps.mufti_review.identity import resolve_identity
from apps.platform_recovery.integration import mutation_context
from apps.research_library.services import _actor, identity_snapshot

from .authority import TaxonomyAuthority
from .models import (
    CaseClassification,
    Concept,
    DevelopmentTree,
    HumanReview,
    MigrationExecution,
    MigrationPlan,
    TreeVersion,
)

ZERO = "0" * 64
MAX_ROWS = 4096


def digest(value):
    return sha256(
        json.dumps(
            value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str
        ).encode()
    ).hexdigest()


def body(row):
    values = {}
    for field in row._meta.fields:
        if field.name not in {"canonical_payload", "digest", "created_at"}:
            value = getattr(row, field.attname)
            if value is not None and not isinstance(value, (str, int, bool, list, dict)):
                value = str(value)
            values[field.attname] = value
    return values


def seal(row):
    row.canonical_payload = json.dumps(
        body(row), ensure_ascii=False, sort_keys=True, separators=(",", ":")
    )
    row.digest = sha256(row.canonical_payload.encode()).hexdigest()
    row.save(force_insert=True)
    return row


def verify(row):
    if (
        json.loads(row.canonical_payload) != body(row)
        or sha256(row.canonical_payload.encode()).hexdigest() != row.digest
    ):
        raise cases.CaseConflict("development_taxonomy_integrity")


def text(value, maximum, *, optional=False):
    cases._text(value, optional=optional)
    if len(value) > maximum:
        raise cases.CaseConflict("development_taxonomy_text_bound")
    return value


def policy():
    if (
        os.environ.get("FATWA_PRODUCTION") != "0"
        or getattr(settings, "FATWA_DEVELOPMENT_TAXONOMY_ENABLED", False) is not True
    ):
        raise cases.CaseConflict("development_taxonomy_disabled")
    authority = getattr(settings, "FATWA_DEVELOPMENT_TAXONOMY_AUTHORITY", None)
    if not isinstance(authority, TaxonomyAuthority):
        raise cases.CaseConflict("development_taxonomy_authority_required")
    try:
        epoch = authority.projection_epoch()
    except Exception as exc:
        raise cases.CaseConflict("development_taxonomy_epoch_required") from exc
    if type(epoch) is not str or not 1 <= len(epoch) <= 131072:
        raise cases.CaseConflict("development_taxonomy_epoch_required")
    return authority, epoch


def _rows(query):
    result = list(query.order_by("pk").values()[: MAX_ROWS + 1])
    if len(result) > MAX_ROWS:
        raise cases.CaseConflict("development_taxonomy_history_bound")
    return result


def fingerprint(case_ids):
    bindings = CaseClassification.objects.filter(case_id__in=case_ids)
    tree_ids = set(
        DevelopmentTree.objects.filter(case_id__in=case_ids).values_list("pk", flat=True)
    )
    tree_ids |= set(bindings.values_list("version__tree_id", flat=True))
    versions = TreeVersion.objects.filter(tree_id__in=tree_ids)
    plans = MigrationPlan.objects.filter(tree_id__in=tree_ids)
    return digest(
        [
            _rows(Case.objects.filter(pk__in=case_ids)),
            _rows(AnswerRevision.objects.filter(case_id__in=case_ids)),
            _rows(CaseDecision.objects.filter(case_id__in=case_ids)),
            _rows(DevelopmentTree.objects.filter(pk__in=tree_ids)),
            _rows(Concept.objects.filter(tree_id__in=tree_ids)),
            _rows(versions),
            _rows(plans),
            _rows(
                HumanReview.objects.filter(version__in=versions)
                | HumanReview.objects.filter(plan__in=plans)
            ),
            _rows(MigrationExecution.objects.filter(plan__in=plans)),
            _rows(bindings),
            _rows(CaseClassification.objects.filter(version__tree_id__in=tree_ids)),
        ]
    )


class Guard:
    def __init__(
        self, provider, actor, locked, authority, epoch, identity_state, directory, directory_state
    ):
        self.provider, self.actor, self.locked = provider, actor, locked
        self.authority, self.epoch = authority, epoch
        self.identity_state, self.directory, self.directory_state = (
            identity_state,
            directory,
            directory_state,
        )
        self.watermark = fingerprint(locked)
        self.permissions = []
        self.deadline = actor.valid_until

    def permit(self, case_id, action, resource=None, *, required=True):
        case = self.locked.get(cases._uuid(case_id))
        if case is None:
            raise cases.CaseConflict("development_taxonomy_unavailable")
        values = dict(
            provider_id=self.provider.provider_id,
            subject_id=self.actor.subject_id,
            auth_epoch=self.actor.auth_epoch,
            case_ref=case.public_ref,
            action=action,
            resource=resource or {"case_id": str(case.pk)},
        )
        allowed = self.call(values)
        self.permissions.append((values, allowed))
        if required and not allowed:
            raise cases.CaseConflict("development_taxonomy_denied")
        return allowed

    def call(self, values):
        try:
            return (
                self.authority.permits(**{**values, "resource": dict(values["resource"])}) is True
            )
        except Exception as exc:
            raise cases.CaseConflict("development_taxonomy_policy_unavailable") from exc

    def callbacks(self):
        for values, allowed in self.permissions:
            if self.call(values) != allowed:
                raise cases.CaseConflict("development_taxonomy_permission_changed")
        fresh = resolve_identity(self.provider, self.actor.subject_id)
        if _actor(fresh) != _actor(self.actor):
            raise cases.CaseConflict("development_taxonomy_identity_changed")
        self.deadline = min(self.deadline, fresh.valid_until)

    def final_pins(self):
        current = policy()
        if (
            current[0] is not self.authority
            or current[1] != self.epoch
            or getattr(settings, "FATWA_CASEWORK_IDENTITY_PROVIDER", None) is not self.directory
            or identity_snapshot(self.provider) != self.identity_state
            or identity_snapshot(self.directory) != self.directory_state
            or timezone.now() >= self.deadline
            or fingerprint(self.locked) != self.watermark
        ):
            raise cases.CaseConflict("development_taxonomy_projection_changed")

    def before_write(self, expected, case_id, revision, evidence):
        if type(expected) is not str or expected != self.watermark:
            raise cases.CaseConflict("development_taxonomy_version_changed")
        cases._versions(self.locked[cases._uuid(case_id)], revision, evidence)
        self.callbacks()
        self.final_pins()

    def written(self):
        self.watermark = fingerprint(self.locked)

    def actor_values(self):
        return dict(
            provider_id=self.provider.provider_id,
            subject_id=self.actor.subject_id,
            auth_epoch=self.actor.auth_epoch,
        )

    def use_cases(self, identifiers, action, resource):
        ids = {cases._uuid(value) for value in identifiers}
        if not ids <= self.locked.keys():
            raise cases.CaseConflict("development_taxonomy_unavailable")
        for identifier in sorted(ids):
            self.permit(identifier, action, resource)


@mutation_context
@contextmanager
def scope(*, case_id, subject_id, provider, synthetic_fixtures_only=False):
    with synthetic_queue_atomic():
        cases._guard(synthetic_fixtures_only)
        authority, epoch = policy()
        identity_state = identity_snapshot(provider)
        directory = getattr(settings, "FATWA_CASEWORK_IDENTITY_PROVIDER", None)
        if provider is not directory and not (
            type(provider) is RequestDirectory and provider._provider is directory
        ):
            raise cases.CaseConflict("development_taxonomy_configured_directory_required")
        directory_state = identity_snapshot(directory)
        actor = resolve_identity(provider, subject_id)
        with connection.cursor() as cursor:
            cursor.execute("SELECT pg_advisory_xact_lock(546131,1)")
        locked = {
            row.pk: row
            for row in Case.objects.filter(public_ref__in=actor.case_keys)
            .order_by("pk")
            .select_for_update()
        }
        current = locked.get(cases._uuid(case_id))
        if current is None:
            raise cases.CaseConflict("development_taxonomy_unavailable")
        guard = Guard(
            provider, actor, locked, authority, epoch, identity_state, directory, directory_state
        )
        guard.permit(current.pk, "READ")
        guard.final_pins()
        yield guard
        guard.callbacks()
        guard.final_pins()
