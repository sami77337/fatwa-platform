"""Exact synthetic stored identity, not a draft-revision or permission join.

Wave7's reader must run outside transactions. Two bounded observations detect
changes but do not claim a transactional snapshot or immutable historical proof.
"""

import re
from dataclasses import dataclass, replace
from datetime import timezone
from hashlib import sha256
from typing import Literal
from uuid import UUID

from django.conf import settings
from django.db import connections

from apps.editorial_demo.workflow_audit import serialize_audit_json
from apps.editorial_demo.workflow_audit_provenance import AuditProvenance, build_audit_provenance
from apps.intake_workflow import contracts as c
from apps.intake_workflow import guards, review


@dataclass(frozen=True, slots=True)
class StoredIdentity:
    database_name: str
    database_oid: int
    batch_id: UUID
    row_id: UUID
    row_ordinal: int
    payload_sha256: str
    row_sha256: str
    latest_event_id: UUID
    latest_operation_id: UUID
    audit_sha256: str


@dataclass(frozen=True, slots=True)
class AuditRead:
    status: Literal["CONNECTED", "NOT_CONNECTED", "NOT_RUN"]
    reason: str
    provenance: AuditProvenance | None = None
    audit_sha256: str | None = None
    revision_connection: Literal["NOT_CONNECTED"] = "NOT_CONNECTED"
    permission_connection: Literal["NOT_CONNECTED"] = "NOT_CONNECTED"
    owner_acceptance: Literal["NOT_RUN"] = "NOT_RUN"


class BoundaryDenied(ValueError):
    """Internal fixed reason only; external exceptions are always redacted."""


def _require(condition: bool, code: str) -> None:
    if not condition:
        raise BoundaryDenied(code)


def _validate(identity: StoredIdentity) -> None:
    _require(type(identity) is StoredIdentity, "INVALID_IDENTITY")
    _require(
        type(identity.database_name) is str
        and re.fullmatch(r"test_wave7_synthetic_[a-z0-9_]{1,40}", identity.database_name)
        is not None
        and type(identity.database_oid) is int
        and 0 < identity.database_oid <= 4294967295,
        "INVALID_DATABASE_IDENTITY",
    )
    _require(
        all(
            type(value) is UUID
            for value in (
                identity.batch_id,
                identity.row_id,
                identity.latest_event_id,
                identity.latest_operation_id,
            )
        )
        and type(identity.row_ordinal) is int
        and 1 <= identity.row_ordinal <= c.MAX_ITEMS,
        "INVALID_ROW_OR_REVIEW_IDENTITY",
    )
    _require(
        all(
            type(value) is str and re.fullmatch(r"[0-9a-f]{64}", value)
            for value in (identity.payload_sha256, identity.row_sha256, identity.audit_sha256)
        ),
        "INVALID_SHA256",
    )


def _require_database(identity: StoredIdentity) -> None:
    # Configuration is checked before opening any connection, including the base
    # DB used by the trusted runner. This adapter accepts only its disposable DB.
    target = guards.validate_write_configuration(synthetic_fixtures_only=True)
    _require(
        target.database_name == target.test_name == identity.database_name
        and settings.WAVE7_TEST_DATABASE_NAME == identity.database_name,
        "DATABASE_IDENTITY_MISMATCH",
    )
    connection = connections["default"]
    _require(not connection.in_atomic_block and connection.get_autocommit(), "AUTOCOMMIT_REQUIRED")
    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT current_database(), current_user, "
            "(SELECT oid FROM pg_database WHERE datname=current_database()), "
            "current_setting('transaction_read_only')"
        )
        actual = cursor.fetchone()
    _require(
        actual == (identity.database_name, c.DATABASE_ROLE, identity.database_oid, "on"),
        "DATABASE_IDENTITY_OR_READ_ONLY_MISMATCH",
    )
    # Includes actual role/version/OID, ownership marker and existing schema checks.
    from apps.reference import services

    services._require_workflow_read(synthetic_fixtures_only=True)


def _source_sha(identity: StoredIdentity) -> str:
    from apps.intake_workflow.models import IntakeBatch

    value = (
        IntakeBatch.objects.using("default")
        .filter(
            pk=identity.batch_id,
            scope=c.SYNTHETIC_SCOPE,
            source_config_id=c.SOURCE_CONFIG_ID,
            contract_version=c.CONTRACT_VERSION,
        )
        .values_list("payload_sha256", flat=True)
        .first()
    )
    _require(value is not None, "STORED_STATE_MISSING")
    return value


def selected_window(stored: review.ReviewWorklist) -> review.ReviewWorklist:
    """Discard unrelated worklist rows; preserve the selected objects verbatim."""
    build_audit_provenance(stored, synthetic_fixtures_only=True)
    _require(stored.row is not None, "STORED_STATE_MISSING")
    return replace(
        stored,
        batches=tuple(b for b in stored.batches if b.id == stored.batch_id),
        rows=(stored.row,),
        total_count=1,
        matched_count=1,
        page=1,
        page_count=1,
        page_size=1,
        q="",
        mode="normalized",
        intake_status="",
        review_status="",
    )


def window_sha256(stored: review.ReviewWorklist) -> str:
    """Fingerprint a previously supplied DTO; this does NOT prove persistence.

    The exact export includes timestamps, byte spans, original strings, event and
    operation IDs, statuses, references and the truncation flag. No normalization.
    It is a technical audit window pin, never a draft revision number/link.
    """
    return sha256(serialize_audit_json(selected_window(stored))).hexdigest()


def _observe(identity: StoredIdentity) -> tuple[review.ReviewWorklist, str]:
    _require(_source_sha(identity) == identity.payload_sha256, "SOURCE_IDENTITY_MISMATCH")
    stored = review.load_review_worklist(
        batch_id=identity.batch_id,
        row_id=identity.row_id,
        page=1,
        page_size=1,
        synthetic_fixtures_only=True,
    )
    window = selected_window(stored)
    row = window.row
    _require(
        window.batch_id == row.batch_id == identity.batch_id
        and row.id == identity.row_id
        and row.row_ordinal == identity.row_ordinal,
        "ROW_IDENTITY_MISMATCH",
    )
    raw = row.original_row.encode("utf-8", errors="strict")
    _require(
        sha256(raw).hexdigest() == identity.row_sha256
        and 0 <= row.source_byte_start < row.source_byte_end <= c.MAX_INPUT_BYTES
        and row.source_byte_end - row.source_byte_start == len(raw),
        "ROW_SOURCE_MISMATCH",
    )
    _require(bool(row.events), "STORED_REVIEW_MISSING")
    # The real reader orders descending by (created_at, id), not tuple position
    # supplied by an external case label or a duplicated external_id.
    latest = max(
        row.events, key=lambda event: (event.created_at.astimezone(timezone.utc), event.id)
    )
    _require(
        (latest.id, latest.operation_id)
        == (identity.latest_event_id, identity.latest_operation_id),
        "STALE_REVIEW_IDENTITY",
    )
    _require(latest.to_status == row.review_status, "STALE_REVIEW_STATUS")
    digest = window_sha256(window)
    _require(digest == identity.audit_sha256, "STALE_AUDIT_WINDOW")
    return window, digest


def read_stored_audit(
    identity: StoredIdentity | None = None,
    *,
    synthetic_fixtures_only: bool = False,
    draft_revision: int | None = None,
) -> AuditRead:
    """No writes, seeding, identity discovery, revision inference or HTTP route.

    A caller requesting a draft revision must supply an authoritative stored
    join, which Wave7 does not have. Such requests fail closed before DB access.
    """
    if synthetic_fixtures_only is not True:
        return AuditRead("NOT_RUN", "SYNTHETIC_ACK_REQUIRED")
    if identity is None:
        return AuditRead("NOT_CONNECTED", "STORED_IDENTITY_REQUIRED")
    if draft_revision is not None:
        return AuditRead("NOT_CONNECTED", "EXACT_REVISION_LINK_UNAVAILABLE")
    try:
        _validate(identity)
        from apps.reference import services

        if not services._workflow_reads_enabled():
            return AuditRead("NOT_CONNECTED", "READ_GATE_DISABLED")
        _require_database(identity)
        first, digest = _observe(identity)
        second, second_digest = _observe(identity)
        _require(first == second and digest == second_digest, "AUDIT_CHANGED_DURING_READ")
        _require_database(identity)
        return AuditRead(
            "CONNECTED",
            "BOUNDED_SYNTHETIC_READ",
            build_audit_provenance(second, synthetic_fixtures_only=True),
            digest,
        )
    except BoundaryDenied as error:
        return AuditRead("NOT_CONNECTED", str(error))
    except review.ReviewNotFound:
        return AuditRead("NOT_CONNECTED", "STORED_STATE_MISSING")
    except Exception:
        # DB/driver/parser exceptions can include payloads, SQL, paths or secrets.
        # Failures remain NOT_RUN; neither an empty fabricated history nor PASS.
        return AuditRead("NOT_RUN", "READ_UNAVAILABLE")
