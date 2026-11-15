"""Externally keyed HMAC checkpoints for the synthetic Outbox audit head.

The key is supplied by the caller and is never stored in SQLite or returned.
This protects a saved audit checkpoint against local file edits by an actor
who cannot access the external checkpoint key. It is not a production KMS,
identity provider, or distributed ledger.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from hashlib import sha256
import hmac
import json
import re
import sqlite3
from typing import Mapping

from .outbox import APP_ID, FILE_NAME, OutboxConflict, _db, _valid_ref, _valid_utc_timestamp, _verified_db

_KEY_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
_HEX = re.compile(r"^[a-f0-9]{64}$")
_SCHEMA = "fatwa.outbox.audit-checkpoint.v1"


@dataclass(frozen=True, slots=True)
class AuditAttestation:
    schema: str
    application_id: int
    database_version: int
    key_id: str
    sequence: int
    head_digest: str
    created_at: str
    signature_hmac_sha256: str


def _payload(
    *, schema: str, application_id: int, database_version: int,
    key_id: str, sequence: int, head_digest: str, created_at: str,
) -> bytes:
    claims = {
        "application_id": application_id,
        "created_at": created_at,
        "database_version": database_version,
        "head_digest": head_digest,
        "key_id": key_id,
        "schema": schema,
        "sequence": sequence,
    }
    return json.dumps(
        claims, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")


def create_audit_attestation(
    directory, *, key_id: str, signing_key: bytes, created_at: datetime | None = None,
) -> AuditAttestation:
    """Create an external checkpoint; caller must store it outside the DB."""
    if not _KEY_ID.fullmatch(key_id) or type(signing_key) is not bytes or len(signing_key) < 32:
        raise OutboxConflict("audit_attestation_key_invalid")
    stamp = created_at or datetime.now(UTC)
    if stamp.tzinfo is None or stamp.utcoffset() != timedelta(0):
        raise OutboxConflict("audit_attestation_clock_must_be_utc")
    stamp_text = stamp.astimezone(UTC).isoformat(timespec="microseconds")
    try:
        with _db(directory, writable=False) as con:
            if con is None:
                raise OutboxConflict("outbox_missing")
            _, sequence, digest = _verified_db(con)
            version = con.execute("PRAGMA user_version").fetchone()[0]
            claims = _payload(
                schema=_SCHEMA, application_id=APP_ID, database_version=version,
                key_id=key_id, sequence=sequence, head_digest=digest,
                created_at=stamp_text,
            )
            signature = hmac.new(signing_key, claims, sha256).hexdigest()
            return AuditAttestation(
                _SCHEMA, APP_ID, version, key_id, sequence, digest,
                stamp_text, signature,
            )
    except sqlite3.Error as exc:
        raise OutboxConflict("audit_attestation_store_unavailable") from exc


def verify_audit_attestation(
    directory, *, attestation: AuditAttestation, trusted_keys: Mapping[str, bytes],
) -> bool:
    """Verify both HMAC authenticity and equality with the current DB audit head."""
    if not isinstance(attestation, AuditAttestation):
        return False
    if not (
        attestation.schema == _SCHEMA
        and attestation.application_id == APP_ID
        and attestation.database_version == 4
        and _KEY_ID.fullmatch(attestation.key_id) is not None
        and type(attestation.sequence) is int and attestation.sequence >= 0
        and type(attestation.head_digest) is str and _HEX.fullmatch(attestation.head_digest)
        and _valid_utc_timestamp(attestation.created_at)
        and type(attestation.signature_hmac_sha256) is str
        and _HEX.fullmatch(attestation.signature_hmac_sha256)
    ):
        return False
    key = trusted_keys.get(attestation.key_id)
    if type(key) is not bytes or len(key) < 32:
        return False
    expected = hmac.new(key, _payload(
        schema=attestation.schema,
        application_id=attestation.application_id,
        database_version=attestation.database_version,
        key_id=attestation.key_id,
        sequence=attestation.sequence,
        head_digest=attestation.head_digest,
        created_at=attestation.created_at,
    ), sha256).hexdigest()
    if not hmac.compare_digest(expected, attestation.signature_hmac_sha256):
        return False
    try:
        with _db(directory, writable=False) as con:
            if con is None:
                return False
            _, sequence, digest = _verified_db(con)
            version = con.execute("PRAGMA user_version").fetchone()[0]
    except (OutboxConflict, sqlite3.Error):
        return False
    return (
        version == attestation.database_version
        and sequence == attestation.sequence
        and hmac.compare_digest(digest, attestation.head_digest)
    )
