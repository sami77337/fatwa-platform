"""Externally keyed HMAC checkpoints for the PostgreSQL delivery audit head."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from hashlib import sha256
import hmac
import json
import re

from django.utils import timezone

from .services import QueueConflict, verify_audit_chain

_SCHEMA = "fatwa.postgres-delivery.audit-checkpoint.v1"
_KEY_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
_HEX = re.compile(r"^[a-f0-9]{64}$")


@dataclass(frozen=True, slots=True)
class PostgresAuditAttestation:
    schema: str
    key_id: str
    sequence: int
    head_digest: str
    created_at: str
    signature_hmac_sha256: str


def _payload(schema, key_id, sequence, digest, created_at):
    return json.dumps({
        "schema": schema, "key_id": key_id, "sequence": sequence,
        "head_digest": digest, "created_at": created_at,
    }, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def create_postgres_audit_attestation(*, key_id: str, signing_key: bytes, created_at=None):
    """Create a checkpoint; caller must persist it outside PostgreSQL."""
    if not _KEY_ID.fullmatch(key_id) or type(signing_key) is not bytes or len(signing_key) < 32:
        raise QueueConflict("postgres_audit_key_invalid")
    sequence, digest = verify_audit_chain()
    stamp = created_at or timezone.now()
    if not timezone.is_aware(stamp) or stamp.utcoffset() != timedelta(0):
        raise QueueConflict("postgres_audit_clock_must_be_utc")
    stamp_text = stamp.isoformat(timespec="microseconds")
    signature = hmac.new(
        signing_key, _payload(_SCHEMA, key_id, sequence, digest, stamp_text), sha256
    ).hexdigest()
    return PostgresAuditAttestation(_SCHEMA, key_id, sequence, digest, stamp_text, signature)


def verify_postgres_audit_attestation(*, attestation: PostgresAuditAttestation, trusted_keys):
    """Verify HMAC and exact current PostgreSQL audit head."""
    if not isinstance(attestation, PostgresAuditAttestation):
        return False
    if not (
        attestation.schema == _SCHEMA
        and _KEY_ID.fullmatch(attestation.key_id) is not None
        and type(attestation.sequence) is int and attestation.sequence >= 0
        and type(attestation.head_digest) is str and _HEX.fullmatch(attestation.head_digest)
        and type(attestation.signature_hmac_sha256) is str
        and _HEX.fullmatch(attestation.signature_hmac_sha256)
        and type(attestation.created_at) is str
    ):
        return False
    try:
        stamp = datetime.fromisoformat(attestation.created_at)
    except ValueError:
        return False
    if stamp.tzinfo is None or stamp.utcoffset() != timedelta(0):
        return False
    key = trusted_keys.get(attestation.key_id)
    if type(key) is not bytes or len(key) < 32:
        return False
    expected = hmac.new(key, _payload(
        attestation.schema, attestation.key_id, attestation.sequence,
        attestation.head_digest, attestation.created_at,
    ), sha256).hexdigest()
    if not hmac.compare_digest(expected, attestation.signature_hmac_sha256):
        return False
    try:
        sequence, digest = verify_audit_chain()
    except QueueConflict:
        return False
    return sequence == attestation.sequence and hmac.compare_digest(digest, attestation.head_digest)
