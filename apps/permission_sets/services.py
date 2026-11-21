"""Review an exact change, then append one immutable revision under fresh authority."""

import json
import uuid
from contextlib import contextmanager
from datetime import datetime, timedelta
from types import SimpleNamespace

from django.utils import timezone

from . import boundary, catalog, store
from .catalog import PermissionDenied


def _key(kind, key):
    if kind == "SET":
        return catalog.uuid_text(key)
    if kind == "USER":
        return catalog.identifier(key)
    raise PermissionDenied("permission_scope_invalid")


def _head(guard, kind, key):
    return store.latest(guard.saved).get((kind, guard.provider_id, key))


def _audit(guard, kind, key, target=None):
    guard.require("READ_AUDIT", kind, key, target=target)
    return [
        {
            "id": str(row.pk),
            "number": row.number,
            "state": row.state,
            "change": row.change,
            "note": row.note,
            "created_at": row.created_at,
            "actor": row.actor_subject_id,
            "role": row.actor_role,
            "digest": row.digest,
            "reverted_from": str(row.reverted_from_id) if row.reverted_from_id else "",
        }
        for row in reversed(store.history(kind, guard.provider_id, key, values=guard.saved))
    ]


def _read(guard, kind, key):
    _key(kind, key)
    current = _head(guard, kind, key)
    target = guard.target(key) if kind == "USER" else None
    if kind == "SET" and current is None:
        guard.require("CREATE_SET")
    else:
        guard.require("READ_" + kind, kind, key, target=target)
    return current, target


def _dto(row):
    return (
        None
        if row is None
        else {
            "id": str(row.pk),
            "kind": row.kind,
            "key": row.scope_key,
            "number": row.number,
            "digest": row.digest,
            "state": row.state,
            "valid_until": row.valid_until,
            "definition": row.definition,
            "target_role": row.target_role,
            "note": row.note,
        }
    )


@contextmanager
def desk(**base):
    with boundary.scope(**base) as guard:
        result = {"sets": [], "users": [], "can_create": False, "actor": guard.actor.subject_id}
        try:
            guard.require("CREATE_SET")
            result["can_create"] = True
        except PermissionDenied:
            pass
        for key, row in store.latest(guard.saved).items():
            if key[:2] != ("SET", guard.provider_id):
                continue
            try:
                guard.require("READ_SET", "SET", row.scope_key)
            except PermissionDenied:
                continue
            result["sets"].append(_dto(row))
        for subject in guard.candidates():
            try:
                target = guard.target(subject)
                guard.require("READ_USER", "USER", subject, target=target)
            except PermissionDenied:
                continue
            result["users"].append(
                {
                    "subject": subject,
                    "role": target.role,
                    "self": subject == guard.actor.subject_id,
                    "current": _dto(_head(guard, "USER", subject)),
                }
            )
        yield result


@contextmanager
def inspect(*, kind, key, **base):
    with boundary.scope(**base) as guard:
        current, target = _read(guard, kind, key)
        versions = _audit(guard, kind, key, target) if current is not None else []
        choices = []
        for value in guard.choices().values():
            if target is None or catalog.verify_scope(value) <= target.case_keys:
                choices.append(catalog.display(value))
        templates = []
        if kind == "USER":
            for (row_kind, provider, _), row in store.latest(guard.saved).items():
                if row_kind != "SET" or provider != guard.provider_id:
                    continue
                try:
                    guard.require("READ_SET", "SET", row.scope_key)
                except PermissionDenied:
                    continue
                templates.append(_dto(row))
        yield {
            "kind": kind,
            "key": key,
            "current": _dto(current),
            "history": versions,
            "choices": choices,
            "sets": templates,
            "expected_digest": current.digest if current else catalog.ZERO,
            "self": bool(target and target.subject_id == guard.actor.subject_id),
            "role": target.role if target else "",
        }


def _rules(definition, kind, heads, provider):
    if kind == "SET":
        return definition["rules"]
    rules = list(definition["overrides"])
    for key in definition["sets"]:
        selected = heads.get(("SET", provider, key))
        if selected is None:
            raise PermissionDenied("permission_template_unavailable")
        rules.extend(selected.definition["rules"])
    return rules


def _diff(before, after):
    old, new = store.effects(before), store.effects(after)
    result = []
    for key in sorted(set(old) | set(new)):
        previous, current = old.get(key), new.get(key)
        if previous == current:
            continue
        result.append(
            {
                **catalog.display((current or previous)["scope"]),
                "before": previous["effect"] if previous else "NONE",
                "after": current["effect"] if current else "NONE",
            }
        )
    return result


def _prepare(
    guard,
    *,
    kind,
    key,
    change,
    definition,
    expected_digest,
    note,
    minutes,
    request_key,
    reverted_from=None,
    valid_until=None,
):
    _key(kind, key)
    if change not in {"CREATE", "REPLACE", "DISABLE", "REVERT"}:
        raise PermissionDenied("permission_change_invalid")
    if type(minutes) is not int or minutes not in {5, 15, 30, 60}:
        raise PermissionDenied("permission_duration_invalid")
    note = catalog.text(note, 1000)
    request_key = catalog.uuid_text(request_key)
    heads = store.latest(guard.saved)
    current, target = _read(guard, kind, key)
    if expected_digest != (current.digest if current else catalog.ZERO):
        raise PermissionDenied("permission_stale_revision")
    if current is not None and current.number >= 256:
        raise PermissionDenied("permission_history_bound")
    if (current is None) != (change == "CREATE"):
        raise PermissionDenied("permission_change_invalid")
    if kind == "USER":
        target = guard.target(key, changing=True)
        guard.require("WRITE_USER", kind, key, target=target)
    else:
        guard.require(
            "CREATE_SET" if current is None else "WRITE_SET",
            "" if current is None else kind,
            "" if current is None else key,
        )
    if current is not None:
        _audit(guard, kind, key, target)
    state = "ACTIVE"
    selected_revert = None
    if change == "DISABLE":
        if definition is not None:
            raise PermissionDenied("permission_disable_definition_forbidden")
        definition, state = current.definition, "DISABLED"
    elif change == "REVERT":
        if definition is not None:
            raise PermissionDenied("permission_revert_definition_forbidden")
        catalog.uuid_text(reverted_from)
        selected_revert = next((row for row in guard.saved if str(row.pk) == reverted_from), None)
        if (
            selected_revert is None
            or (selected_revert.kind, selected_revert.provider_id, selected_revert.scope_key)
            != (kind, guard.provider_id, key)
            or selected_revert.number >= current.number
        ):
            raise PermissionDenied("permission_revert_source_invalid")
        definition, state = selected_revert.definition, selected_revert.state
    elif reverted_from is not None:
        raise PermissionDenied("permission_revert_source_invalid")
    definition = catalog.definition(kind, definition)
    old_definition = (
        current.definition
        if current
        else (
            {"title": definition["title"], "rules": []}
            if kind == "SET"
            else {"sets": [], "overrides": []}
        )
    )
    old_rules = _rules(old_definition, kind, heads, guard.provider_id)
    new_rules = _rules(definition, kind, heads, guard.provider_id)
    all_rules = {catalog.digest(rule): rule for rule in [*old_rules, *new_rules]}
    if kind == "USER":
        for identifier in set(old_definition["sets"]) | set(definition["sets"]):
            selected = heads.get(("SET", guard.provider_id, identifier))
            if selected is None:
                raise PermissionDenied("permission_template_unavailable")
            guard.require("READ_SET", "SET", identifier)
            if (
                state == "ACTIVE"
                and identifier in definition["sets"]
                and (
                    selected.state != "ACTIVE"
                    or selected.valid_until is None
                    or selected.valid_until <= timezone.now()
                )
            ):
                raise PermissionDenied("permission_template_unavailable")
    affected = []
    if kind == "SET":
        affected = [
            row
            for (row_kind, provider, _), row in heads.items()
            if row_kind == "USER"
            and provider == guard.provider_id
            and key in row.definition["sets"]
        ]
        if any(row.scope_key == guard.actor.subject_id for row in affected):
            raise PermissionDenied("permission_self_template_change_denied")
    for rule in all_rules.values():
        guard.manage_rule(rule, kind, key, target)
    for user in affected:
        actor = guard.target(user.scope_key, changing=True)
        guard.require("READ_USER", "USER", user.scope_key, target=actor)
        guard.require("WRITE_USER", "USER", user.scope_key, target=actor)
        for rule in all_rules.values():
            guard.manage_rule(rule, "USER", user.scope_key, actor)
    guard.callbacks()
    guard.final_pins()
    until = min(guard.deadline, timezone.now() + timedelta(minutes=minutes))
    if valid_until is not None:
        try:
            proposed = datetime.fromisoformat(valid_until)
        except (TypeError, ValueError) as exc:
            raise PermissionDenied("permission_preview_expired") from exc
        if not timezone.is_aware(proposed) or not timezone.now() < proposed <= until:
            raise PermissionDenied("permission_preview_expired")
        until = proposed
    candidate = SimpleNamespace(
        kind=kind,
        provider_id=guard.provider_id,
        scope_key=key,
        definition=definition,
        state=state,
        valid_until=until,
    )
    after_heads = {**heads, (kind, guard.provider_id, key): candidate}
    summaries = []
    if kind == "USER":
        affected = [current] if current else []
        before_effective = store.resolved(current, heads)[0]
        after_effective = store.resolved(candidate, after_heads)[0]
        summaries.append(
            {
                "subject": key,
                "role": target.role,
                "changes": _diff(before_effective, after_effective),
            }
        )
    else:
        for user in affected:
            summaries.append(
                {
                    "subject": user.scope_key,
                    "role": guard.targets[user.scope_key].role,
                    "changes": _diff(
                        store.resolved(user, heads)[0], store.resolved(user, after_heads)[0]
                    ),
                }
            )
    context = {
        "ledger": catalog.digest(guard.watermark),
        "policy": catalog.digest(guard.selected[1]),
        "actor": catalog.digest(
            [
                guard.provider_id,
                guard.actor.subject_id,
                guard.actor.role,
                guard.actor.auth_epoch,
                sorted(guard.actor.case_keys),
            ]
        ),
        "targets": {
            subject: [principal.role, principal.auth_epoch, store.scope_digest(principal.actor)]
            for subject, principal in sorted(guard.targets.items())
        },
        "sets": {
            identifier: heads[("SET", guard.provider_id, identifier)].digest
            for identifier in sorted(
                set(old_definition.get("sets", [])) | set(definition.get("sets", []))
            )
        },
        "affected": [row.scope_key for row in affected if row is not None],
    }
    proposal = {
        "kind": kind,
        "key": key,
        "change": change,
        "definition": definition if change in {"CREATE", "REPLACE"} else None,
        "expected_digest": expected_digest,
        "note": note,
        "minutes": minutes,
        "request_key": request_key,
        "reverted_from": reverted_from,
        "valid_until": until.isoformat(),
    }
    return {
        "proposal": proposal,
        "context": context,
        "definition": definition,
        "state": state,
        "target_role": target.role if target else "",
        "target_auth_epoch": target.auth_epoch if target else "",
        "target_scope_digest": store.scope_digest(target) if target else "",
        "number": current.number + 1 if current else 1,
        "summaries": summaries,
        "changes": _diff(
            old_rules if current and current.state == "ACTIVE" else [],
            new_rules if state == "ACTIVE" else [],
        ),
    }


@contextmanager
def preview(*, proposal, **base):
    with boundary.scope(**base) as guard:
        plan = _prepare(guard, **proposal)
        yield plan


@contextmanager
def apply(*, plan, confirmed=False, **base):
    if (
        confirmed is not True
        or type(plan) is not dict
        or set(plan)
        != {
            "proposal",
            "context",
            "definition",
            "state",
            "target_role",
            "target_auth_epoch",
            "target_scope_digest",
            "number",
            "summaries",
            "changes",
        }
    ):
        raise PermissionDenied("permission_confirmed_preview_required")
    with boundary.scope(**base) as guard:
        prepared = _prepare(guard, **plan["proposal"])
        if catalog.digest(prepared) != catalog.digest(plan):
            raise PermissionDenied("permission_preview_changed")
        proposal = prepared["proposal"]
        if store.model().objects.filter(request_key=proposal["request_key"]).exists():
            raise PermissionDenied("permission_request_already_applied")
        row = store.model()(
            id=uuid.uuid4(),
            kind=proposal["kind"],
            provider_id=guard.provider_id,
            scope_key=proposal["key"],
            number=prepared["number"],
            previous_digest=proposal["expected_digest"],
            state=prepared["state"],
            change=proposal["change"],
            definition=prepared["definition"],
            valid_until=datetime.fromisoformat(proposal["valid_until"]),
            target_role=prepared["target_role"],
            target_auth_epoch=prepared["target_auth_epoch"],
            target_scope_digest=prepared["target_scope_digest"],
            actor_provider_id=guard.provider_id,
            actor_subject_id=guard.actor.subject_id,
            actor_role=guard.actor.role,
            actor_auth_epoch=guard.actor.auth_epoch,
            policy_digest=prepared["context"]["policy"],
            context=prepared["context"],
            note=proposal["note"],
            request_key=proposal["request_key"],
            request_digest=catalog.digest(proposal),
            reverted_from_id=proposal["reverted_from"],
        )
        store.seal(row).save(force_insert=True)
        guard.account(row)
        guard.final_pins()
        yield {"saved": _dto(row), "summary": prepared["summaries"]}


def decode(value):
    if type(value) is not str or len(value) > 131072:
        raise PermissionDenied("permission_preview_invalid")
    try:
        return json.loads(value)
    except (ValueError, TypeError) as exc:
        raise PermissionDenied("permission_preview_invalid") from exc
