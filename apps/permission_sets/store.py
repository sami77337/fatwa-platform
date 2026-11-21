"""One resolver and a sealed audit chain for every template and individual change."""

import json
import os
import uuid
from datetime import datetime

from django.apps import apps
from django.conf import settings
from django.db import connection
from django.utils import timezone

from . import catalog
from .catalog import PermissionDenied

MAX_ROWS = 8192


def enabled():
    if (
        getattr(settings, "FATWA_PERMISSION_SETS_ENABLED", False) is not True
        or os.environ.get("FATWA_PRODUCTION") != "0"
        or not apps.is_installed("apps.permission_sets")
    ):
        raise PermissionDenied("permission_sets_disabled")


def model():
    enabled()
    return apps.get_model("permission_sets.PermissionRevision")


def lock():
    with connection.cursor() as cursor:
        cursor.execute("SELECT pg_advisory_xact_lock(401404,1)")


def body(row):
    result = {}
    for field in row._meta.concrete_fields:
        if field.name in {"canonical_payload", "digest", "created_at"}:
            continue
        value = getattr(row, field.attname)
        if isinstance(value, uuid.UUID):
            value = str(value)
        elif isinstance(value, datetime):
            value = value.isoformat(timespec="microseconds")
        result[field.attname] = value
    return result


def seal(row):
    value = body(row)
    row.canonical_payload = catalog.canonical(value)
    row.digest = catalog.digest(value)
    return row


def verify(row):
    try:
        valid = (
            json.loads(row.canonical_payload) == body(row)
            and catalog.digest(body(row)) == row.digest
            and catalog.definition(row.kind, row.definition) == row.definition
            and row.kind in {"SET", "USER"}
            and row.state in {"ACTIVE", "DISABLED"}
            and row.actor_role in {"MUFTI", "ORGANIZER_ADMIN"}
            and row.actor_provider_id == row.provider_id
            and row.change in {"CREATE", "REPLACE", "DISABLE", "REVERT"}
        )
        if row.kind == "SET":
            catalog.uuid_text(row.scope_key)
            valid = valid and not any(
                (row.target_role, row.target_auth_epoch, row.target_scope_digest)
            )
        else:
            catalog.identifier(row.scope_key)
            valid = (
                valid
                and row.target_role in {"MUFTI", "ORGANIZER_ADMIN", "ORGANIZER"}
                and row.actor_subject_id != row.scope_key
            )
        if not valid:
            raise ValueError
    except (TypeError, ValueError, KeyError) as exc:
        raise PermissionDenied("permission_ledger_changed") from exc


def rows():
    result = list(
        model().objects.order_by("kind", "provider_id", "scope_key", "number")[: MAX_ROWS + 1]
    )
    if len(result) > MAX_ROWS:
        raise PermissionDenied("permission_ledger_bound")
    latest = {}
    for row in result:
        verify(row)
        key = (row.kind, row.provider_id, row.scope_key)
        previous = latest.get(key)
        if row.number != (previous.number + 1 if previous else 1) or row.previous_digest != (
            previous.digest if previous else catalog.ZERO
        ):
            raise PermissionDenied("permission_ledger_changed")
        latest[key] = row
    return result


def fingerprint(values=None):
    return tuple((str(row.pk), row.digest) for row in (rows() if values is None else values))


def latest(values=None):
    return {
        (row.kind, row.provider_id, row.scope_key): row
        for row in (rows() if values is None else values)
    }


def history(kind, provider_id, scope_key, *, values=None):
    return [
        row
        for row in (rows() if values is None else values)
        if (row.kind, row.provider_id, row.scope_key) == (kind, provider_id, scope_key)
    ]


def scope_digest(actor):
    return catalog.digest(sorted(actor.case_keys))


def resolved(user, heads):
    """A stale selected template invalidates its profile, including overrides."""
    if (
        user is None
        or user.state != "ACTIVE"
        or user.valid_until is None
        or user.valid_until <= timezone.now()
    ):
        return [], None
    result, deadline = list(user.definition["overrides"]), user.valid_until
    for identifier in user.definition["sets"]:
        selected = heads.get(("SET", user.provider_id, identifier))
        if (
            selected is None
            or selected.state != "ACTIVE"
            or selected.valid_until is None
            or selected.valid_until <= timezone.now()
        ):
            return [], None
        deadline = min(deadline, selected.valid_until)
        result.extend(selected.definition["rules"])
    return result, deadline


def effects(rules):
    result = {}
    for rule in rules:
        key = catalog.digest(rule["scope"])
        if key not in result or rule["effect"] == "DENY":
            result[key] = rule
    return result


def grant(actor, provider_id, value):
    value = catalog.scope(value)
    heads = latest()
    user = heads.get(("USER", provider_id, actor.subject_id))
    if user is None or (user.target_role, user.target_auth_epoch, user.target_scope_digest) != (
        actor.role,
        actor.auth_epoch,
        scope_digest(actor),
    ):
        return None
    rules, deadline = resolved(user, heads)
    selected = effects(rules).get(catalog.digest(value))
    if selected is None or selected["effect"] != "ALLOW" or deadline is None:
        return None
    if not catalog.verify_scope(value) <= actor.case_keys:
        return None
    return min(deadline, actor.valid_until)
