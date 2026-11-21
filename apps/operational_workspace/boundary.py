"""Read admission, exact policy snapshots and unchanged sources through final rendering."""

import json
import os
from contextlib import contextmanager
from hashlib import sha256

from django.conf import settings
from django.db import connection
from django.utils import timezone

from apps.answer_media.models import AnswerManifest, AnswerPart
from apps.case_organization.models import OrganizationRevision
from apps.casework import services as cases
from apps.casework.models import (
    AnswerRevision,
    Case,
    CaseDecision,
    CaseDelivery,
    CaseEvent,
    CaseEvidence,
    CaseSource,
)
from apps.composite_delivery import services as composite
from apps.composite_delivery.models import CompositeDelivery, CompositeRetry
from apps.delivery_queue.models import (
    ApprovalClaim,
    DeliveryAttempt,
    DeliveryAuditEvent,
    DeliveryAuditHead,
    DeliveryIntent,
    ProviderReceipt,
    ProviderSignatureEvidence,
    RequesterTrackingCase,
    RequesterTrackingEvent,
    RequesterTrackingToken,
    SignedDeliveryContext,
)
from apps.delivery_queue.services import synthetic_queue_atomic
from apps.development_taxonomy.models import CaseClassification, HumanReview, TreeVersion
from apps.experimental_publication.models import PublicationAction, PublicationEdition
from apps.platform_recovery.integration import mutation_context
from apps.public_answer_media.models import RecordingTranscript, TranscriptAction
from apps.source_case_intake.models import EvidenceBinding, SourceReceipt

from . import identity, retry_projection
from .authority import OperationalAuthority

MAX_ROWS = 8192
ACTIONS = frozenset(
    {
        "READ_QUEUE",
        "READ_CASE",
        "READ_METADATA",
        "READ_DELIVERY",
        "READ_PUBLICATION",
        "READ_TRANSCRIPT",
        "READ_CAPABILITY",
    }
)
NOTE_ACTIONS = frozenset({"READ_INTERNAL_NOTES", "ADD_INTERNAL_NOTE"})


def note_feature_enabled():
    return (
        getattr(settings, "FATWA_OPERATIONAL_INTERNAL_NOTES_ENABLED", False) is True
        and getattr(settings, "FATWA_CASE_ORGANIZATION_ENABLED", False) is True
    )


def digest(value):
    def default(item):
        if isinstance(item, (bytes, bytearray, memoryview)):
            return {"sha256": sha256(bytes(item)).hexdigest(), "size": len(item)}
        return str(item)

    return sha256(
        json.dumps(value, sort_keys=True, ensure_ascii=False, default=default).encode()
    ).hexdigest()


def rows(query):
    values = list(query.order_by("pk").values()[: MAX_ROWS + 1])
    if len(values) > MAX_ROWS:
        raise cases.CaseConflict("operational_history_bound")
    return values


def source_rows(case_ids):
    scoped = Case.objects.filter(pk__in=case_ids)
    refs = scoped.values_list("public_ref", flat=True)
    tracking = scoped.values_list("tracking_id", flat=True)
    bindings = CaseClassification.objects.filter(case_id__in=case_ids)
    versions = TreeVersion.objects.filter(pk__in=bindings.values_list("version_id", flat=True))
    receipts = SourceReceipt.objects.filter(evidencebinding__case_id__in=case_ids)
    queries = (
        scoped,
        CaseSource.objects.filter(case_id__in=case_ids),
        CaseEvidence.objects.filter(case_id__in=case_ids),
        CaseEvent.objects.filter(case_id__in=case_ids),
        AnswerRevision.objects.filter(case_id__in=case_ids),
        CaseDecision.objects.filter(case_id__in=case_ids),
        CaseDelivery.objects.filter(decision__case_id__in=case_ids),
        RequesterTrackingCase.objects.filter(pk__in=tracking),
        RequesterTrackingEvent.objects.filter(case_id__in=tracking),
        RequesterTrackingToken.objects.filter(case_id__in=tracking),
        AnswerManifest.objects.filter(answer__case_id__in=case_ids),
        AnswerPart.objects.filter(manifest__answer__case_id__in=case_ids),
        OrganizationRevision.objects.filter(case_id__in=case_ids),
        bindings,
        versions,
        HumanReview.objects.filter(version__in=versions),
        CompositeDelivery.objects.filter(decision__case_id__in=case_ids),
        CompositeRetry.objects.filter(delivery__decision__case_id__in=case_ids),
        ApprovalClaim.objects.filter(case_key__in=refs),
        SignedDeliveryContext.objects.filter(approval__case_key__in=refs),
        DeliveryIntent.objects.filter(case_key__in=refs),
        DeliveryAttempt.objects.filter(intent__case_key__in=refs),
        DeliveryAuditEvent.objects.filter(intent__case_key__in=refs),
        ProviderReceipt.objects.filter(intent__case_key__in=refs),
        ProviderSignatureEvidence.objects.filter(receipt__intent__case_key__in=refs),
        PublicationEdition.objects.filter(case_id__in=case_ids),
        PublicationAction.objects.filter(edition__case_id__in=case_ids),
        RecordingTranscript.objects.filter(case_id__in=case_ids),
        TranscriptAction.objects.filter(transcript__case_id__in=case_ids),
        EvidenceBinding.objects.filter(case_id__in=case_ids),
        receipts,
    )
    return {query.model._meta.db_table: rows(query) for query in queries}


def policy():
    if (
        os.environ.get("FATWA_PRODUCTION") != "0"
        or getattr(settings, "FATWA_OPERATIONAL_WORKSPACE_ENABLED", False) is not True
    ):
        raise cases.CaseConflict("operational_workspace_disabled")
    authority = getattr(settings, "FATWA_OPERATIONAL_WORKSPACE_AUTHORITY", None)
    if not isinstance(authority, OperationalAuthority):
        raise cases.CaseConflict("operational_authority_required")
    return authority, epoch(authority)


def epoch(value):
    try:
        result = value.projection_epoch()
    except Exception as exc:
        raise cases.CaseConflict("operational_policy_snapshot_required") from exc
    if type(result) is not str or not 1 <= len(result) <= 131072:
        raise cases.CaseConflict("operational_policy_snapshot_required")
    return result


def capability_epoch(reader):
    if not callable(reader) or not callable(getattr(reader, "projection_epoch", None)):
        return None
    try:
        return epoch(reader)
    except cases.CaseConflict:
        return None


class Guard:
    def __init__(
        self,
        provider,
        actor,
        locked,
        authority,
        policy_epoch,
        directory,
        directory_epoch,
        request_epoch,
        deadline,
    ):
        self.provider, self.actor, self.locked = provider, actor, locked
        self.authority, self.policy_epoch = authority, policy_epoch
        self.directory, self.directory_epoch = directory, directory_epoch
        self.request_epoch = request_epoch
        self.provider_id = directory.provider_id
        self.note_feature = note_feature_enabled()
        self.deadline = min(actor.valid_until, deadline) if deadline else actor.valid_until
        self.permissions, self.profiles, self.derived_reads = [], {}, []
        self.retry_configuration = retry_projection.configuration()
        self.storage = getattr(settings, "FATWA_PRIVATE_MEDIA_STORAGE", None)
        self.audit_head = digest(rows(DeliveryAuditHead.objects.all()))
        self.capabilities = getattr(settings, "FATWA_COMPOSITE_DELIVERY_CAPABILITIES", None)
        self.capability_epoch = capability_epoch(self.capabilities)
        self.sources = source_rows(locked)
        self.watermark = digest(self.sources)
        self.scope = tuple(sorted((str(row.pk), row.public_ref) for row in locked.values()))

    def permit(self, case, action, section, *, required=False):
        if action not in ACTIONS | NOTE_ACTIONS or case.pk not in self.locked:
            raise cases.CaseConflict("operational_action_unavailable")
        if action in NOTE_ACTIONS and not self.note_feature:
            raise cases.CaseConflict("operational_notes_unavailable")
        values = dict(
            provider_id=self.provider_id,
            subject_id=self.actor.subject_id,
            role=self.actor.role,
            auth_epoch=self.actor.auth_epoch,
            case_ref=case.public_ref,
            action=action,
            resource={
                "kind": "CASE_OPERATIONAL_SECTION",
                "case_id": str(case.pk),
                "section": section,
            },
        )
        allowed = self.call(values)
        self.permissions.append((values, allowed))
        if required and not allowed:
            raise cases.CaseConflict("operational_read_denied")
        return allowed

    def call(self, values):
        try:
            allowed = (
                self.authority.permits(**{**values, "resource": dict(values["resource"])}) is True
            )
            if allowed:
                until = self.authority.grant_deadline(
                    **{**values, "resource": dict(values["resource"])}
                )
                if not identity.valid_deadline(until):
                    raise ValueError
                self.deadline = min(self.deadline, until)
            return allowed
        except Exception as exc:
            raise cases.CaseConflict("operational_policy_unavailable") from exc

    def profile(self, channel):
        if self.capability_epoch is None:
            return None
        try:
            value = composite._profile(channel)
        except cases.CaseConflict:
            value = None
        fingerprint = composite._profile_hash(value) if value is not None else None
        self.profiles[channel] = fingerprint
        return value

    def observe(self, reader):
        result = reader()
        self.derived_reads.append((reader, digest(result)))
        return result

    def account_for_note_append(self, row):
        """Advance the exact expected fingerprint by one authorized immutable note row.

        Never adopt a fresh whole-database snapshot after a write: that would
        conceal an unrelated append performed by a callback during admission.
        """
        table = OrganizationRevision._meta.db_table
        created = rows(OrganizationRevision.objects.filter(pk=row.pk))
        if (
            row.case_id not in self.locked
            or row.subject_id != self.actor.subject_id
            or row.provider_id != self.provider_id
            or row.auth_epoch != self.actor.auth_epoch
            or not row.note
            or len(created) != 1
            or any(value["id"] == row.pk for value in self.sources[table])
        ):
            raise cases.CaseConflict("operational_note_append_invalid")
        self.sources = {
            **self.sources,
            table: sorted([*self.sources[table], created[0]], key=lambda value: str(value["id"])),
        }
        self.watermark = digest(self.sources)
        if digest(source_rows(self.locked)) != self.watermark:
            raise cases.CaseConflict("operational_note_source_changed")

    def callbacks(self):
        for values, before in self.permissions:
            if self.call(values) != before:
                raise cases.CaseConflict("operational_grant_changed")
        for channel, before in self.profiles.items():
            try:
                current = composite._profile_hash(composite._profile(channel))
            except cases.CaseConflict:
                current = None
            if current != before:
                raise cases.CaseConflict("operational_capability_changed")
        fresh = identity.resolve(self.provider, self.actor.subject_id)
        if identity.pin(fresh) != identity.pin(self.actor):
            raise cases.CaseConflict("operational_identity_changed")
        self.deadline = min(self.deadline, fresh.valid_until)
        for reader, before in self.derived_reads:
            if digest(reader()) != before:
                raise cases.CaseConflict("operational_derived_source_changed")

    def finish(self):
        self.callbacks()
        current = policy()
        if (
            current[0] is not self.authority
            or current[1] != self.policy_epoch
            or note_feature_enabled() != self.note_feature
            or getattr(settings, "FATWA_CASEWORK_IDENTITY_PROVIDER", None) is not self.directory
            or getattr(settings, "FATWA_COMPOSITE_DELIVERY_CAPABILITIES", None)
            is not self.capabilities
            or self.provider.provider_id != self.provider_id
            or self.directory.provider_id != self.provider_id
            or identity.epoch(self.directory) != self.directory_epoch
            or identity.epoch(self.provider) != self.request_epoch
            or capability_epoch(self.capabilities) != self.capability_epoch
            or retry_projection.configuration() != self.retry_configuration
            or getattr(settings, "FATWA_PRIVATE_MEDIA_STORAGE", None) is not self.storage
            or digest(rows(DeliveryAuditHead.objects.all())) != self.audit_head
            or digest(source_rows(self.locked)) != self.watermark
            or tuple(
                sorted(
                    (str(pk), ref)
                    for pk, ref in Case.objects.filter(
                        public_ref__in=self.actor.case_keys
                    ).values_list("pk", "public_ref")
                )
            )
            != self.scope
            or timezone.now() >= self.deadline
        ):
            raise cases.CaseConflict("operational_projection_changed")


@mutation_context
@contextmanager
def scope(*, subject_id, provider, synthetic_fixtures_only=False, session_deadline=None):
    cases._guard(synthetic_fixtures_only)
    authority, policy_epoch = policy()
    directory = identity.configured(provider)
    directory_epoch, request_epoch = identity.epoch(directory), identity.epoch(provider)
    actor = identity.resolve(provider, subject_id)
    if session_deadline is not None and not identity.valid_deadline(session_deadline):
        raise cases.CaseConflict("operational_session_expired")
    with synthetic_queue_atomic():
        with connection.cursor() as cursor:
            cursor.execute("SELECT pg_advisory_xact_lock(546131, 1)")
        locked = {
            row.pk: row
            for row in Case.objects.select_for_update()
            .filter(public_ref__in=actor.case_keys)
            .order_by("pk")
        }
        guard = Guard(
            provider,
            actor,
            locked,
            authority,
            policy_epoch,
            directory,
            directory_epoch,
            request_epoch,
            session_deadline,
        )
        yield guard
        guard.finish()
