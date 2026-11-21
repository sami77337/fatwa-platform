"""Reviewed immutable synonym versions and live canonical shadow comparisons."""

import re
from datetime import timedelta
from time import perf_counter_ns

from django.db import DatabaseError, transaction
from django.utils import timezone

from apps.casework import services as cases
from apps.platform_recovery.integration import mutation_service

from . import governance_pins, policy, services
from .models import ShadowComparison, SynonymDecision, SynonymPreview, SynonymRevision
from .text import PROFILE, digest, normalize, query

MAPPING_KINDS = {"SAME", "RENAMED", "MOVED", "SPLIT", "MERGED", "NO_EQUIVALENT"}
MAX_REVISIONS, MAX_PREVIEWS, MAX_SHADOWS = 64, 16, 128


def _text(value, maximum):
    cases._text(value)
    if len(value) > maximum:
        raise cases.CaseConflict("search_governance_text_bound")
    return value


def _word(value):
    _text(value, 48)
    if re.fullmatch(r"[^\W_]+", normalize(value), re.UNICODE) is None:
        raise cases.CaseConflict("search_synonym_single_word_required")
    return value


def validate_entries(entries):
    if type(entries) is not list or not 1 <= len(entries) <= 12:
        raise cases.CaseConflict("search_dictionary_entries_bound")
    keys, terms = set(), set()
    for entry in entries:
        if type(entry) is not dict or set(entry) != {"key", "term", "alternatives"}:
            raise cases.CaseConflict("search_dictionary_entry_invalid")
        key = entry["key"]
        if (
            type(key) is not str
            or re.fullmatch(r"[a-z][a-z0-9._-]{0,39}", key) is None
            or key in keys
        ):
            raise cases.CaseConflict("search_dictionary_key_invalid")
        term = normalize(_word(entry["term"]))
        if term in terms:
            raise cases.CaseConflict("search_dictionary_duplicate_term")
        alternatives = entry["alternatives"]
        if type(alternatives) is not list or not 1 <= len(alternatives) <= 3:
            raise cases.CaseConflict("search_dictionary_alternatives_bound")
        normalized = [normalize(_word(value)) for value in alternatives]
        if len(set(normalized)) != len(normalized) or term in normalized:
            raise cases.CaseConflict("search_dictionary_duplicate_alternative")
        keys.add(key)
        terms.add(term)
    return entries


def validate_mapping(mapping, previous, entries):
    if type(mapping) is not list or len(mapping) != len(previous):
        raise cases.CaseConflict("search_dictionary_mapping_required")
    old, new = {row["key"]: row for row in previous}, {row["key"]: row for row in entries}
    seen, merges = set(), {}
    for row in mapping:
        if type(row) is not dict or set(row) != {"from", "kind", "to", "reason"}:
            raise cases.CaseConflict("search_dictionary_mapping_invalid")
        source, kind, targets = row["from"], row["kind"], row["to"]
        _text(row["reason"], 500)
        if (
            type(source) is not str
            or source not in old
            or source in seen
            or type(kind) is not str
            or kind not in MAPPING_KINDS
            or type(targets) is not list
            or any(type(target) is not str for target in targets)
            or len(set(targets)) != len(targets)
            or not set(targets) <= new.keys()
        ):
            raise cases.CaseConflict("search_dictionary_mapping_invalid")
        if (
            (kind == "NO_EQUIVALENT" and targets)
            or (kind == "SPLIT" and not 2 <= len(targets) <= 12)
            or (kind not in {"NO_EQUIVALENT", "SPLIT"} and len(targets) != 1)
        ):
            raise cases.CaseConflict("search_dictionary_mapping_cardinality")
        if kind == "SAME" and (targets != [source] or old[source]["term"] != new[source]["term"]):
            raise cases.CaseConflict("search_dictionary_same_identity_changed")
        if kind == "MERGED":
            merges[targets[0]] = merges.get(targets[0], 0) + 1
        seen.add(source)
    if any(count < 2 for count in merges.values()) or seen != old.keys():
        raise cases.CaseConflict("search_dictionary_mapping_incomplete")
    return mapping


def _case(context, base):
    return context.cases[str(base["case_id"])]


def _versions(case, expected_revision, expected_evidence_version):
    cases._versions(case, expected_revision, expected_evidence_version)


def _identity(context, case, request_key):
    return dict(
        case=case,
        case_revision=case.revision,
        evidence_version=case.evidence_version,
        provider_id=context.provider.provider_id,
        subject_id=context.actor.subject_id,
        auth_epoch=context.actor.auth_epoch,
        request_key=cases._uuid(request_key),
    )


def _save(context, row):
    services._seal(row)
    context.governance.wrote(row)
    return row


def _replay(model, context, case, request_key):
    row = model.objects.filter(
        case=case,
        provider_id=context.provider.provider_id,
        subject_id=context.actor.subject_id,
        request_key=cases._uuid(request_key),
    ).first()
    if row:
        services._verify(row)
    return row


def _revision(context, case, identifier):
    row = SynonymRevision.objects.filter(pk=cases._uuid(identifier), case=case).first()
    if row is None:
        raise cases.CaseConflict("search_dictionary_unavailable")
    services._verify(row)
    validate_entries(row.entries)
    return row


def _decision(revision):
    rows = list(SynonymDecision.objects.filter(revision=revision).order_by("sequence"))
    for number, row in enumerate(rows, 1):
        services._verify(row)
        if row.sequence != number:
            raise cases.CaseConflict("search_dictionary_decision_history")
    return rows[-1] if rows else None


def _approved(context, revision):
    decision = _decision(revision)
    if (
        decision is None
        or decision.action != "APPROVE"
        or decision.valid_until is None
        or timezone.now() >= decision.valid_until
    ):
        raise cases.CaseConflict("search_dictionary_not_currently_approved")
    context.governance.deadlines.append(decision.valid_until)
    return decision


def _source_pin(context, case):
    generation, usable, status = services._case_data(context, case)
    if status["state"] != "CURRENT":
        raise cases.CaseConflict("search_governance_current_index_required")
    return {
        "case_id": str(case.pk),
        "generation_id": str(generation.pk),
        "generation_digest": generation.digest,
        "source_fingerprint": generation.source_fingerprint,
        "allowed_fingerprint": digest(
            [(key, source.pin) for key, source in sorted(usable.items())]
        ),
    }


def _expansions(revision):
    return {
        normalize(row["term"]): tuple(normalize(value) for value in row["alternatives"])
        for row in revision.entries
    }


def _summary(result):
    return {
        "total": result["total"],
        "limited": result["limited"],
        "window": services.PAGE_SIZE,
        "rows": [
            {key: row[key] for key in ("document_id", "generation_id", "case_id", "kind", "pin")}
            for row in result["results"]
        ],
    }


def _difference(baseline, candidate):
    before = [row["document_id"] for row in baseline["rows"]]
    after = [row["document_id"] for row in candidate["rows"]]
    return {
        "added": [value for value in after if value not in before],
        "removed": [value for value in before if value not in after],
        "baseline_order": before,
        "candidate_order": after,
        "window": services.PAGE_SIZE,
    }


def _candidate(context, revision, value, *, page=1):
    return services.search_in_context(
        context, value=value, mode="FTS", page=page, expansions=_expansions(revision)
    )


def _dictionary(row, decision):
    state = "DRAFT" if decision is None else decision.action
    if state == "APPROVE" and timezone.now() >= decision.valid_until:
        state = "EXPIRED"
    return {
        "id": str(row.pk),
        "number": row.number,
        "digest": row.digest,
        "title": row.title,
        "provenance": row.provenance,
        "entries": row.entries,
        "mapping": row.mapping,
        "previous_id": str(row.previous_id) if row.previous_id else "",
        "author": row.subject_id,
        "provider": row.provider_id,
        "profile": row.profile,
        "state": state,
        "decision_sequence": decision.sequence if decision else 0,
        "reviewer": decision.subject_id if decision else "",
        "valid_until": decision.valid_until if decision else None,
    }


def desk_in_context(context, *, case_id):
    governance_pins.enabled()
    case = context.cases[str(case_id)]
    context.require(case, "DICTIONARY_READ")
    rows = list(SynonymRevision.objects.filter(case=case).order_by("-number"))
    result = []
    for row in rows:
        services._verify(row)
        decision = _decision(row)
        if decision and decision.action == "APPROVE" and timezone.now() < decision.valid_until:
            context.governance.deadlines.append(decision.valid_until)
        result.append(_dictionary(row, decision))
        latest_preview = (
            SynonymPreview.objects.filter(revision=row).order_by("-created_at", "-pk").first()
        )
        if latest_preview:
            services._verify(latest_preview)
        result[-1]["latest_preview_id"] = str(latest_preview.pk) if latest_preview else ""
    return {
        "case_ref": case.public_ref,
        "revision": case.revision,
        "evidence_version": case.evidence_version,
        "number": rows[0].number if rows else 0,
        "dictionaries": result,
        "index": services.desk_in_context(context, case_id=case_id),
    }


@mutation_service
def desk(**base):
    with policy.boundary(**base, action="DICTIONARY_READ") as context:
        return desk_in_context(context, case_id=base["case_id"])


@mutation_service
def create_revision(
    *,
    title,
    provenance,
    entries,
    mapping,
    expected_number,
    expected_revision,
    expected_evidence_version,
    request_key,
    **base,
):
    _text(title, 160)
    _text(provenance, 1000)
    validate_entries(entries)
    with policy.boundary(**base, action="DICTIONARY_EDIT") as context:
        case = _case(context, base)
        _versions(case, expected_revision, expected_evidence_version)
        previous = SynonymRevision.objects.filter(case=case).order_by("-number").first()
        replay = _replay(SynonymRevision, context, case, request_key)
        if replay:
            if (
                replay.pk != previous.pk
                or replay.title != title
                or replay.provenance != provenance
                or replay.entries != entries
                or replay.mapping != mapping
            ):
                raise cases.CaseConflict("search_dictionary_request_conflict")
            return _dictionary(replay, _decision(replay))
        if type(expected_number) is not int or expected_number != (
            previous.number if previous else 0
        ):
            raise cases.CaseConflict("search_dictionary_version_changed")
        if expected_number >= MAX_REVISIONS:
            raise cases.CaseConflict("search_dictionary_history_bound")
        if previous:
            services._verify(previous)
        validate_mapping(mapping, previous.entries if previous else [], entries)
        current_keys = {row["key"] for row in previous.entries} if previous else set()
        historical = {
            item["key"]
            for data in SynonymRevision.objects.filter(case=case).values_list("entries", flat=True)
            for item in data
        }
        if ({row["key"] for row in entries} - current_keys) & historical:
            raise cases.CaseConflict("search_dictionary_historical_identifier_reused")
        row = _save(
            context,
            SynonymRevision(
                **_identity(context, case, request_key),
                number=expected_number + 1,
                previous=previous,
                title=title,
                provenance=provenance,
                profile=PROFILE,
                entries=entries,
                mapping=mapping,
            ),
        )
        return _dictionary(row, None)


@mutation_service
def prepare_preview(
    *, revision_id, queries, expected_revision, expected_evidence_version, request_key, **base
):
    if (
        type(queries) is not list
        or not 1 <= len(queries) <= 8
        or any(type(value) is not str for value in queries)
        or len(set(queries)) != len(queries)
    ):
        raise cases.CaseConflict("search_dictionary_preview_queries")
    for value in queries:
        query(value, "FTS")
    with policy.boundary(**base, action="DICTIONARY_EDIT") as context:
        case = _case(context, base)
        context.require(case, "SEARCH")
        _versions(case, expected_revision, expected_evidence_version)
        revision = _revision(context, case, revision_id)
        pin = _source_pin(context, case)
        replay = _replay(SynonymPreview, context, case, request_key)
        if replay:
            if (
                replay.revision_id != revision.pk
                or replay.queries != queries
                or replay.source_pin != pin
            ):
                raise cases.CaseConflict("search_preview_request_conflict")
            return preview_in_context(context, case=case, preview_id=replay.pk)
        if SynonymPreview.objects.filter(revision=revision).count() >= MAX_PREVIEWS:
            raise cases.CaseConflict("search_preview_history_bound")
        impact = []
        for value in queries:
            baseline = _summary(services.search_in_context(context, value=value, mode="FTS"))
            candidate = _summary(_candidate(context, revision, value))
            impact.append(
                {
                    "query": value,
                    "baseline": baseline,
                    "candidate": candidate,
                    "difference": _difference(baseline, candidate),
                }
            )
        row = _save(
            context,
            SynonymPreview(
                **_identity(context, case, request_key),
                revision=revision,
                source_pin=pin,
                queries=queries,
                impact=impact,
            ),
        )
        return preview_in_context(context, case=case, preview_id=row.pk)


def preview_in_context(context, *, case, preview_id):
    context.require(case, "DICTIONARY_READ")
    context.require(case, "SEARCH")
    row = (
        SynonymPreview.objects.select_related("revision")
        .filter(pk=cases._uuid(preview_id), case=case)
        .first()
    )
    if row is None:
        raise cases.CaseConflict("search_preview_unavailable")
    services._verify(row)
    services._verify(row.revision)
    if row.source_pin != _source_pin(context, case):
        raise cases.CaseConflict("search_preview_stale")
    return {
        "id": str(row.pk),
        "digest": row.digest,
        "revision_id": str(row.revision_id),
        "dictionary_number": row.revision.number,
        "impact": row.impact,
        "source_pin": row.source_pin,
        "author": row.subject_id,
        "provider": row.provider_id,
    }


@mutation_service
def decide(
    *,
    revision_id,
    preview_id,
    action,
    note,
    ttl_minutes,
    expected_sequence,
    expected_revision,
    expected_evidence_version,
    request_key,
    confirmed=False,
    **base,
):
    _text(note, 2000)
    if confirmed is not True or action not in {"APPROVE", "REJECT", "RETIRE"}:
        raise cases.CaseConflict("search_dictionary_human_review_required")
    if (
        type(ttl_minutes) is not int
        or not 0 <= ttl_minutes <= 1440
        or (action == "APPROVE" and ttl_minutes < 1)
        or (action != "APPROVE" and ttl_minutes != 0)
    ):
        raise cases.CaseConflict("search_dictionary_expiry_invalid")
    with policy.boundary(**base, action="DICTIONARY_REVIEW") as context:
        case = _case(context, base)
        _versions(case, expected_revision, expected_evidence_version)
        revision = _revision(context, case, revision_id)
        latest = _decision(revision)
        replay = _replay(SynonymDecision, context, case, request_key)
        if replay:
            if (
                latest.pk != replay.pk
                or replay.revision_id != revision.pk
                or replay.action != action
                or replay.note != note
                or replay.ttl_minutes != ttl_minutes
                or str(replay.preview_id or "") != str(preview_id or "")
            ):
                raise cases.CaseConflict("search_dictionary_decision_conflict")
            return _dictionary(revision, replay)
        if type(expected_sequence) is not int or expected_sequence != (
            latest.sequence if latest else 0
        ):
            raise cases.CaseConflict("search_dictionary_review_changed")
        preview = None
        if action == "RETIRE":
            if latest is None or latest.action != "APPROVE" or preview_id:
                raise cases.CaseConflict("search_dictionary_retirement_invalid")
        else:
            if latest is not None:
                raise cases.CaseConflict("search_dictionary_already_reviewed")
            preview_data = preview_in_context(context, case=case, preview_id=preview_id)
            preview = SynonymPreview.objects.get(pk=preview_data["id"])
            if preview.revision_id != revision.pk:
                raise cases.CaseConflict("search_dictionary_preview_mismatch")
            actor = (context.provider.provider_id, context.actor.subject_id)
            if actor in {
                (revision.provider_id, revision.subject_id),
                (preview.provider_id, preview.subject_id),
            }:
                raise cases.CaseConflict("search_dictionary_independent_review_required")
        row = _save(
            context,
            SynonymDecision(
                **_identity(context, case, request_key),
                revision=revision,
                preview=preview,
                sequence=expected_sequence + 1,
                action=action,
                note=note,
                ttl_minutes=ttl_minutes,
                valid_until=timezone.now() + timedelta(minutes=ttl_minutes)
                if action == "APPROVE"
                else None,
            ),
        )
        return _dictionary(revision, row)


def search_in_context(context, *, case, revision_id, value, page=1):
    context.require(case, "DICTIONARY_USE")
    context.require(case, "SEARCH")
    revision = _revision(context, case, revision_id)
    approval = _approved(context, revision)
    _source_pin(context, case)
    result = _candidate(context, revision, value, page=page)
    result["dictionary"] = {
        "id": str(revision.pk),
        "digest": revision.digest,
        "number": revision.number,
        "title": revision.title,
        "provenance": revision.provenance,
        "approval_id": str(approval.pk),
        "approval_digest": approval.digest,
        "reviewer": approval.subject_id,
        "reviewed_at": approval.created_at,
        "valid_until": approval.valid_until,
    }
    _, tokens = query(value, "FTS")
    result["expanded_terms"] = [
        {"typed_token": token, "alternatives": list(_expansions(revision)[token])}
        for token in tokens
        if token in _expansions(revision)
    ]
    return result


@mutation_service
def search(*, revision_id, value, page=1, **base):
    with policy.boundary(**base, action="DICTIONARY_USE") as context:
        return search_in_context(
            context, case=_case(context, base), revision_id=revision_id, value=value, page=page
        )


@mutation_service
def run_shadow(
    *, revision_id, value, expected_revision, expected_evidence_version, request_key, **base
):
    with policy.boundary(**base, action="SHADOW") as context:
        return run_shadow_in_context(
            context,
            case=_case(context, base),
            revision_id=revision_id,
            value=value,
            expected_revision=expected_revision,
            expected_evidence_version=expected_evidence_version,
            request_key=request_key,
        )


def run_shadow_in_context(
    context, *, case, revision_id, value, expected_revision, expected_evidence_version, request_key
):
    """The same retrieval receipt, composed inside a caller's current-source boundary."""
    query(value, "FTS")
    context.require(case, "SHADOW")
    context.require(case, "SEARCH")
    context.require(case, "DICTIONARY_USE")
    _versions(case, expected_revision, expected_evidence_version)
    revision = _revision(context, case, revision_id)
    approval = _approved(context, revision)
    pin = _source_pin(context, case)
    replay = _replay(ShadowComparison, context, case, request_key)
    if replay:
        if (
            replay.query != value
            or replay.revision_id != revision.pk
            or replay.approval_id != approval.pk
            or replay.source_pin != pin
        ):
            raise cases.CaseConflict("search_shadow_request_conflict")
        baseline = services.search_in_context(context, value=value, mode="FTS")
        if _summary(baseline) != replay.baseline:
            raise cases.CaseConflict("search_shadow_baseline_changed")
        return {
            "result": baseline,
            "comparison": shadow_in_context(context, case=case, comparison_id=replay.pk),
        }
    if ShadowComparison.objects.filter(case=case).count() >= MAX_SHADOWS:
        raise cases.CaseConflict("search_shadow_history_bound")
    started = perf_counter_ns()
    baseline = services.search_in_context(context, value=value, mode="FTS")
    baseline_ms = max(0, (perf_counter_ns() - started) // 1_000_000)
    started = perf_counter_ns()
    status, candidate, difference = "OK", {}, {}
    try:
        with transaction.atomic():
            candidate = _summary(_candidate(context, revision, value))
    except DatabaseError:
        # A candidate SQL failure is observational. The real baseline was
        # already obtained; permission/source changes still fail at finish.
        status = "ERROR"
    candidate_ms = max(0, (perf_counter_ns() - started) // 1_000_000)
    summary = _summary(baseline)
    if status == "OK":
        difference = _difference(summary, candidate)
    row = _save(
        context,
        ShadowComparison(
            **_identity(context, case, request_key),
            revision=revision,
            approval=approval,
            source_pin=pin,
            query=value,
            baseline_profile=PROFILE,
            candidate_profile=f"{PROFILE}:{revision.digest}",
            baseline=summary,
            candidate=candidate,
            difference=difference,
            candidate_status=status,
            baseline_ms=baseline_ms,
            candidate_ms=candidate_ms,
        ),
    )
    return {
        "result": baseline,
        "comparison": shadow_in_context(context, case=case, comparison_id=row.pk),
    }


def shadow_in_context(context, *, case, comparison_id):
    context.require(case, "SHADOW_READ")
    context.require(case, "SEARCH")
    context.require(case, "DICTIONARY_USE")
    row = (
        ShadowComparison.objects.select_related("revision", "approval")
        .filter(pk=cases._uuid(comparison_id), case=case)
        .first()
    )
    if row is None:
        raise cases.CaseConflict("search_shadow_unavailable")
    for record in (row, row.revision, row.approval):
        services._verify(record)
    if _approved(context, row.revision).pk != row.approval_id or row.source_pin != _source_pin(
        context, case
    ):
        raise cases.CaseConflict("search_shadow_stale")
    return {
        "id": str(row.pk),
        "digest": row.digest,
        "query": row.query,
        "dictionary_id": str(row.revision_id),
        "dictionary_digest": row.revision.digest,
        "source_pin": row.source_pin,
        "baseline_profile": row.baseline_profile,
        "candidate_profile": row.candidate_profile,
        "baseline": row.baseline,
        "candidate": row.candidate,
        "difference": row.difference,
        "candidate_status": row.candidate_status,
        "baseline_ms": row.baseline_ms,
        "candidate_ms": row.candidate_ms,
        "created_at": row.created_at,
        "baseline_retained": True,
        "promotion_performed": False,
    }


@mutation_service
def read_shadow(*, comparison_id, **base):
    with policy.boundary(**base, action="SHADOW_READ") as context:
        return shadow_in_context(context, case=_case(context, base), comparison_id=comparison_id)


def shadow_history_in_context(context, *, case):
    context.require(case, "SHADOW_READ")
    context.require(case, "SEARCH")
    context.require(case, "DICTIONARY_USE")
    rows = list(
        ShadowComparison.objects.select_related("revision", "approval")
        .filter(case=case)
        .order_by("-created_at", "-pk")
    )
    if not rows:
        return []
    _, _, index_status = services._case_data(context, case)
    if index_status["state"] != "CURRENT":
        return []
    pin = _source_pin(context, case)
    result = []
    for row in rows:
        for record in (row, row.revision, row.approval):
            services._verify(record)
        current = _decision(row.revision)
        if (
            row.source_pin != pin
            or current is None
            or current.pk != row.approval_id
            or current.action != "APPROVE"
            or timezone.now() >= current.valid_until
        ):
            continue
        context.governance.deadlines.append(current.valid_until)
        result.append(
            {
                "id": str(row.pk),
                "query": row.query,
                "created_at": row.created_at,
                "candidate_status": row.candidate_status,
                "digest": row.digest,
            }
        )
    return result
