"""Authorized synthetic storage conversions; these never alter case facts or approval."""

from contextlib import ExitStack, contextmanager
from contextvars import ContextVar

from django.apps import apps
from django.conf import settings
from django.db import connection

from apps.casework import services as cases
from apps.casework.models import CaseMediaStorageTransition
from apps.private_media.storage import (
    InlineDatabaseStorage,
    PrivateStorage,
    StoredOriginal,
    configured_storage,
    read_original,
)
from apps.private_media.validation import MediaValidationError, ValidatedMedia

ACTIVE_BINDINGS = ContextVar("fatwa_private_storage_bindings", default=frozenset())

INLINE = "inline-database-v1"
FILESYSTEM = "private-filesystem-v1"
OWNERS = {
    "ATTACHMENT": ("case_attachments", "CaseAttachment"),
    "ANSWER_PART": ("answer_media", "AnswerPart"),
}


def reference(row):
    return StoredOriginal(
        row.storage_backend,
        row.storage_key or row.sha256,
        row.sha256,
        row.size,
        bytes(row.original) if row.original is not None else None,
    )


def raw_for_owner(row):
    try:
        return read_original(reference(row))
    except (MediaValidationError, OSError) as exc:
        raise cases.CaseConflict("private_original_integrity_failed") from exc


def pointer_fields(original):
    return {
        "original": original.inline,
        "storage_backend": original.backend,
        "storage_key": original.key,
    }


def copied_pointer(row):
    # Verify live immutable bytes, then preserve the external pointer without copying inline.
    raw_for_owner(row)
    return pointer_fields(reference(row))


@contextmanager
def binding_locks(storage, digests):
    """Hold external references through outer commit; only explicitly held locks nest.

    Source intake composes upload inside its guarded unit. It must acquire these
    locks before entering that unit; an arbitrary nested external write still fails.
    Inline bytes have no independent orphan collector and need no filesystem lock.
    """
    digests = sorted(set(digests))
    needed = frozenset((id(storage), digest) for digest in digests)
    if connection.in_atomic_block:
        if isinstance(storage, InlineDatabaseStorage) or needed <= ACTIVE_BINDINGS.get():
            yield
            return
        raise cases.CaseConflict("storage_lock_requires_outer_transaction_boundary")
    try:
        with ExitStack() as stack:
            for digest in digests:
                stack.enter_context(storage.binding_lock(digest))
            token = ACTIVE_BINDINGS.set(ACTIVE_BINDINGS.get() | needed)
            try:
                yield
            finally:
                ACTIVE_BINDINGS.reset(token)
    except (MediaValidationError, OSError) as exc:
        raise cases.CaseConflict("private_storage_unavailable") from exc


def stored_fields(storage, media):
    try:
        stored = storage.put(media)
        if (stored.sha256, stored.size) != (media.sha256, media.size):
            raise MediaValidationError("private_original_integrity_failed")
        # Use target adapter here: conversion may target inline while FS is configured.
        if storage.get(stored) != media.raw:
            raise MediaValidationError("private_original_integrity_failed")
        return pointer_fields(stored)
    except (MediaValidationError, OSError) as exc:
        raise cases.CaseConflict("private_storage_unavailable") from exc


def live_references(backend, key=None):
    """Fresh committed reference lookup for GC; no owner row locks or cached counts.

    Every durable owner must be registered before any lookup: another profile may
    omit an app while its committed rows still reference this same private store.
    Missing owner schemas and database failures propagate so GC preserves originals.
    """
    if isinstance(backend, StoredOriginal) and key is None:
        backend, key = backend.backend, backend.key
    if any(not apps.is_installed("apps." + label) for label, _ in OWNERS.values()):
        raise cases.CaseConflict("media_owner_schema_unavailable")
    try:
        models = [apps.get_model(label, name) for label, name in OWNERS.values()]
    except LookupError as exc:
        raise cases.CaseConflict("media_owner_schema_unavailable") from exc
    for model in models:
        if model.objects.filter(storage_backend=backend, storage_key=key).exists():
            return True
    return False


def migrate_original(
    *,
    owner_kind,
    owner_id,
    case_id,
    target_storage,
    subject_id,
    provider,
    confirmed=False,
    synthetic_fixtures_only=False,
    expected_sha256=None,
):
    """Explicit scoped MUFTI operation, not a requester upload or substantive revision.

    An interrupted target write can leave a grace-protected unreferenced blob. The
    old binding and audit both roll back; orphan collection is a separate operation.
    """
    if getattr(settings, "FATWA_MEDIA_STORAGE_MIGRATION_ENABLED", False) is not True:
        raise cases.CaseConflict("media_storage_migration_disabled")
    cases._guard(synthetic_fixtures_only)
    if confirmed is not True or not isinstance(target_storage, PrivateStorage):
        raise cases.CaseConflict("explicit_media_conversion_required")
    owner = OWNERS.get(owner_kind)
    if owner is None or not apps.is_installed("apps." + owner[0]):
        raise cases.CaseConflict("media_owner_unavailable")
    model = apps.get_model(*owner)
    candidate = model.objects.filter(pk=cases._uuid(owner_id)).first()
    if candidate is None or (owner_kind == "ANSWER_PART" and candidate.kind == "TEXT"):
        raise cases.CaseConflict("media_owner_unavailable")
    # Both source and target locks must precede the case lock. A source retained row
    # already protects its blob, but taking this lock also serializes conversion/GC.
    source_storage = (
        configured_storage() if candidate.storage_backend == FILESYSTEM else target_storage
    )
    with binding_locks(source_storage, [candidate.sha256]):
        with binding_locks(
            target_storage, [] if target_storage is source_storage else [candidate.sha256]
        ):
            with cases._staff_case(case_id, subject_id, provider, synthetic_fixtures_only) as (
                case,
                actor,
            ):
                row = model.objects.get(pk=candidate.pk)
                row_case_id = (
                    row.case_id if owner_kind == "ATTACHMENT" else row.manifest.answer.case_id
                )
                if row_case_id != case.pk or (
                    expected_sha256 is not None and row.sha256 != expected_sha256
                ):
                    raise cases.CaseConflict("media_owner_unavailable")
                provider_id = provider.provider_id
                raw = raw_for_owner(row)
                metadata = row.validation_metadata if owner_kind == "ATTACHMENT" else row.metadata
                kind = row.kind
                media = ValidatedMedia(
                    raw, row.filename, row.media_type, row.sha256, row.size, kind, metadata
                )
                fields = stored_fields(target_storage, media)
                if fields["storage_backend"] == row.storage_backend:
                    raise cases.CaseConflict("media_conversion_same_backend")
                current = cases._identity(provider, subject_id, case)
                if (current.subject_id, current.auth_epoch, provider.provider_id) != (
                    actor.subject_id,
                    actor.auth_epoch,
                    provider_id,
                ):
                    raise cases.CaseConflict("case_identity_changed")
                event = CaseMediaStorageTransition.objects.create(
                    case=case,
                    owner_kind=owner_kind,
                    owner_id=row.pk,
                    from_backend=row.storage_backend,
                    from_key=row.storage_key,
                    to_backend=fields["storage_backend"],
                    to_key=fields["storage_key"],
                    sha256=row.sha256,
                    size=row.size,
                    subject_id=actor.subject_id,
                    provider_id=provider_id,
                    auth_epoch=actor.auth_epoch,
                )
                model.objects.filter(pk=row.pk).update(**fields)
                row.refresh_from_db()
                # Verify the committed resolver can read this pointer under current config.
                # Inline is routed independently, so reverse works with FS still configured.
                if raw_for_owner(row) != raw:
                    raise cases.CaseConflict("private_original_integrity_failed")
                current = cases._identity(provider, subject_id, case)
                if (current.subject_id, current.auth_epoch, provider.provider_id) != (
                    actor.subject_id,
                    actor.auth_epoch,
                    provider_id,
                ):
                    raise cases.CaseConflict("case_identity_changed")
                return {
                    "transition_id": str(event.pk),
                    "owner_id": str(row.pk),
                    "sha256": row.sha256,
                    "size": row.size,
                    "storage_backend": row.storage_backend,
                }
