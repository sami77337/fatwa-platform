"""Canonical append-only records. Raw originals never enter this module."""

import json
from hashlib import sha256

from apps.casework import services as cases
from apps.delivery_queue.services import _canonical


def digest(value):
    return sha256(_canonical(value)).hexdigest()


def body(row):
    result = {}
    for field in row._meta.concrete_fields:
        if field.name not in {"canonical_payload", "digest", "created_at", "raw"}:
            value = getattr(row, field.attname)
            if hasattr(value, "isoformat"):
                value = value.isoformat(timespec="microseconds")
            elif value is not None and not isinstance(value, (str, int, bool, list, dict)):
                value = str(value)
            result[field.attname] = value
    return result


def seal(row):
    row.canonical_payload = _canonical(body(row)).decode()
    row.digest = sha256(row.canonical_payload.encode()).hexdigest()
    row.save(force_insert=True)
    return row


def verify(row):
    try:
        if (
            json.loads(row.canonical_payload) != body(row)
            or sha256(row.canonical_payload.encode()).hexdigest() != row.digest
        ):
            raise ValueError
    except (ValueError, TypeError, UnicodeError) as exc:
        raise cases.CaseConflict("derivative_history_invalid") from exc
