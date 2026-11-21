"""Review exact reversible suppression, then append a decision or replay a newer floor."""

import json
from contextlib import contextmanager

from django.utils import timezone

from . import boundary, catalog, store
from .catalog import SuppressionDenied

RECONCILE_BATCH = 128


def _row(guard, kind, identifier):
    target = guard.target(kind, identifier)
    resource = guard.resource(target)
    guard.require("READ_AUDIT", resource)
    rows = [
        row
        for row in guard.saved.saved
        if (row.target_kind, str(row.target_id)) == (kind, identifier)
    ]
    return {
        **resource,
        "history": [
            {
                "action": row.action,
                "state": row.state,
                "actor": row.subject_id,
                "role": row.role,
                "created_at": row.occurred_at,
                "reason": row.reason,
                "reason_sha256": row.reason_sha256,
                "recovered": row.recovered,
                "applied_by": row.applied_subject_id,
                "recovery_reason": row.recovery_reason,
                "digest": row.digest,
            }
            for row in reversed(rows)
        ],
    }


@contextmanager
def desk(**base):
    with boundary.scope(allow_pending=True, **base) as guard:
        rows = []
        for kind, identifier in sorted(guard.resources()):
            try:
                rows.append(_row(guard, kind, identifier))
            except SuppressionDenied:
                continue
        pending = guard.saved.events[len(guard.saved.saved) :]
        visible_pending = 0
        try:
            for decision in pending:
                target = guard.target(decision["target_kind"], decision["target_id"])
                resource = guard.resource(target)
                guard.require("READ_AUDIT", resource)
                guard.require(
                    "RECONCILE",
                    {
                        **resource,
                        "decision": catalog.digest(decision),
                        "sequence": decision["sequence"],
                    },
                )
            visible_pending = len(pending)
        except SuppressionDenied:
            pass
        yield {
            "rows": rows,
            "pending": visible_pending,
            "watermark": guard.saved.watermark,
        }


@contextmanager
def inspect(*, kind, identifier, **base):
    with boundary.scope(**base) as guard:
        yield {"item": _row(guard, kind, identifier), "watermark": guard.saved.watermark}


def _prepare(guard, proposal):
    if type(proposal) is not dict or set(proposal) != {
        "action",
        "kind",
        "identifier",
        "source_digest",
        "head",
        "watermark",
        "reason",
        "request_key",
    }:
        raise SuppressionDenied("suppression_proposal_invalid")
    action, note = proposal["action"], proposal["reason"]
    if (
        action not in {"SOFT_DELETE", "RESTORE", "RECONCILE"}
        or type(note) is not str
        or not 1 <= len(note.strip()) <= 1000
        or "\x00" in note
        or any(0xD800 <= ord(char) <= 0xDFFF for char in note)
    ):
        raise SuppressionDenied("suppression_proposal_invalid")
    catalog.uuid_text(proposal["request_key"])
    if catalog.sha(proposal["watermark"]) != guard.saved.watermark:
        raise SuppressionDenied("suppression_stale_review")
    if action == "RECONCILE":
        if any(proposal[name] != "" for name in ("kind", "identifier", "source_digest", "head")):
            raise SuppressionDenied("suppression_reconciliation_shape_invalid")
        pending = guard.saved.events[len(guard.saved.saved) :][:RECONCILE_BATCH]
        if not pending:
            raise SuppressionDenied("suppression_reconciliation_not_required")
        resources = []
        for value in pending:
            target = guard.target(value["target_kind"], value["target_id"])
            if target.source_digest != value["source_digest"] or target.case_id != value["case_id"]:
                raise SuppressionDenied("suppression_reconciliation_source_changed")
            resource = {
                **guard.resource(target),
                "decision": catalog.digest(value),
                "sequence": value["sequence"],
            }
            guard.require("READ_AUDIT", guard.resource(target))
            guard.require("RECONCILE", resource)
            resources.append(resource)
    else:
        if len(guard.saved.saved) != len(guard.saved.events):
            raise SuppressionDenied("suppression_reconciliation_required")
        target = guard.target(proposal["kind"], proposal["identifier"])
        resource = guard.resource(target)
        if (proposal["source_digest"], proposal["head"]) != (
            resource["source_digest"],
            resource["head"],
        ):
            raise SuppressionDenied("suppression_stale_source")
        guard.require("READ_AUDIT", resource)
        guard.require(action, resource)
        if (action == "RESTORE") != (resource["state"] == "SOFT_DELETED"):
            raise SuppressionDenied("suppression_transition_invalid")
        resources = [resource]
    return {
        "proposal": proposal,
        "resources": resources,
        "actor": {
            "provider_id": guard.provider_id,
            "subject_id": guard.actor.subject_id,
            "role": guard.actor.role,
            "auth_epoch": guard.actor.auth_epoch,
        },
        "policy": catalog.digest(guard.selected[1]),
        "sql_head": guard.saved.saved[-1].digest if guard.saved.saved else catalog.ZERO,
    }


@contextmanager
def preview(*, proposal, **base):
    with boundary.scope(allow_pending=proposal.get("action") == "RECONCILE", **base) as guard:
        plan = _prepare(guard, proposal)
        guard.finish()
        plan["valid_until"] = catalog.stamp(guard.deadline)
        yield plan


def decode(raw):
    if type(raw) is not str or len(raw) > 200000:
        raise SuppressionDenied("suppression_plan_invalid")
    try:
        value = json.loads(raw)
    except ValueError as exc:
        raise SuppressionDenied("suppression_plan_invalid") from exc
    if type(value) is not dict or set(value) != {
        "proposal",
        "resources",
        "actor",
        "policy",
        "sql_head",
        "valid_until",
    }:
        raise SuppressionDenied("suppression_plan_invalid")
    return value


@contextmanager
def apply(*, plan, confirmed=False, **base):
    plan = decode(catalog.canonical(plan))
    if confirmed is not True or catalog.parse_stamp(plan["valid_until"]) <= timezone.now():
        raise SuppressionDenied("suppression_confirmation_expired_or_missing")
    proposal = plan["proposal"]
    with boundary.scope(allow_pending=proposal["action"] == "RECONCILE", **base) as guard:
        prepared = _prepare(guard, proposal)
        if prepared != {k: v for k, v in plan.items() if k != "valid_until"}:
            raise SuppressionDenied("suppression_stale_review")
        guard.deadline = min(guard.deadline, catalog.parse_stamp(plan["valid_until"]))
        guard.finish()
        if proposal["action"] == "RECONCILE":
            pending = guard.saved.events[len(guard.saved.saved) :][:RECONCILE_BATCH]
            for value in pending:
                row = store.insert(
                    value,
                    actor=guard.actor,
                    provider_id=guard.provider_id,
                    recovered=True,
                    recovery_reason=proposal["reason"],
                )
                guard.saved.saved = [*guard.saved.saved, row]
            guard.allow_pending = len(guard.saved.saved) != len(guard.saved.events)
            result = {
                "action": "RECONCILE",
                "count": len(plan["resources"]),
                "digest": guard.saved.watermark,
                "still_closed": guard.allow_pending,
            }
        else:
            resource = prepared["resources"][0]
            value = {
                "id": proposal["request_key"],
                "ledger_id": guard.saved.journal.ledger_id,
                "sequence": len(guard.saved.events) + 1,
                "previous_digest": guard.saved.saved[-1].digest
                if guard.saved.saved
                else catalog.ZERO,
                "target_kind": resource["kind"],
                "target_id": resource["id"],
                "source_digest": resource["source_digest"],
                "case_id": resource["case_id"],
                "version": resource["version"] + 1,
                "previous_state": resource["state"],
                "state": "SOFT_DELETED" if proposal["action"] == "SOFT_DELETE" else "RESTORED",
                "action": proposal["action"],
                "provider_id": guard.provider_id,
                "subject_id": guard.actor.subject_id,
                "role": guard.actor.role,
                "auth_epoch": guard.actor.auth_epoch,
                "reason_sha256": catalog.text_hash(proposal["reason"]),
                "occurred_at": catalog.stamp(timezone.now()),
            }
            # External metadata first. SQL or final-policy failure deliberately
            # requires recovery; it never resurrects an older accepted state.
            guard.saved.journal.append(guard.saved.events, value)
            row = store.insert(
                value, actor=guard.actor, provider_id=guard.provider_id, reason=proposal["reason"]
            )
            guard.append(value, row)
            result = {
                "action": row.action,
                "kind": row.target_kind,
                "id": str(row.target_id),
                "state": row.state,
                "digest": row.digest,
                "count": 1,
            }
        guard.final_pins()
        yield result
