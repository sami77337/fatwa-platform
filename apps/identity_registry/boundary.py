"""Graph-first locking and current, independently scoped identity authority."""

import json
import os
from contextlib import contextmanager
from hashlib import sha256

from django.conf import settings
from django.db import connection
from django.utils import timezone

from apps.casework import services as cases
from apps.casework.models import Case, CaseSource
from apps.casework_web.access import RequestDirectory
from apps.data_privacy import integration as privacy
from apps.data_privacy.services import PrivacyDenied
from apps.delivery_queue.services import synthetic_queue_atomic
from apps.mufti_review.identity import resolve_identity
from apps.platform_recovery.integration import mutation_context
from apps.research_library.services import _actor, identity_snapshot
from apps.source_case_intake.models import EvidenceBinding, SourceReceipt

from .authority import IdentityAuthority
from .models import (
    IdentityMembership,
    IdentityObservation,
    LinkProposal,
    Person,
    PlatformIdentity,
    RegistryOperation,
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
        raise cases.CaseConflict("identity_registry_integrity")


def text(value, maximum, *, optional=False):
    cases._text(value, optional=optional)
    if len(value) > maximum:
        raise cases.CaseConflict("identity_registry_text_bound")
    return value


def policy():
    if (
        os.environ.get("FATWA_PRODUCTION") != "0"
        or getattr(settings, "FATWA_IDENTITY_REGISTRY_ENABLED", False) is not True
    ):
        raise cases.CaseConflict("identity_registry_disabled")
    authority = getattr(settings, "FATWA_IDENTITY_REGISTRY_AUTHORITY", None)
    if not isinstance(authority, IdentityAuthority):
        raise cases.CaseConflict("identity_registry_authority_required")
    try:
        epoch = authority.projection_epoch()
    except Exception as exc:
        raise cases.CaseConflict("identity_registry_epoch_required") from exc
    if type(epoch) is not str or not 1 <= len(epoch) <= 131072:
        raise cases.CaseConflict("identity_registry_epoch_required")
    return authority, epoch


def origin(case):
    """Exact existing origin only. WEBSITE_SESSION explicitly is not a login identity."""
    pin = cases._delivery_origin_for_locked_case(case)
    source = case.source
    if source.source_event_id.startswith("source:"):
        binding = (
            EvidenceBinding.objects.select_related("receipt")
            .filter(case=case, action="CREATED", evidence__version=1)
            .first()
        )
        if binding is None or not binding.receipt.sender:
            raise cases.CaseConflict("identity_registry_origin_unavailable")
        receipt = binding.receipt
        values = dict(
            source=receipt.source,
            account=receipt.account,
            source_subject=receipt.sender,
            display_name=receipt.display_name,
            receipt_id=receipt.pk,
        )
    else:
        values = dict(
            source="WEBSITE_SESSION",
            account="native-casework",
            source_subject=case.requester_id,
            display_name="",
            receipt_id=None,
        )
    if any(
        type(values[key]) is not str or not values[key] or len(values[key]) > 128
        for key in ("account", "source_subject")
    ):
        raise cases.CaseConflict("identity_registry_origin_unavailable")
    return {
        **values,
        "identity_key": digest([values[key] for key in ("source", "account", "source_subject")]),
        "origin_digest": pin["identity_sha256"],
    }


def _rows(query):
    result = list(query.order_by("pk").values()[: MAX_ROWS + 1])
    if len(result) > MAX_ROWS:
        raise cases.CaseConflict("identity_registry_history_bound")
    return result


def fingerprint(case_ids):
    observations = IdentityObservation.objects.filter(case_id__in=case_ids)
    ids = set(observations.values_list("identity_id", flat=True))
    members = IdentityMembership.objects.filter(identity_id__in=ids)
    proposals = LinkProposal.objects.filter(identity_id__in=ids)
    persons = set(Person.objects.filter(case_id__in=case_ids).values_list("pk", flat=True))
    persons |= set(members.exclude(person=None).values_list("person_id", flat=True))
    persons |= set(proposals.values_list("person_id", flat=True))
    operations = RegistryOperation.objects.filter(
        case_id__in=case_ids
    ) | RegistryOperation.objects.filter(id__in=members.values_list("operation_id", flat=True))
    receipts = SourceReceipt.objects.filter(evidencebinding__case_id__in=case_ids)
    # Exact immutable source rows and binary digests are retained in the private
    # watermark; no raw source payload enters registry rows or browser forms.
    raw_rows = []
    for row in receipts.order_by("pk").values():
        row["raw"] = sha256(bytes(row["raw"])).hexdigest()
        raw_rows.append(row)
    return digest(
        [
            _rows(Case.objects.filter(pk__in=case_ids)),
            _rows(CaseSource.objects.filter(case_id__in=case_ids)),
            _rows(EvidenceBinding.objects.filter(case_id__in=case_ids)),
            raw_rows,
            _rows(PlatformIdentity.objects.filter(pk__in=ids)),
            _rows(IdentityObservation.objects.filter(identity_id__in=ids)),
            _rows(Person.objects.filter(pk__in=persons)),
            _rows(proposals),
            _rows(members),
            _rows(operations.distinct()),
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
            raise cases.CaseConflict("identity_registry_unavailable")
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
            raise cases.CaseConflict("identity_registry_denied")
        if allowed:
            try:
                privacy.staff(
                    "CASE",
                    case.pk,
                    provider=self.provider,
                    actor=self.actor,
                    action="SEARCH" if action == "SEARCH" else "READ",
                )
                for receipt_id in EvidenceBinding.objects.filter(
                    case=case, evidence__version=1
                ).values_list("receipt_id", flat=True):
                    privacy.staff(
                        "SOURCE_RECEIPT",
                        receipt_id,
                        provider=self.provider,
                        actor=self.actor,
                        action="SEARCH" if action == "SEARCH" else "READ",
                    )
            except PrivacyDenied:
                if required:
                    raise
                return False
        return allowed

    def call(self, values):
        try:
            return (
                self.authority.permits(**{**values, "resource": dict(values["resource"])}) is True
            )
        except Exception as exc:
            raise cases.CaseConflict("identity_registry_policy_unavailable") from exc

    def callbacks(self):
        for values, allowed in self.permissions:
            if self.call(values) != allowed:
                raise cases.CaseConflict("identity_registry_permission_changed")
        fresh = resolve_identity(self.provider, self.actor.subject_id)
        if _actor(fresh) != _actor(self.actor):
            raise cases.CaseConflict("identity_registry_identity_changed")
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
            raise cases.CaseConflict("identity_registry_projection_changed")

    def before_write(self, expected, case_id, revision, evidence):
        if type(expected) is not str or expected != self.watermark:
            raise cases.CaseConflict("identity_registry_version_changed")
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
            raise cases.CaseConflict("identity_registry_unavailable")
        for identifier in sorted(ids):
            self.permit(identifier, action, resource)


@mutation_context
@privacy.contextual
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
            raise cases.CaseConflict("identity_registry_configured_directory_required")
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
            raise cases.CaseConflict("identity_registry_unavailable")
        guard = Guard(
            provider, actor, locked, authority, epoch, identity_state, directory, directory_state
        )
        guard.permit(current.pk, "READ")
        guard.final_pins()
        yield guard
        guard.callbacks()
        guard.final_pins()
