"""Version-pinned reports over existing authorized readers; no content mutations."""

import os
from contextlib import contextmanager
from hashlib import sha256

from django.apps import apps
from django.conf import settings
from django.db.models import Q

from apps.case_citations.services import _projection_expiry_guard
from apps.casework import delivery
from apps.casework import services as cases
from apps.delivery_queue.services import _canonical, synthetic_queue_atomic
from apps.platform_recovery.integration import mutation_context, mutation_service

from .authority import ContentReportAuthority
from .models import ContentReport, ReportEvent

REASONS = {
    "BROKEN_LINK": "رابط لا يعمل",
    "BROKEN_MEDIA": "ملف أو تشغيل مرفق لا يعمل",
    "CONTENT_ERROR": "ملاحظة على المحتوى تحتاج مراجعة مختصة",
    "OTHER": "مشكلة أخرى",
}
STATES = {
    "OPEN": "مستلم للمراجعة",
    "IN_REVIEW": "قيد المراجعة البشرية",
    "RESOLVED": "أغلق بعد تسجيل الإجراء والتحقق",
    "DISMISSED": "أغلق مع تسجيل سبب عدم المتابعة",
}
KINDS = {"ANSWER", "ANSWER_PART", "PUBLICATION", "TRANSCRIPT"}
TARGET_KEYS = {
    "kind",
    "identifier",
    "version",
    "sha256",
    "answer_id",
    "answer_revision",
    "evidence_version",
    "manifest_sha256",
}
MAX_REPORTS = 128
MAX_EVENTS = 64


def enabled():
    if (
        os.environ.get("FATWA_PRODUCTION") != "0"
        or getattr(settings, "FATWA_CONTENT_REPORTS_ENABLED", False) is not True
    ):
        raise cases.CaseConflict("content_reports_disabled")


def _digest(value):
    return sha256(_canonical(value)).hexdigest()


def _note(value, *, optional=False):
    cases._text(value, optional=optional)
    if len(value) > 2000:
        raise cases.CaseConflict("report_note_too_long")
    return value


def _key(value):
    return cases._uuid(value)


def _authority(actor, provider, case, action, kind):
    authority = getattr(settings, "FATWA_CONTENT_REPORTS_AUTHORITY", None)
    if not isinstance(authority, ContentReportAuthority):
        raise cases.CaseConflict("report_authority_required")
    try:
        permitted = authority.permits(
            provider_id=provider.provider_id,
            subject_id=actor.subject_id,
            auth_epoch=actor.auth_epoch,
            case_ref=case.public_ref,
            action=action,
            target_kind=kind,
        )
    except Exception as exc:
        raise cases.CaseConflict("report_authority_unavailable") from exc
    if permitted is not True:
        raise cases.CaseConflict("report_action_denied")


def _recheck(case, actor, provider, action, kind):
    fresh = cases._identity(provider, actor.subject_id, case)
    if (fresh.auth_epoch, fresh.role, fresh.case_keys) != (
        actor.auth_epoch,
        actor.role,
        actor.case_keys,
    ):
        raise cases.CaseConflict("report_identity_changed")
    _authority(fresh, provider, case, action, kind)


def _policy_epoch(policy):
    try:
        epoch = policy.projection_epoch()
    except Exception as exc:
        raise cases.CaseConflict("report_policy_snapshot_required") from exc
    if type(epoch) is not str or not epoch or len(epoch) > 1000:
        raise cases.CaseConflict("report_policy_snapshot_required")
    return epoch


def _report_policy():
    authority = getattr(settings, "FATWA_CONTENT_REPORTS_AUTHORITY", None)
    if not isinstance(authority, ContentReportAuthority):
        raise cases.CaseConflict("report_authority_required")
    return authority, _policy_epoch(authority)


def _source_state(case, kind):
    """Snapshot external policy generations plus locked canonical source evidence.

    Epoch reads are a side-effect-free integration contract. The final database
    snapshot runs after every permission and identity callback; no reader is
    reopened after it. Case locks alone cannot cover an external policy change.
    """
    if kind is None:
        return None
    if kind not in {"PUBLICATION", "TRANSCRIPT"}:
        raise cases.CaseConflict("report_staff_target_invalid")
    configuration = tuple(
        (name, getattr(settings, name, None))
        for name in (
            "FATWA_EXPERIMENTAL_PUBLICATION_ENABLED",
            "FATWA_RESEARCH_WORKSPACE_ENABLED",
            "FATWA_KNOWLEDGE_LINKS_ENABLED",
            "FATWA_SOURCE_RIGHTS_ENFORCED",
            "FATWA_SOURCE_RIGHTS_ENABLED",
            "FATWA_SOURCE_RIGHTS_AUTHORITY",
        )
    )
    policies = []
    if kind == "TRANSCRIPT":
        from apps.knowledge_links.authority import KnowledgeAuthority
        from apps.research_workspace.reference_batch import _epoch
        from apps.research_workspace.rights import ResearchRights

        research = getattr(settings, "FATWA_RESEARCH_WORKSPACE_RIGHTS", None)
        knowledge = getattr(settings, "FATWA_KNOWLEDGE_LINKS_AUTHORITY", None)
        if not isinstance(research, ResearchRights) or not isinstance(
            knowledge, KnowledgeAuthority
        ):
            raise cases.CaseConflict("report_source_policy_required")
        policies = [(research, _epoch(research)), (knowledge, _policy_epoch(knowledge))]
    ledger = []
    if apps.is_installed("apps.source_rights"):
        from apps.source_rights.models import (
            RightsAction,
            RightsRevision,
            SourceRegistration,
            SourceVersion,
        )

        registrations = list(SourceRegistration.objects.filter(case=case).order_by("pk").values())
        revisions = list(RightsRevision.objects.filter(case=case).order_by("pk").values())
        actions = list(RightsAction.objects.filter(revision__case=case).order_by("pk").values())
        versions = list(
            SourceVersion.objects.filter(pk__in=[row["source_id"] for row in registrations])
            .order_by("pk")
            .values()
        )
        ledger = [registrations, revisions, actions, versions]
    editions = []
    if kind == "PUBLICATION":
        from apps.experimental_publication.models import PublicationAction, PublicationEdition

        editions = [
            list(
                PublicationEdition.objects.filter(case=case)
                .order_by("pk")
                .values(
                    "id", "number", "answer_id", "decision_id", "evidence_version", "content_sha256"
                )
            ),
            list(PublicationAction.objects.filter(edition__case=case).order_by("pk").values()),
        ]
    canonical = (
        type(case)
        .objects.filter(pk=case.pk)
        .values_list(
            "revision", "evidence_version", "answer_revision", "approved_answer_id", "stage"
        )
        .get()
    )
    return {
        "configuration": configuration,
        "policies": policies,
        "ledger": ledger,
        "editions": editions,
        "canonical": canonical,
    }


@mutation_context
@contextmanager
def staff_projection_boundary(
    *, case_id, subject_id, provider, source_kind=None, synthetic_fixtures_only=False
):
    """Keep report/source authorization valid through complete projection or render."""
    enabled()
    provider_id = getattr(provider, "provider_id", None)
    with (
        synthetic_queue_atomic(),
        cases._staff_case(case_id, subject_id, provider, synthetic_fixtures_only) as (case, actor),
        _projection_expiry_guard(),
    ):
        report_policy = _report_policy()
        source = _source_state(case, source_kind)
        yield
        enabled()
        fresh = cases._identity(provider, subject_id, case)
        if provider.provider_id != provider_id or (
            fresh.subject_id,
            fresh.role,
            fresh.active,
            fresh.case_keys,
            fresh.auth_epoch,
        ) != (actor.subject_id, actor.role, actor.active, actor.case_keys, actor.auth_epoch):
            raise cases.CaseConflict("report_identity_changed")
        current_policy = _report_policy()
        if current_policy[0] is not report_policy[0] or current_policy[1] != report_policy[1]:
            raise cases.CaseConflict("report_policy_changed")
        if _source_state(case, source_kind) != source:
            raise cases.CaseConflict("report_source_policy_changed")


def _validate_target(target):
    if type(target) is not dict or set(target) != TARGET_KEYS or target["kind"] not in KINDS:
        raise cases.CaseConflict("report_target_invalid")
    _key(target["identifier"])
    for name in ("version", "evidence_version"):
        if type(target[name]) is not int or not 1 <= target[name] <= 256:
            raise cases.CaseConflict("report_target_invalid")
    if type(target["sha256"]) is not str or len(target["sha256"]) != 64:
        raise cases.CaseConflict("report_target_invalid")
    if any(c not in "0123456789abcdef" for c in target["sha256"]):
        raise cases.CaseConflict("report_target_invalid")
    if target["kind"] == "TRANSCRIPT":
        if target["answer_id"] or target["answer_revision"] != 0 or target["manifest_sha256"]:
            raise cases.CaseConflict("report_target_invalid")
    else:
        _key(target["answer_id"])
        if type(target["answer_revision"]) is not int or not 1 <= target["answer_revision"] <= 256:
            raise cases.CaseConflict("report_target_invalid")
        manifest = target["manifest_sha256"]
        if type(manifest) is not str or (
            manifest and (len(manifest) != 64 or any(c not in "0123456789abcdef" for c in manifest))
        ):
            raise cases.CaseConflict("report_target_invalid")
    return target


def target_key(target):
    return f"{target['kind']}:{target['identifier']}:{_digest(target)}"


def _private_targets(case, token):
    # Reuse the actual portal release reader, including signed legacy delivery.
    # No report receipt, approval flag or guessed identifier grants answer access.
    from apps.answer_media import services as media
    from apps.answer_media.models import AnswerManifest
    from apps.requester_portal.services import snapshot

    visible = snapshot(token=token, synthetic_fixtures_only=True)
    if visible["answer"] is None:
        return []
    case.refresh_from_db()
    answer = case.approved_answer
    if answer is None or answer.revision != visible["answer"]["revision"]:
        raise cases.CaseConflict("report_answer_changed")
    manifest = AnswerManifest.objects.filter(answer=answer).first()
    if manifest is not None:
        manifest = media._requester_manifest(case)
    common = dict(
        answer_id=str(answer.pk),
        answer_revision=answer.revision,
        evidence_version=case.evidence_version,
        manifest_sha256=manifest.sha256 if manifest else "",
    )
    rows = [
        {
            "target": dict(
                kind="ANSWER",
                identifier=str(answer.pk),
                version=answer.revision,
                sha256=cases._digest(answer.text),
                **common,
            ),
            "label": f"نص الجواب، الإصدار {answer.revision}",
        }
    ]
    if manifest is not None:
        for part in media._verified(manifest):
            if part.ordinal > 1:
                rows.append(
                    {
                        "target": dict(
                            kind="ANSWER_PART",
                            identifier=str(part.pk),
                            version=answer.revision,
                            sha256=part.sha256,
                            **common,
                        ),
                        "label": f"جزء الجواب {part.ordinal}: {part.filename}",
                    }
                )
    return rows


def _staff_target(case, actor, provider, kind, identifier):
    if kind == "PUBLICATION":
        from apps.experimental_publication import services as publication
        from apps.experimental_publication.models import PublicationEdition

        publication._enabled()
        edition = (
            PublicationEdition.objects.filter(case=case, actions__action="APPROVE")
            .select_related("answer", "decision")
            .order_by("-number")
            .first()
        )
        if (
            edition is None
            or str(edition.pk) != str(_key(identifier))
            or edition.actions.filter(action="WITHDRAW").exists()
        ):
            raise cases.CaseConflict("report_publication_unavailable")
        publication._approved(case, edition)
        publication._verify(edition)
        if edition.citations != publication._citation_snapshot(edition.answer):
            raise cases.CaseConflict("report_publication_changed")
        publication._projection(edition, rights_usage="PREVIEW_METADATA")
        publication._require_publication_sources(case, edition.citations)
        return dict(
            kind=kind,
            identifier=str(edition.pk),
            version=edition.number,
            sha256=edition.content_sha256,
            answer_id=str(edition.answer_id),
            answer_revision=edition.answer.revision,
            evidence_version=edition.evidence_version,
            manifest_sha256="",
        )
    if kind == "TRANSCRIPT":
        from apps.research_workspace import services as research
        from apps.transcript_case_links.models import TranscriptLink

        research._enabled()
        resource, _ = research._transcript(case, actor, provider, identifier, "READ_TEXT")
        research.open_resource(
            case_id=str(case.pk),
            subject_id=actor.subject_id,
            provider=provider,
            resource=resource,
            synthetic_fixtures_only=True,
        )
        link = TranscriptLink.objects.select_related("evidence").get(pk=resource.identifier)
        return dict(
            kind=kind,
            identifier=resource.identifier,
            version=link.evidence.version,
            sha256=resource.sha256,
            answer_id="",
            answer_revision=0,
            evidence_version=link.evidence.version,
            manifest_sha256="",
        )
    raise cases.CaseConflict("report_staff_target_invalid")


def _payload(row):
    return _digest(
        [
            str(row.case_id),
            row.case_revision,
            row.evidence_version,
            row.reporter_kind,
            row.reporter_binding,
            str(row.request_key),
            row.target,
            row.reason,
            row.description,
            row.evidence_note,
        ]
    )


def _verify(row):
    _validate_target(row.target)
    if row.target_sha256 != _digest(row.target) or row.payload_sha256 != _payload(row):
        raise cases.CaseConflict("report_history_inconsistent")
    events = list(row.events.order_by("sequence"))
    if not events or len(events) > MAX_EVENTS:
        raise cases.CaseConflict("report_history_inconsistent")
    state = None
    for index, event in enumerate(events, 1):
        if event.sequence != index:
            raise cases.CaseConflict("report_history_inconsistent")
        if index == 1:
            valid = (
                event.action == "SUBMIT"
                and event.state == "OPEN"
                and event.request_key == row.request_key
            )
        else:
            valid = _next_state(state, event.action) == event.state
        if not valid:
            raise cases.CaseConflict("report_history_inconsistent")
        state = event.state
    return events


def _next_state(state, action):
    if action == "START" and state == "OPEN":
        return "IN_REVIEW"
    if action in {"RESOLVE", "DISMISS"} and state == "IN_REVIEW":
        return "RESOLVED" if action == "RESOLVE" else "DISMISSED"
    if action == "REOPEN" and state in {"RESOLVED", "DISMISSED"}:
        return "OPEN"
    if action == "LINK" and state in STATES:
        return state
    raise cases.CaseConflict("report_transition_denied")


def _public(row, events=None):
    events = events or _verify(row)
    return {
        "id": str(row.pk),
        "state": events[-1].state,
        "state_label": STATES[events[-1].state],
        "revision": events[-1].sequence,
        "reason": REASONS[row.reason],
        "target_kind": row.target["kind"],
        "target_version": row.target["version"],
        "created_at": row.created_at,
        "content_changed": False,
    }


def _create(
    case,
    *,
    kind,
    binding,
    request_key,
    target,
    reason,
    description,
    evidence_note,
    actor=None,
    provider=None,
):
    if type(reason) is not str or reason not in REASONS:
        raise cases.CaseConflict("report_reason_invalid")
    _note(description)
    _note(evidence_note, optional=True)
    _validate_target(target)
    key = _key(request_key)
    candidate = ContentReport(
        case=case,
        case_revision=case.revision,
        evidence_version=case.evidence_version,
        reporter_kind=kind,
        reporter_binding=binding,
        request_key=key,
        target=target,
        target_sha256=_digest(target),
        reason=reason,
        description=description,
        evidence_note=evidence_note,
    )
    candidate.payload_sha256 = _payload(candidate)
    existing = ContentReport.objects.filter(
        case=case, reporter_binding=binding, request_key=key
    ).first()
    if existing is not None:
        if existing.payload_sha256 != candidate.payload_sha256:
            raise cases.CaseConflict("report_request_reused")
        return {**_public(existing), "created": False}
    if ContentReport.objects.filter(case=case).count() >= MAX_REPORTS:
        raise cases.CaseConflict("report_capacity")
    candidate.save(force_insert=True)
    ReportEvent.objects.create(
        report=candidate,
        sequence=1,
        request_key=key,
        action="SUBMIT",
        state="OPEN",
        subject_id=actor.subject_id if actor else "",
        provider_id=provider.provider_id if provider else "",
        auth_epoch=actor.auth_epoch if actor else "",
    )
    return {**_public(candidate), "created": True}


@mutation_service
def requester_context(*, token, expected_revision, synthetic_fixtures_only=False):
    enabled()
    with delivery._token_case(token, synthetic_fixtures_only) as case:
        cases._versions(case, expected_revision)
        targets = _private_targets(case, token)
        rows = [
            _public(row)
            for row in ContentReport.objects.filter(case=case, reporter_kind="REQUESTER").order_by(
                "-created_at"
            )[:MAX_REPORTS]
        ]
        # Revalidate capability and current release after composing the projection.
        with cases._token_case(token, True) as fresh:
            cases._versions(fresh, expected_revision)
            if targets != _private_targets(fresh, token):
                raise cases.CaseConflict("report_target_changed")
        return {
            "targets": [
                {"key": target_key(row["target"]), "label": row["label"]} for row in targets
            ],
            "reports": rows,
            "reasons": REASONS,
        }


@mutation_service
def submit_requester(
    *,
    token,
    expected_revision,
    selected_target,
    request_key,
    reason,
    description,
    evidence_note="",
    synthetic_fixtures_only=False,
):
    enabled()
    with delivery._token_case(token, synthetic_fixtures_only) as case:
        cases._versions(case, expected_revision)
        target = next(
            (
                r["target"]
                for r in _private_targets(case, token)
                if target_key(r["target"]) == selected_target
            ),
            None,
        )
        if target is None:
            raise cases.CaseConflict("report_target_unavailable")
        result = _create(
            case,
            kind="REQUESTER",
            binding=_digest(["REQUESTER", cases._digest(token)]),
            request_key=request_key,
            target=target,
            reason=reason,
            description=description,
            evidence_note=evidence_note,
        )
        with cases._token_case(token, True) as fresh:
            cases._versions(fresh, expected_revision)
            if target not in [row["target"] for row in _private_targets(fresh, token)]:
                raise cases.CaseConflict("report_target_changed")
        return result


@mutation_service
def prepare_staff_target(
    *, case_id, subject_id, provider, target_kind, target_id, synthetic_fixtures_only=False
):
    enabled()
    with (
        staff_projection_boundary(
            case_id=case_id,
            subject_id=subject_id,
            provider=provider,
            source_kind=target_kind,
            synthetic_fixtures_only=synthetic_fixtures_only,
        ),
        synthetic_queue_atomic(),
        cases._staff_case(case_id, subject_id, provider, synthetic_fixtures_only) as (case, actor),
        _projection_expiry_guard(),
    ):
        _authority(actor, provider, case, "SUBMIT", target_kind)
        target = _staff_target(case, actor, provider, target_kind, target_id)
        _recheck(case, actor, provider, "SUBMIT", target_kind)
        return {
            "target": target,
            "key": target_key(target),
            "public_ref": case.public_ref,
            "case_revision": case.revision,
            "evidence_version": case.evidence_version,
        }


@mutation_service
def submit_staff(
    *,
    case_id,
    subject_id,
    provider,
    target_kind,
    target_id,
    selected_target,
    expected_revision,
    expected_evidence_version,
    request_key,
    reason,
    description,
    evidence_note="",
    synthetic_fixtures_only=False,
):
    enabled()
    with (
        staff_projection_boundary(
            case_id=case_id,
            subject_id=subject_id,
            provider=provider,
            source_kind=target_kind,
            synthetic_fixtures_only=synthetic_fixtures_only,
        ),
        synthetic_queue_atomic(),
        cases._staff_case(
            case_id,
            subject_id,
            provider,
            synthetic_fixtures_only,
            expected_revision=expected_revision,
            expected_evidence_version=expected_evidence_version,
        ) as (case, actor),
        _projection_expiry_guard(),
    ):
        _authority(actor, provider, case, "SUBMIT", target_kind)
        target = _staff_target(case, actor, provider, target_kind, target_id)
        if selected_target != target_key(target):
            raise cases.CaseConflict("report_target_changed")
        result = _create(
            case,
            kind="STAFF",
            binding=_digest([provider.provider_id, subject_id, actor.auth_epoch]),
            request_key=request_key,
            target=target,
            reason=reason,
            description=description,
            evidence_note=evidence_note,
            actor=actor,
            provider=provider,
        )
        case.refresh_from_db()
        cases._versions(case, expected_revision, expected_evidence_version)
        if _staff_target(case, actor, provider, target_kind, target_id) != target:
            raise cases.CaseConflict("report_target_changed")
        _recheck(case, actor, provider, "SUBMIT", target_kind)
        return result


@mutation_service
def staff_desk(*, case_id, subject_id, provider, synthetic_fixtures_only=False):
    enabled()
    with (
        staff_projection_boundary(
            case_id=case_id,
            subject_id=subject_id,
            provider=provider,
            synthetic_fixtures_only=synthetic_fixtures_only,
        ),
        synthetic_queue_atomic(),
        cases._staff_case(case_id, subject_id, provider, synthetic_fixtures_only) as (case, actor),
    ):
        rows, kinds = [], set()
        for row in ContentReport.objects.filter(case=case).order_by("-created_at")[:MAX_REPORTS]:
            kind = row.target["kind"]
            _authority(actor, provider, case, "READ", kind)
            kinds.add(kind)
            events = _verify(row)
            rows.append(
                {
                    **_public(row, events),
                    "description": row.description,
                    "evidence_note": row.evidence_note,
                    "target": row.target,
                    "reporter_kind": row.reporter_kind,
                    "events": [
                        {
                            "sequence": event.sequence,
                            "action": event.action,
                            "state": STATES[event.state],
                            "action_note": event.action_note,
                            "verification_note": event.verification_note,
                            "related_report": str(event.related_report_id)
                            if event.related_report_id
                            else "",
                            "subject_id": event.subject_id,
                            "created_at": event.created_at,
                        }
                        for event in events
                    ],
                }
            )
        # Even an empty desk is an explicitly authorized staff operation.
        for kind in kinds or {"ANSWER"}:
            _recheck(case, actor, provider, "READ", kind)
        return {"public_ref": case.public_ref, "reports": rows, "reasons": REASONS}


@mutation_service
def advance(
    *,
    case_id,
    subject_id,
    provider,
    report_id,
    expected_revision,
    request_key,
    action,
    action_note,
    verification_note="",
    related_report_id="",
    synthetic_fixtures_only=False,
):
    enabled()
    _note(action_note)
    _note(verification_note, optional=action not in {"RESOLVE", "DISMISS"})
    if type(expected_revision) is not int or not 1 <= expected_revision <= MAX_EVENTS:
        raise cases.CaseConflict("report_revision_invalid")
    key = _key(request_key)
    with (
        staff_projection_boundary(
            case_id=case_id,
            subject_id=subject_id,
            provider=provider,
            synthetic_fixtures_only=synthetic_fixtures_only,
        ),
        synthetic_queue_atomic(),
        cases._staff_case(case_id, subject_id, provider, synthetic_fixtures_only) as (case, actor),
    ):
        row = ContentReport.objects.filter(pk=_key(report_id), case=case).first()
        if row is None:
            raise cases.CaseConflict("report_unavailable")
        permission = "LINK" if action == "LINK" else "TRIAGE"
        _authority(actor, provider, case, permission, row.target["kind"])
        events = _verify(row)
        related = None
        if action == "LINK":
            related = ContentReport.objects.filter(pk=_key(related_report_id), case=case).first()
            if related is None or related.pk == row.pk or related.target != row.target:
                raise cases.CaseConflict("report_link_invalid")
            _verify(related)
            _authority(actor, provider, case, "READ", related.target["kind"])
        elif related_report_id:
            raise cases.CaseConflict("report_link_invalid")
        repeated = next((event for event in events if event.request_key == key), None)
        values = (
            action,
            action_note,
            verification_note,
            related.pk if related else None,
            actor.subject_id,
            provider.provider_id,
            actor.auth_epoch,
        )
        if repeated is not None:
            if values != (
                repeated.action,
                repeated.action_note,
                repeated.verification_note,
                repeated.related_report_id,
                repeated.subject_id,
                repeated.provider_id,
                repeated.auth_epoch,
            ):
                raise cases.CaseConflict("report_request_reused")
            _recheck(case, actor, provider, permission, row.target["kind"])
            return {**_public(row, events), "created": False}
        if events[-1].sequence != expected_revision or len(events) >= MAX_EVENTS:
            raise cases.CaseConflict("report_changed")
        state = _next_state(events[-1].state, action)
        if (
            related is not None
            and ReportEvent.objects.filter(
                Q(report=row, related_report=related) | Q(report=related, related_report=row),
                action="LINK",
            ).exists()
        ):
            raise cases.CaseConflict("report_already_linked")
        ReportEvent.objects.create(
            report=row,
            sequence=len(events) + 1,
            request_key=key,
            action=action,
            state=state,
            action_note=action_note,
            verification_note=verification_note,
            related_report=related,
            subject_id=actor.subject_id,
            provider_id=provider.provider_id,
            auth_epoch=actor.auth_epoch,
        )
        _recheck(case, actor, provider, permission, row.target["kind"])
        return {**_public(row), "created": True}
