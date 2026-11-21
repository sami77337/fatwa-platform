"""Finite material targets and metadata-only journal records."""

import json
import re
import uuid
from datetime import datetime, timezone
from hashlib import sha256

from apps.data_privacy.catalog import TARGETS, locate
from apps.data_privacy.services import PrivacyDenied

ZERO = "0" * 64
LIMIT = 4096
STATES = {"ACTIVE", "SOFT_DELETED", "RESTORED"}
ROLES = {"MUFTI", "ORGANIZER_ADMIN"}
FIELDS = {
    "id",
    "ledger_id",
    "sequence",
    "previous_digest",
    "target_kind",
    "target_id",
    "source_digest",
    "case_id",
    "version",
    "previous_state",
    "state",
    "action",
    "provider_id",
    "subject_id",
    "role",
    "auth_epoch",
    "reason_sha256",
    "occurred_at",
}


class SuppressionDenied(PrivacyDenied):
    pass


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def digest(value):
    return sha256(canonical(value).encode()).hexdigest()


def text_hash(value):
    return sha256(value.encode()).hexdigest()


def uuid_text(value):
    try:
        if type(value) is not str or str(uuid.UUID(value)) != value:
            raise ValueError
    except (TypeError, ValueError, AttributeError) as exc:
        raise SuppressionDenied("suppression_identifier_invalid") from exc
    return value


def sha(value):
    if type(value) is not str or re.fullmatch("[a-f0-9]{64}", value) is None:
        raise SuppressionDenied("suppression_digest_invalid")
    return value


def stamp(value):
    return value.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def parse_stamp(value):
    try:
        parsed = datetime.strptime(value, "%Y-%m-%dT%H:%M:%S.%fZ").replace(tzinfo=timezone.utc)
        if stamp(parsed) != value:
            raise ValueError
        return parsed
    except (ValueError, TypeError) as exc:
        raise SuppressionDenied("suppression_timestamp_invalid") from exc


def body(value):
    if type(value) is not dict or set(value) != FIELDS:
        raise SuppressionDenied("suppression_record_shape_invalid")
    for field in ("id", "ledger_id", "target_id"):
        uuid_text(value[field])
    if value["case_id"] is not None:
        uuid_text(value["case_id"])
    for field in ("source_digest", "previous_digest", "reason_sha256"):
        sha(value[field])
    if type(value["target_kind"]) is not str or value["target_kind"] not in TARGETS:
        raise SuppressionDenied("suppression_kind_invalid")
    if any(
        type(value[k]) is not int or not 1 <= value[k] <= LIMIT for k in ("sequence", "version")
    ):
        raise SuppressionDenied("suppression_sequence_invalid")
    for name in ("provider_id", "subject_id", "auth_epoch"):
        if (
            type(value[name]) is not str
            or not 1 <= len(value[name]) <= 128
            or not value[name].strip()
        ):
            raise SuppressionDenied("suppression_identity_invalid")
    if type(value["role"]) is not str or value["role"] not in ROLES:
        raise SuppressionDenied("suppression_role_invalid")
    before, after, action = value["previous_state"], value["state"], value["action"]
    if any(type(part) is not str for part in (before, after, action)):
        raise SuppressionDenied("suppression_transition_invalid")
    if not (
        before in {"ACTIVE", "RESTORED"}
        and after == "SOFT_DELETED"
        and action == "SOFT_DELETE"
        or before == "SOFT_DELETED"
        and after == "RESTORED"
        and action == "RESTORE"
    ):
        raise SuppressionDenied("suppression_transition_invalid")
    parse_stamp(value["occurred_at"])
    return value


def events(values, ledger_id):
    if type(values) is not list or len(values) > LIMIT:
        raise SuppressionDenied("suppression_journal_bound")
    heads, previous, ids = {}, ZERO, set()
    for index, item in enumerate(values, 1):
        body(item)
        key = (item["target_kind"], item["target_id"])
        old = heads.get(key)
        if (
            item["ledger_id"] != ledger_id
            or item["sequence"] != index
            or item["previous_digest"] != previous
            or item["id"] in ids
            or item["version"] != (old["version"] + 1 if old else 1)
            or item["previous_state"] != (old["state"] if old else "ACTIVE")
            or old
            and (item["source_digest"], item["case_id"]) != (old["source_digest"], old["case_id"])
        ):
            raise SuppressionDenied("suppression_journal_chain_invalid")
        heads[key], previous = item, digest(item)
        ids.add(item["id"])
    return heads, previous


def target(kind, identifier):
    uuid_text(identifier)
    try:
        return locate(kind, identifier)
    except Exception as exc:
        raise SuppressionDenied("suppression_target_unavailable") from exc
