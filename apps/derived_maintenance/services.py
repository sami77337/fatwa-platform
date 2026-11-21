"""Preview exact payload disposal; explicitly rebuild through existing owner services."""

import json
from contextlib import contextmanager

from django.utils import timezone

from apps.casework.models import Case

from . import boundary, catalog, store
from .catalog import DerivedDenied

RECONCILE_BATCH = 128
PROPOSAL_FIELDS = {
    "action",
    "kind",
    "identifier",
    "header_digest",
    "payload_digest",
    "clearance",
    "watermark",
    "reason",
    "request_key",
    "parameters",
}


def _row(guard, kind, identifier):
    from .models import DerivativeRebuild

    target = guard.target(kind, identifier)
    resource = guard.resource(target)
    guard.require("READ_AUDIT", resource)
    clearance = next(
        (row for row in guard.saved.saved if row.kind == kind and str(row.target_id) == identifier),
        None,
    )
    history = []
    if clearance:
        history.append(
            dict(
                action="CLEAR",
                actor=clearance.subject_id,
                role=clearance.role,
                reason=clearance.reason,
                occurred_at=clearance.occurred_at,
                digest=clearance.digest,
                recovered=clearance.recovered,
                recovery_reason=clearance.recovery_reason,
            )
        )
        for row in DerivativeRebuild.objects.filter(clearance=clearance).order_by(
            "created_at", "pk"
        )[:65]:
            history.append(
                dict(
                    action="REBUILD",
                    actor=row.subject_id,
                    role=row.role,
                    reason=row.reason,
                    occurred_at=row.created_at,
                    digest=row.digest,
                    child_id=str(row.child_id),
                    status=row.status,
                )
            )
    return {**resource, "history": history}


@contextmanager
def desk(**base):
    with boundary.scope(allow_pending=True, **base) as guard:
        rows = []
        for kind, identifier in sorted(guard.resources()):
            try:
                rows.append(_row(guard, kind, identifier))
            except DerivedDenied:
                continue
        pending = guard.saved.events[len(guard.saved.saved) :]
        visible = 0
        try:
            for value in pending:
                target = guard.target(value["kind"], value["target_id"])
                resource = guard.resource(target)
                guard.require("READ_AUDIT", resource)
                guard.require("RECONCILE", {**resource, "decision": catalog.digest(value)})
            visible = len(pending)
        except DerivedDenied:
            pass
        yield dict(rows=rows, pending=visible, watermark=guard.saved.watermark)


@contextmanager
def inspect(*, kind, identifier, **base):
    with boundary.scope(**base) as guard:
        yield {"item": _row(guard, kind, identifier), "watermark": guard.saved.watermark}


def _prepare(guard, proposal):
    if type(proposal) is not dict or set(proposal) != PROPOSAL_FIELDS:
        raise DerivedDenied("derived_proposal_invalid")
    action, note = proposal["action"], proposal["reason"]
    if (
        action not in {"CLEAR", "REBUILD", "RECONCILE"}
        or type(note) is not str
        or not 1 <= len(note.strip()) <= 1000
        or "\x00" in note
        or any(0xD800 <= ord(char) <= 0xDFFF for char in note)
        or type(proposal["parameters"]) is not dict
    ):
        raise DerivedDenied("derived_proposal_invalid")
    catalog.uuid_text(proposal["request_key"])
    if catalog.sha(proposal["watermark"]) != guard.saved.watermark:
        raise DerivedDenied("derived_stale_review")
    inputs = {}
    if action == "RECONCILE":
        if (
            any(
                proposal[name] != ""
                for name in ("kind", "identifier", "header_digest", "payload_digest", "clearance")
            )
            or proposal["parameters"]
        ):
            raise DerivedDenied("derived_reconciliation_shape_invalid")
        pending = guard.saved.events[len(guard.saved.saved) :][:RECONCILE_BATCH]
        if not pending:
            raise DerivedDenied("derived_reconciliation_not_required")
        resources = []
        for value in pending:
            target = guard.target(value["kind"], value["target_id"])
            if (
                target.header_digest != value["header_digest"]
                or target.case_id != value["case_id"]
                or target.payload
                and target.manifest() != value["payload"]
            ):
                raise DerivedDenied("derived_reconciliation_payload_changed")
            resource = guard.resource(target)
            guard.require("READ_AUDIT", resource)
            selected = {**resource, "decision": catalog.digest(value)}
            guard.require("RECONCILE", selected)
            resources.append(selected)
    else:
        if len(guard.saved.saved) != len(guard.saved.events):
            raise DerivedDenied("derived_reconciliation_required")
        target = guard.target(proposal["kind"], proposal["identifier"])
        resource = guard.resource(target)
        if any(
            proposal[name] != resource[name]
            for name in ("header_digest", "payload_digest", "clearance")
        ):
            raise DerivedDenied("derived_stale_payload")
        guard.require("READ_AUDIT", resource)
        guard.require(action, resource)
        if action == "CLEAR":
            if resource["state"] != "PRESENT" or proposal["parameters"]:
                raise DerivedDenied("derived_clear_payload_required")
        else:
            if resource["state"] != "CLEARED" or target.payload:
                raise DerivedDenied("derived_cleared_parent_required")
            if guard.actor.role != "MUFTI":
                raise DerivedDenied("derived_rebuild_owner_role_required")
            case = Case.objects.get(pk=target.case_id)
            inputs = dict(case_revision=case.revision, evidence_version=case.evidence_version)
            if target.kind == "SEARCH_INDEX":
                from apps.canonical_search.models import SearchGeneration

                latest = SearchGeneration.objects.filter(case=case).order_by("-number").first()
                if latest is None or str(latest.pk) != target.identifier or proposal["parameters"]:
                    raise DerivedDenied("derived_search_parent_superseded")
                inputs["generation"] = latest.number
            else:
                from apps.ai_gateway import services as gateway
                from apps.ai_gateway.models import GatewayRun

                run = GatewayRun.objects.get(pk=target.identifier)
                query = proposal["parameters"].get("query")
                if (
                    set(proposal["parameters"]) != {"query"}
                    or type(query) is not str
                    or not 1 <= len(query) <= gateway.MAX_QUERY
                    or any(ord(char) < 32 and char not in "\t\n\r" for char in query)
                    or any(0xD800 <= ord(char) <= 0xDFFF for char in query)
                    or catalog.text_hash(query) != run.query_digest
                ):
                    raise DerivedDenied("derived_fresh_fragment_required")
                configured = gateway.configuration()
                inputs.update(
                    selection=run.source["kind"] + ":" + run.source["id"],
                    start=run.source["locator"]["start"],
                    end=run.source["locator"]["end"],
                    provider=gateway.provider_fields(configured[3]),
                    gateway_policy=catalog.digest(configured[1]),
                )
        resources = [resource]
    return dict(
        proposal=proposal,
        resources=resources,
        inputs=inputs,
        actor=dict(
            provider_id=guard.provider_id,
            subject_id=guard.actor.subject_id,
            role=guard.actor.role,
            auth_epoch=guard.actor.auth_epoch,
        ),
        policy=catalog.digest(guard.selected[1]),
        sql_head=guard.saved.saved[-1].digest if guard.saved.saved else catalog.ZERO,
    )


@contextmanager
def preview(*, proposal, **base):
    with boundary.scope(allow_pending=proposal.get("action") == "RECONCILE", **base) as guard:
        plan = _prepare(guard, proposal)
        guard.finish()
        plan["valid_until"] = catalog.stamp(guard.deadline)
        yield plan


def decode(raw):
    if type(raw) is not str or len(raw) > 200000:
        raise DerivedDenied("derived_plan_invalid")
    try:
        value = json.loads(raw)
    except ValueError as exc:
        raise DerivedDenied("derived_plan_invalid") from exc
    if type(value) is not dict or set(value) != {
        "proposal",
        "resources",
        "inputs",
        "actor",
        "policy",
        "sql_head",
        "valid_until",
    }:
        raise DerivedDenied("derived_plan_invalid")
    return value


def _check_plan(guard, plan):
    prepared = _prepare(guard, plan["proposal"])
    if prepared != {key: value for key, value in plan.items() if key != "valid_until"}:
        raise DerivedDenied("derived_stale_review")
    guard.deadline = min(guard.deadline, catalog.parse_stamp(plan["valid_until"]))
    guard.finish()
    return prepared


def _rebuild_record(guard, *, parent, child_id, child_digest, status, request_key, reason):
    from apps.precise_citations.boundary import seal

    from .models import DerivativeClear, DerivativeRebuild

    clearance = DerivativeClear.objects.get(kind=parent.kind, target_id=parent.identifier)
    if DerivativeRebuild.objects.filter(clearance=clearance).count() >= 64:
        raise DerivedDenied("derived_rebuild_history_bound")
    row = seal(
        DerivativeRebuild(
            id=request_key,
            clearance=clearance,
            child_id=child_id,
            child_digest=child_digest,
            status=status,
            provider_id=guard.provider_id,
            subject_id=guard.actor.subject_id,
            role=guard.actor.role,
            auth_epoch=guard.actor.auth_epoch,
            reason=reason,
        )
    )
    guard.rebuilt(row)
    return row


@contextmanager
def apply(*, plan, confirmed=False, **base):
    plan = decode(catalog.canonical(plan))
    if confirmed is not True or catalog.parse_stamp(plan["valid_until"]) <= timezone.now():
        raise DerivedDenied("derived_confirmation_expired_or_missing")
    proposal = plan["proposal"]
    if proposal["action"] == "REBUILD" and proposal["kind"] == "AI_CANDIDATES":
        from .rebuild import regenerate

        result, intent = regenerate(plan=plan, base=base)
        # Rendering is a fresh short transaction after provider execution. It
        # repeats the management mandate and retains every earlier pure pin.
        with intent.stage():
            yield result
        return
    with boundary.scope(allow_pending=proposal["action"] == "RECONCILE", **base) as guard:
        prepared = _check_plan(guard, plan)
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
                guard.cleared(value, row, appended=False)
            guard.allow_pending = len(guard.saved.saved) != len(guard.saved.events)
            result = dict(action="RECONCILE", count=len(pending), still_closed=guard.allow_pending)
        elif proposal["action"] == "CLEAR":
            target = guard.targets[proposal["kind"], proposal["identifier"]]
            value = dict(
                id=proposal["request_key"],
                ledger_id=guard.saved.journal.ledger_id,
                sequence=len(guard.saved.events) + 1,
                previous_digest=prepared["sql_head"],
                kind=target.kind,
                target_id=target.identifier,
                header_digest=target.header_digest,
                case_id=target.case_id,
                payload=target.manifest(),
                provider_id=guard.provider_id,
                subject_id=guard.actor.subject_id,
                role=guard.actor.role,
                auth_epoch=guard.actor.auth_epoch,
                reason_sha256=catalog.text_hash(proposal["reason"]),
                occurred_at=catalog.stamp(timezone.now()),
            )
            guard.saved.journal.append(guard.saved.events, value)
            row = store.insert(
                value, actor=guard.actor, provider_id=guard.provider_id, reason=proposal["reason"]
            )
            guard.cleared(value, row)
            result = dict(action="CLEAR", count=len(target.payload), target_id=target.identifier)
        else:
            from apps.canonical_search import services as search
            from apps.canonical_search.models import SearchGeneration

            from .rebuild import retaining

            target = guard.targets[proposal["kind"], proposal["identifier"]]
            with retaining(guard):
                built = search.rebuild(
                    case_id=target.case_id,
                    provider=guard.provider,
                    subject_id=guard.actor.subject_id,
                    synthetic_fixtures_only=True,
                    expected_revision=prepared["inputs"]["case_revision"],
                    expected_evidence_version=prepared["inputs"]["evidence_version"],
                    expected_generation=prepared["inputs"]["generation"],
                    request_key=proposal["request_key"],
                )
            if not built["created"] or built["generation_id"] == target.identifier:
                raise DerivedDenied("derived_new_generation_required")
            child = SearchGeneration.objects.get(pk=built["generation_id"])
            _rebuild_record(
                guard,
                parent=target,
                child_id=child.pk,
                child_digest=child.digest,
                status="SUCCEEDED",
                request_key=proposal["request_key"],
                reason=proposal["reason"],
            )
            result = dict(action="REBUILD", child_id=str(child.pk), status="SUCCEEDED")
        guard.finish()
        yield result
