"""Human-only optional identity links. No original, access, or route mutation."""

from apps.casework import services as cases
from apps.platform_recovery.integration import mutation_service

from .boundary import ZERO, digest, origin, scope, seal, text, verify
from .models import (
    IdentityMembership,
    IdentityObservation,
    LinkProposal,
    Person,
    PlatformIdentity,
    RegistryOperation,
)

MAX_IDENTITIES = 64
STATE_LABELS = {
    "UNLINKED": "غير مرتبطة",
    "POSSIBLE_MATCH": "ربط مقترح بانتظار تحقق مستقل",
    "VERIFIED_LINK": "ربط تحقّق منه إنسان مستقل",
}


def _latest(identifier):
    rows = list(
        IdentityMembership.objects.filter(identity_id=identifier).order_by("sequence")[:2049]
    )
    if len(rows) > 2048:
        raise cases.CaseConflict("identity_registry_history_bound")
    previous = ZERO
    for number, row in enumerate(rows, 1):
        verify(row)
        verify(row.operation)
        if row.sequence != number or row.previous_digest != previous:
            raise cases.CaseConflict("identity_registry_membership_history")
        change = next(
            (item for item in row.operation.changes if item["identity_id"] == str(identifier)), None
        )
        if (
            change is None
            or change["before_digest"] != previous
            or change["after_person"] != (str(row.person_id) if row.person_id else None)
        ):
            raise cases.CaseConflict("identity_registry_membership_history")
        previous = row.digest
    return rows[-1] if rows else None


def _pending(identifier):
    rows = list(
        LinkProposal.objects.filter(
            identity_id=identifier, registryoperation__isnull=True
        ).order_by("created_at", "pk")[:2]
    )
    if len(rows) > 1:
        raise cases.CaseConflict("identity_registry_pending_conflict")
    for row in rows:
        verify(row)
    return rows[0] if rows else None


def _identity_cases(identifier):
    return set(
        IdentityObservation.objects.filter(identity_id=identifier).values_list("case_id", flat=True)
    )


def _person_cases(person):
    result = {person.case_id}
    for identifier in (
        IdentityMembership.objects.filter(person=person)
        .values_list("identity_id", flat=True)
        .distinct()
    ):
        current = _latest(identifier)
        if current and current.person_id == person.pk:
            result |= _identity_cases(identifier)
    return result


def _identity(guard, identifier, action="READ"):
    key = cases._uuid(identifier)
    row = (
        PlatformIdentity.objects.filter(pk=key, identityobservation__case_id__in=guard.locked)
        .distinct()
        .first()
    )
    if row is None:
        raise cases.CaseConflict("identity_registry_unavailable")
    verify(row)
    observations = list(IdentityObservation.objects.filter(identity=row).order_by("case_id"))
    guard.use_cases(
        [item.case_id for item in observations],
        action,
        {"kind": "IDENTITY", "id": str(row.pk), "digest": row.digest},
    )
    for item in observations:
        verify(item)
        actual = origin(guard.locked[item.case_id])
        if (
            actual["identity_key"] != row.identity_key
            or actual["origin_digest"] != item.origin_digest
            or actual["receipt_id"] != item.receipt_id
            or actual["display_name"] != item.display_name
        ):
            raise cases.CaseConflict("identity_registry_origin_changed")
    return row


def _person(guard, identifier, action="READ", *, group=False):
    row = Person.objects.filter(pk=cases._uuid(identifier), case_id__in=guard.locked).first()
    if row is None:
        raise cases.CaseConflict("identity_registry_unavailable")
    verify(row)
    guard.use_cases(
        _person_cases(row) if group else [row.case_id],
        action,
        {"kind": "PERSON", "id": str(row.pk), "digest": row.digest},
    )
    return row


def _current_ids(person):
    result = []
    for identifier in (
        IdentityMembership.objects.filter(person=person)
        .values_list("identity_id", flat=True)
        .distinct()
    ):
        current = _latest(identifier)
        if current and current.person_id == person.pk:
            result.append(identifier)
    if len(result) > MAX_IDENTITIES:
        raise cases.CaseConflict("identity_registry_group_bound")
    return sorted(result)


def _identity_dto(guard, row):
    current, pending = _latest(row.pk), _pending(row.pk)
    person = _person(guard, current.person_id) if current and current.person_id else None
    state = "VERIFIED_LINK" if person else "POSSIBLE_MATCH" if pending else "UNLINKED"
    proposal = None
    if pending:
        guard.permit(
            pending.case_id,
            "READ",
            {"kind": "PROPOSAL", "id": str(pending.pk), "digest": pending.digest},
        )
        proposed_person = _person(guard, pending.person_id)
        proposal = {
            "id": str(pending.pk),
            "person": proposed_person.label,
            "evidence": pending.evidence,
            "author": pending.subject_id,
            "provider": pending.provider_id,
            "can_review": (pending.provider_id, pending.subject_id)
            != (guard.provider.provider_id, guard.actor.subject_id),
        }
    observations = list(
        IdentityObservation.objects.filter(identity=row).order_by("case__public_ref")
    )
    return {
        "id": str(row.pk),
        "source": row.source,
        "account": row.account,
        "source_subject": row.source_subject,
        "state": state,
        "state_label": STATE_LABELS[state],
        "person_id": str(person.pk) if person else "",
        "person_label": person.label if person else "",
        "proposal": proposal,
        "membership_digest": current.digest if current else ZERO,
        "observations": [
            {
                "case_ref": guard.locked[item.case_id].public_ref,
                "display_name": item.display_name,
                "origin_digest": item.origin_digest,
            }
            for item in observations
        ],
    }


def desk_locked(guard, *, case_id, query=""):
    text(query, 128, optional=True)
    query = query.strip().casefold()
    case = guard.locked[cases._uuid(case_id)]
    allowed = {key for key in guard.locked if guard.permit(key, "SEARCH", required=False)}
    candidates = (
        PlatformIdentity.objects.filter(identityobservation__case_id__in=allowed)
        .distinct()
        .order_by("source", "account", "source_subject")
    )
    rows = []
    for row in candidates[: MAX_IDENTITIES + 1]:
        # Omit incomplete identity groups without a count, name, or hidden-case hint.
        if not _identity_cases(row.pk) <= allowed:
            continue
        if (
            query
            and query
            not in " ".join(
                [
                    row.source,
                    row.account,
                    row.source_subject,
                    *IdentityObservation.objects.filter(
                        identity=row, case_id__in=allowed
                    ).values_list("display_name", flat=True),
                ]
            ).casefold()
        ):
            continue
        _identity(guard, row.pk)
        current = _latest(row.pk)
        pending = _pending(row.pk)
        if pending and pending.case_id not in allowed:
            continue
        person_ids = [
            value
            for value in (
                current.person_id if current else None,
                pending.person_id if pending else None,
            )
            if value
        ]
        if any(
            not Person.objects.filter(pk=value, case_id__in=allowed).exists()
            for value in person_ids
        ):
            continue
        rows.append(_identity_dto(guard, row))
    if len(rows) > MAX_IDENTITIES:
        raise cases.CaseConflict("identity_registry_search_bound")
    people = []
    for person in Person.objects.filter(case_id__in=allowed).order_by("created_at", "pk")[
        : MAX_IDENTITIES + 1
    ]:
        if _person_cases(person) <= allowed:
            _person(guard, person.pk, group=True)
            people.append(
                {
                    "id": str(person.pk),
                    "label": person.label,
                    "count": len(_current_ids(person)),
                    "reason": person.reason,
                }
            )
    if len(people) > MAX_IDENTITIES:
        raise cases.CaseConflict("identity_registry_search_bound")
    operations = []
    visible = {row["id"] for row in rows}
    for operation in RegistryOperation.objects.filter(case_id__in=allowed).order_by(
        "created_at", "pk"
    )[:4097]:
        historical_people = {
            value
            for item in operation.changes
            for value in (item["before_person"], item["after_person"])
            if value
        }
        historical_people |= {
            str(value)
            for value in (operation.source_person_id, operation.target_person_id)
            if value
        }
        needed_cases = set(
            Person.objects.filter(pk__in=historical_people).values_list("case_id", flat=True)
        ) | {operation.case_id}
        proposal_identity = None
        if operation.proposal_id:
            proposal = operation.proposal
            verify(proposal)
            needed_cases.add(proposal.case_id)
            proposal_identity = str(proposal.identity_id)
        if (
            needed_cases <= allowed
            and (proposal_identity is None or proposal_identity in visible)
            and all(item["identity_id"] in visible for item in operation.changes)
        ):
            guard.use_cases(
                needed_cases, "AUDIT", {"id": str(operation.pk), "digest": operation.digest}
            )
            guard.permit(
                operation.case_id, "AUDIT", {"id": str(operation.pk), "digest": operation.digest}
            )
            verify(operation)
            operations.append(
                {
                    "id": str(operation.pk),
                    "kind": operation.kind,
                    "reason": operation.reason,
                    "subject": operation.subject_id,
                    "provider": operation.provider_id,
                    "created_at": operation.created_at,
                    "changes": operation.changes,
                    "digest": operation.digest,
                }
            )
    captured = IdentityObservation.objects.filter(case=case).exists()
    return {
        "case_id": str(case.pk),
        "case_ref": case.public_ref,
        "revision": case.revision,
        "evidence_version": case.evidence_version,
        "snapshot": guard.watermark,
        "identities": rows,
        "people": people,
        "history": operations,
        "captured": captured,
        "query": query,
    }


@mutation_service
def desk(*, query="", **base):
    with scope(**base) as guard:
        return desk_locked(guard, case_id=base["case_id"], query=query)


def _start(guard, base, expected_snapshot, expected_revision, expected_evidence_version):
    guard.before_write(
        expected_snapshot, base["case_id"], expected_revision, expected_evidence_version
    )


@mutation_service
def capture(
    *, expected_snapshot, expected_revision, expected_evidence_version, request_key, **base
):
    with scope(**base) as guard:
        case = guard.locked[cases._uuid(base["case_id"])]
        guard.permit(case.pk, "CAPTURE")
        values = origin(case)
        existing = PlatformIdentity.objects.filter(identity_key=values["identity_key"]).first()
        if existing:
            _identity(guard, existing.pk, "CAPTURE")
        if IdentityObservation.objects.filter(case=case).exists():
            raise cases.CaseConflict("identity_registry_already_captured")
        _start(guard, base, expected_snapshot, expected_revision, expected_evidence_version)
        row = existing or seal(
            PlatformIdentity(
                **{
                    key: values[key]
                    for key in ("source", "account", "source_subject", "identity_key")
                },
                **guard.actor_values(),
            )
        )
        observation = seal(
            IdentityObservation(
                identity=row,
                case=case,
                receipt_id=values["receipt_id"],
                origin_digest=values["origin_digest"],
                display_name=values["display_name"],
                request_key=cases._uuid(request_key),
                **guard.actor_values(),
            )
        )
        guard.written()
        return {"id": str(row.pk), "observation_id": str(observation.pk)}


@mutation_service
def create_person(
    *,
    label,
    reason,
    expected_snapshot,
    expected_revision,
    expected_evidence_version,
    request_key,
    confirmed=False,
    **base,
):
    text(label, 256)
    text(reason, 2000)
    if confirmed is not True:
        raise cases.CaseConflict("identity_registry_human_confirmation")
    with scope(**base) as guard:
        guard.permit(base["case_id"], "CREATE_PERSON")
        _start(guard, base, expected_snapshot, expected_revision, expected_evidence_version)
        row = seal(
            Person(
                case_id=base["case_id"],
                label=label,
                reason=reason,
                request_key=cases._uuid(request_key),
                **guard.actor_values(),
            )
        )
        guard.written()
        return {"id": str(row.pk), "label": row.label}


@mutation_service
def propose(
    *,
    identity_id,
    person_id,
    evidence,
    expected_snapshot,
    expected_revision,
    expected_evidence_version,
    request_key,
    confirmed=False,
    **base,
):
    text(evidence, 2000)
    if confirmed is not True:
        raise cases.CaseConflict("identity_registry_human_confirmation")
    with scope(**base) as guard:
        identity = _identity(guard, identity_id, "LINK")
        guard.permit(
            base["case_id"], "LINK", {"identity_id": str(identity.pk), "person_id": str(person_id)}
        )
        person = _person(guard, person_id, "LINK")
        current = _latest(identity.pk)
        if (current and current.person_id) or _pending(identity.pk):
            raise cases.CaseConflict("identity_registry_unlinked_required")
        _start(guard, base, expected_snapshot, expected_revision, expected_evidence_version)
        row = seal(
            LinkProposal(
                identity=identity,
                person=person,
                case_id=base["case_id"],
                previous_digest=current.digest if current else ZERO,
                evidence=evidence,
                request_key=cases._uuid(request_key),
                **guard.actor_values(),
            )
        )
        guard.written()
        return {"id": str(row.pk)}


def _change(identity_id, current, target):
    return {
        "identity_id": str(identity_id),
        "before_digest": current.digest if current else ZERO,
        "before_person": str(current.person_id) if current and current.person_id else None,
        "after_person": str(target) if target else None,
        "sequence": current.sequence + 1 if current else 1,
    }


def _write_operation(
    guard,
    *,
    case_id,
    kind,
    changes,
    reason,
    request_key,
    proposal=None,
    source=None,
    target=None,
    preview_digest=ZERO,
):
    operation = seal(
        RegistryOperation(
            case_id=case_id,
            kind=kind,
            proposal=proposal,
            source_person=source,
            target_person=target,
            changes=changes,
            reason=reason,
            preview_digest=preview_digest,
            request_key=cases._uuid(request_key),
            **guard.actor_values(),
        )
    )
    for change in changes:
        seal(
            IdentityMembership(
                identity_id=change["identity_id"],
                person_id=change["after_person"],
                sequence=change["sequence"],
                previous_digest=change["before_digest"],
                operation=operation,
                **guard.actor_values(),
            )
        )
    guard.written()
    return {"id": str(operation.pk), "kind": kind, "count": len(changes)}


@mutation_service
def decide(
    *,
    kind,
    identity_id,
    proposal_id=None,
    reason,
    expected_snapshot,
    expected_revision,
    expected_evidence_version,
    request_key,
    confirmed=False,
    **base,
):
    text(reason, 2000)
    if confirmed is not True or kind not in {"VERIFY", "REJECT", "UNLINK"}:
        raise cases.CaseConflict("identity_registry_human_confirmation")
    with scope(**base) as guard:
        identity = _identity(
            guard, identity_id, "VERIFY" if kind in {"VERIFY", "REJECT"} else "UNLINK"
        )
        guard.permit(
            base["case_id"],
            "VERIFY" if kind in {"VERIFY", "REJECT"} else "UNLINK",
            {"identity_id": str(identity.pk)},
        )
        current, proposal, target = _latest(identity.pk), None, None
        if kind == "UNLINK":
            if not current or not current.person_id or _pending(identity.pk):
                raise cases.CaseConflict("identity_registry_verified_required")
            _person(guard, current.person_id, "UNLINK")
            changes = [_change(identity.pk, current, None)]
        else:
            proposal = _pending(identity.pk)
            if (
                proposal is None
                or proposal.pk != cases._uuid(proposal_id)
                or proposal.previous_digest != (current.digest if current else ZERO)
                or (current and current.person_id)
            ):
                raise cases.CaseConflict("identity_registry_proposal_changed")
            if (proposal.provider_id, proposal.subject_id) == (
                guard.provider.provider_id,
                guard.actor.subject_id,
            ):
                raise cases.CaseConflict("identity_registry_independent_verifier_required")
            target = _person(guard, proposal.person_id, "VERIFY")
            guard.permit(
                proposal.case_id, "VERIFY", {"id": str(proposal.pk), "digest": proposal.digest}
            )
            changes = [_change(identity.pk, current, target.pk)] if kind == "VERIFY" else []
        _start(guard, base, expected_snapshot, expected_revision, expected_evidence_version)
        return _write_operation(
            guard,
            case_id=base["case_id"],
            kind=kind,
            changes=changes,
            reason=reason,
            request_key=request_key,
            proposal=proposal,
            target=target,
        )


def prepare_locked(guard, *, case_id, kind, source_person_id, target_person_id, identity_ids=None):
    if kind not in {"MERGE", "SPLIT"}:
        raise cases.CaseConflict("identity_registry_operation_invalid")
    guard.permit(case_id, kind, {"source": str(source_person_id), "target": str(target_person_id)})
    source = _person(guard, source_person_id, kind, group=True)
    target = _person(guard, target_person_id, kind, group=True)
    if source.pk == target.pk:
        raise cases.CaseConflict("identity_registry_distinct_people_required")
    current_ids = _current_ids(source)
    if kind == "MERGE":
        selected = current_ids
    else:
        if type(identity_ids) is not list or not 1 <= len(identity_ids) <= MAX_IDENTITIES:
            raise cases.CaseConflict("identity_registry_split_selection_required")
        selected = sorted({cases._uuid(value) for value in identity_ids})
        if len(selected) != len(identity_ids) or not set(selected) < set(current_ids):
            raise cases.CaseConflict("identity_registry_split_subset_required")
    if not selected or len(_current_ids(target)) + len(selected) > MAX_IDENTITIES:
        raise cases.CaseConflict("identity_registry_group_bound")
    changes, affected = [], {source.case_id, target.case_id}
    for identifier in selected:
        _identity(guard, identifier, kind)
        if _pending(identifier):
            raise cases.CaseConflict("identity_registry_pending_conflict")
        current = _latest(identifier)
        changes.append(_change(identifier, current, target.pk))
        affected |= _identity_cases(identifier)
    guard.use_cases(affected, kind, {"source": str(source.pk), "target": str(target.pk)})
    result = {
        "kind": kind,
        "source_person_id": str(source.pk),
        "target_person_id": str(target.pk),
        "source_label": source.label,
        "target_label": target.label,
        "identity_ids": [str(value) for value in selected],
        "changes": changes,
        "affected_cases": [
            {
                "reference": guard.locked[key].public_ref,
                "revision": guard.locked[key].revision,
                "evidence_version": guard.locked[key].evidence_version,
            }
            for key in sorted(affected)
        ],
        "snapshot": guard.watermark,
        "case_id": str(case_id),
    }
    return {**result, "digest": digest(result)}


@mutation_service
def prepare(*, kind, source_person_id, target_person_id, identity_ids=None, **base):
    with scope(**base) as guard:
        return prepare_locked(
            guard,
            case_id=base["case_id"],
            kind=kind,
            source_person_id=source_person_id,
            target_person_id=target_person_id,
            identity_ids=identity_ids,
        )


@mutation_service
def apply(
    *,
    preview,
    reason,
    expected_snapshot,
    expected_revision,
    expected_evidence_version,
    request_key,
    confirmed=False,
    **base,
):
    text(reason, 2000)
    if confirmed is not True or type(preview) is not dict:
        raise cases.CaseConflict("identity_registry_human_confirmation")
    with scope(**base) as guard:
        current = prepare_locked(
            guard,
            case_id=base["case_id"],
            kind=preview.get("kind"),
            source_person_id=preview.get("source_person_id"),
            target_person_id=preview.get("target_person_id"),
            identity_ids=preview.get("identity_ids"),
        )
        if current != preview:
            raise cases.CaseConflict("identity_registry_preview_changed")
        _start(guard, base, expected_snapshot, expected_revision, expected_evidence_version)
        return _write_operation(
            guard,
            case_id=base["case_id"],
            kind=current["kind"],
            changes=current["changes"],
            reason=reason,
            request_key=request_key,
            source=Person.objects.get(pk=current["source_person_id"]),
            target=Person.objects.get(pk=current["target_person_id"]),
            preview_digest=current["digest"],
        )
