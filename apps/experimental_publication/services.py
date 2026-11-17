"""Closed editorial publication workflow over the canonical approved case answer."""

import json
import os
from hashlib import sha256

from django.apps import apps
from django.conf import settings

from apps.casework import services as cases
from apps.editorial_search.query_terms import normalize_editorial_search
from apps.platform_recovery.integration import mutation_service

from .authority import PublicationAuthority
from .models import PublicationAction, PublicationEdition


def _enabled():
    if (
        os.environ.get("FATWA_PRODUCTION") != "0"
        or getattr(settings, "FATWA_EXPERIMENTAL_PUBLICATION_ENABLED", False) is not True
    ):
        raise cases.CaseConflict("experimental_publication_disabled")


def _authority(identity, provider, case, action):
    authority = getattr(settings, "FATWA_EXPERIMENTAL_PUBLICATION_AUTHORITY", None)
    if not isinstance(authority, PublicationAuthority):
        raise cases.CaseConflict("publication_authority_required")
    try:
        allowed = authority.permits(
            provider_id=provider.provider_id,
            subject_id=identity.subject_id,
            auth_epoch=identity.auth_epoch,
            case_ref=case.public_ref,
            action=action,
        )
    except Exception as exc:
        raise cases.CaseConflict("publication_authority_unavailable") from exc
    if allowed is not True:
        raise cases.CaseConflict("publication_action_denied")


def _approved(case, edition=None):
    if case.stage != "ANSWERED" or not case.approved_answer_id:
        raise cases.CaseConflict("current_approval_required")
    answer = case.answers.get(pk=case.approved_answer_id)
    decision = answer.decision
    if (
        answer.evidence_version != case.evidence_version
        or decision.action != "APPROVE"
        or decision.evidence_version != case.evidence_version
        or (
            edition is not None
            and (
                edition.answer_id != answer.pk
                or edition.decision_id != decision.pk
                or edition.evidence_version != case.evidence_version
            )
        )
    ):
        raise cases.CaseConflict("publication_source_changed")
    return answer, decision


def _digest(title, category, body, citations):
    return sha256(
        json.dumps(
            [title, category, body, citations],
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode()
    ).hexdigest()


def _verify(edition):
    if edition.content_sha256 != _digest(
        edition.title, edition.category, edition.body, edition.citations
    ):
        raise cases.CaseConflict("publication_content_changed")


def _citation_snapshot(answer):
    # The citation app supplies only source-pinned, human-verified references.
    # Without that optional app there is no free-form citation input fallback.
    if not apps.is_installed("apps.case_citations"):
        return []
    from apps.case_citations.services import citations_for_locked_answer

    return [
        {"source": item["source"], "source_sha256": item["source_sha256"]}
        for item in citations_for_locked_answer(answer)
    ]


def _projection(edition, *, editorial=False, rights_usage="READ"):
    _verify(edition)
    from apps.case_citations.services import _permits_source

    visible_citations = [
        item for item in edition.citations if _permits_source(edition.case, item, rights_usage)
    ]
    actions = set(edition.actions.values_list("action", flat=True))
    result = {
        "id": str(edition.pk),
        "number": edition.number,
        "title": edition.title,
        "category": edition.category,
        "body": edition.body,
        "citations": visible_citations,
        "state": "WITHDRAWN"
        if "WITHDRAW" in actions
        else (
            "PUBLISHED"
            if "APPROVE" in actions
            else ("REVIEWED" if "REVIEW" in actions else "CANDIDATE")
        ),
    }
    if editorial:
        result.update(
            source_answer_revision=edition.answer.revision,
            evidence_version=edition.evidence_version,
            content_sha256=edition.content_sha256,
        )
    # Deliberately no case reference, original question, actor, internal note or audit.
    return result


@mutation_service
def create_edition(
    *,
    case_id,
    subject_id,
    provider,
    expected_revision,
    expected_evidence_version,
    title,
    category,
    body,
    source_edition_id=None,
    synthetic_fixtures_only=False,
):
    _enabled()
    for value, maximum in ((title, 160), (category, 80), (body, cases.MAX_TEXT)):
        cases._text(value)
        if len(value) > maximum:
            raise cases.CaseConflict("publication_text_too_long")
    with cases._staff_case(
        case_id,
        subject_id,
        provider,
        synthetic_fixtures_only,
        expected_revision=expected_revision,
        expected_evidence_version=expected_evidence_version,
    ) as (case, identity):
        answer, decision = _approved(case)
        if source_edition_id is not None:
            _correction_source(case, source_edition_id)
        number = PublicationEdition.objects.filter(case=case).count() + 1
        if number > 64:
            raise cases.CaseConflict("publication_capacity")
        citations = _citation_snapshot(answer)
        edition = PublicationEdition.objects.create(
            case=case,
            answer=answer,
            decision=decision,
            number=number,
            evidence_version=case.evidence_version,
            title=title,
            category=category,
            body=body,
            citations=citations,
            content_sha256=_digest(title, category, body, citations),
            subject_id=identity.subject_id,
            provider_id=provider.provider_id,
            auth_epoch=identity.auth_epoch,
        )
        return _projection(edition, editorial=True)


@mutation_service
def act(
    *,
    case_id,
    edition_id,
    subject_id,
    provider,
    action,
    reviewed=False,
    synthetic_fixtures_only=False,
):
    _enabled()
    if action not in {"REVIEW", "APPROVE", "WITHDRAW"}:
        raise cases.CaseConflict("publication_action_invalid")
    with cases._staff_case(case_id, subject_id, provider, synthetic_fixtures_only) as (case, actor):
        edition = PublicationEdition.objects.filter(pk=cases._uuid(edition_id), case=case).first()
        if edition is None:
            raise cases.CaseConflict("publication_unavailable")
        _verify(edition)
        existing = set(edition.actions.values_list("action", flat=True))
        if action in existing or "WITHDRAW" in existing:
            raise cases.CaseConflict("publication_transition_invalid")
        if action == "WITHDRAW":
            _authority(actor, provider, case, action)
        else:
            answer, decision = _approved(case, edition)
            if edition.citations != _citation_snapshot(answer):
                raise cases.CaseConflict("publication_citation_source_changed")
            if edition.number != PublicationEdition.objects.filter(case=case).count():
                raise cases.CaseConflict("publication_edition_changed")
            if action == "REVIEW":
                if reviewed is not True or existing:
                    raise cases.CaseConflict("explicit_redaction_review_required")
            else:
                _authority(actor, provider, case, action)
                if existing != {"REVIEW"}:
                    raise cases.CaseConflict("redaction_review_required")
                reviewer = edition.actions.get(action="REVIEW")
                actors = {
                    (edition.provider_id, edition.subject_id),
                    (decision.provider_id, decision.subject_id),
                    (reviewer.provider_id, reviewer.subject_id),
                }
                if (provider.provider_id, actor.subject_id) in actors:
                    raise cases.CaseConflict("independent_publication_approver_required")
        current = cases._identity(provider, subject_id, case)
        if current.auth_epoch != actor.auth_epoch:
            raise cases.CaseConflict("publication_identity_changed")
        PublicationAction.objects.create(
            edition=edition,
            action=action,
            subject_id=actor.subject_id,
            provider_id=provider.provider_id,
            auth_epoch=actor.auth_epoch,
        )
        return _projection(edition, editorial=True)


def _permitted(identity, provider, case, action):
    """Presentation only; mutations still recheck the same explicit authority."""
    try:
        _authority(identity, provider, case, action)
    except cases.CaseConflict:
        return False
    return True


@mutation_service
def editorial_case(*, edition_id, subject_id, provider, synthetic_fixtures_only=False):
    """Resolve a library edition back to its desk without putting case data in library DTOs."""
    _enabled()
    cases._guard(synthetic_fixtures_only)
    edition = PublicationEdition.objects.filter(pk=cases._uuid(edition_id)).first()
    if edition is None:
        raise cases.CaseConflict("publication_unavailable")
    with cases._staff_case(edition.case_id, subject_id, provider, True) as (case, _):
        _verify(edition)
        return {"case_id": str(case.pk), "public_ref": case.public_ref}


@mutation_service
def desk(*, case_id, subject_id, provider, synthetic_fixtures_only=False):
    _enabled()
    with cases._staff_case(case_id, subject_id, provider, synthetic_fixtures_only) as (case, actor):
        current = None
        if case.approved_answer_id:
            answer, _ = _approved(case)
            current = {"text": answer.text, "revision": answer.revision}
        rows = list(
            PublicationEdition.objects.filter(case=case)
            .select_related("answer", "decision")
            .prefetch_related("actions")
            .order_by("-number")
        )
        latest_number = rows[0].number if rows else 0
        latest_published = next(
            (e for e in rows if any(a.action == "APPROVE" for a in e.actions.all())), None
        )
        grants = {
            action: _permitted(actor, provider, case, action) for action in ("APPROVE", "WITHDRAW")
        }
        editions = []
        for edition in rows:
            entry = _projection(edition, editorial=True)
            source_current = False
            try:
                answer, _ = _approved(case, edition)
                source_current = edition.citations == _citation_snapshot(answer)
            except cases.CaseConflict:
                pass
            actions = list(edition.actions.all())
            reviewer = next((a for a in actions if a.action == "REVIEW"), None)
            independent = (provider.provider_id, actor.subject_id) not in {
                (edition.provider_id, edition.subject_id),
                (edition.decision.provider_id, edition.decision.subject_id),
                (reviewer.provider_id, reviewer.subject_id) if reviewer else (None, None),
            }
            latest = edition.number == latest_number
            published = latest_published is not None and edition.pk == latest_published.pk
            state = entry["state"]
            entry.update(
                can_correct=source_current and published,
                can_review=source_current and latest and state == "CANDIDATE",
                can_approve=(
                    source_current
                    and latest
                    and state == "REVIEWED"
                    and grants["APPROVE"]
                    and independent
                ),
                can_withdraw=state != "WITHDRAWN" and grants["WITHDRAW"],
                visible=source_current and published and state == "PUBLISHED",
                created_at=edition.created_at,
                history=[
                    {
                        "label": {
                            "REVIEW": "مراجعة التحرير والخصوصية",
                            "APPROVE": "موافقة النشر المستقلة",
                            "WITHDRAW": "سحب النسخة",
                        }[a.action],
                        "created_at": a.created_at,
                    }
                    for a in sorted(actions, key=lambda a: (a.created_at, a.pk))
                ],
            )
            if state == "WITHDRAWN":
                entry["status_label"] = "مسحوبة من المكتبة"
                entry["next_step"] = "يبقى السجل محفوظًا؛ السحب لا يعيد نسخة أقدم إلى المكتبة."
            elif not source_current:
                entry["status_label"] = "متوقفة لتغيّر الجواب أو الوقائع أو المصدر"
                entry["next_step"] = "راجع القضية واعتماد جوابها الحالي قبل إعداد نسخة جديدة."
            elif state == "PUBLISHED":
                entry["status_label"] = (
                    "متاحة حاليًا في المكتبة المغلقة" if published else "استُبدلت بنسخة نشر أحدث"
                )
                entry["next_step"] = (
                    "يمكن فتح النسخة الحالية أو إعداد تصحيح مستقل."
                    if published
                    else "هذه نسخة محفوظة للتاريخ ولا تظهر في البحث."
                )
            elif not latest:
                entry["status_label"] = "مرشح سابق متوقف"
                entry["next_step"] = "تابع أحدث نسخة مرشحة؛ لا يمكن اعتماد هذا المرشح القديم."
            elif state == "CANDIDATE":
                entry["status_label"] = "مرشحة — تحتاج مراجعة التحرير والخصوصية"
                entry["next_step"] = "راجع النص والعنوان والتصنيف والإحالات ثم سجّل المراجعة."
            else:
                entry["status_label"] = "مراجعة — تنتظر موافقة نشر مستقلة"
                entry["next_step"] = (
                    "النسخة جاهزة لقرار النشر من هويتك المخوّلة."
                    if entry["can_approve"]
                    else "يلزم مخوّل نشر مستقل عن محرر النسخة ومراجعها ومعتمد الجواب؛ الصلاحية وحدها لا تلغي شرط الاستقلال."
                )
            editions.append(entry)
        if cases._identity(provider, subject_id, case).auth_epoch != actor.auth_epoch:
            raise cases.CaseConflict("publication_identity_changed")
        return {
            "public_ref": case.public_ref,
            "case_id": str(case.pk),
            "revision": case.revision,
            "evidence_version": case.evidence_version,
            "approved": current,
            "editions": editions,
            "visible_edition": next((e for e in editions if e["visible"]), None),
            "can_withdraw": grants["WITHDRAW"],
        }


def _correction_source(case, edition_id):
    source = (
        PublicationEdition.objects.filter(case=case, actions__action="APPROVE")
        .order_by("-number")
        .first()
    )
    if source is None or str(source.pk) != str(edition_id):
        raise cases.CaseConflict("publication_correction_source_changed")
    _approved(case, source)
    _verify(source)
    if source.citations != _citation_snapshot(source.answer):
        raise cases.CaseConflict("publication_correction_source_changed")
    return source


@mutation_service
def correction_draft(*, case_id, edition_id, subject_id, provider, synthetic_fixtures_only=False):
    """Prefill a new editorial candidate from an immutable current published edition."""
    _enabled()
    with cases._staff_case(case_id, subject_id, provider, synthetic_fixtures_only) as (case, _):
        source = _correction_source(case, edition_id)
        return {
            "source_edition_id": str(source.pk),
            "source_number": source.number,
            "title": source.title,
            "category": source.category,
            "body": source.body,
        }


@mutation_service
def library(*, subject_id, provider, query="", category="", synthetic_fixtures_only=False):
    _enabled()
    cases._text(query, optional=True)
    cases._text(category, optional=True)
    if len(query) > 80 or len(category) > 80:
        raise cases.CaseConflict("publication_query_too_long")
    query = normalize_editorial_search(query)
    category = normalize_editorial_search(category)
    scoped = cases.list_cases(
        subject_id=subject_id, provider=provider, synthetic_fixtures_only=synthetic_fixtures_only
    )
    output = []
    for row in scoped:
        with cases._staff_case(row["case_id"], subject_id, provider, True) as (case, _):
            # The most recently approved edition is authoritative; withdrawal never
            # resurrects an older publication. Unapproved candidates are never searched.
            edition = (
                PublicationEdition.objects.filter(case=case, actions__action="APPROVE")
                .order_by("-number")
                .first()
            )
            if edition is None or edition.actions.filter(action="WITHDRAW").exists():
                continue
            try:
                _approved(case, edition)
                _verify(edition)
                if edition.citations != _citation_snapshot(edition.answer):
                    continue
            except cases.CaseConflict:
                continue
            public = _projection(edition, rights_usage="PREVIEW_METADATA")
            haystack = normalize_editorial_search(
                " ".join((public["title"], public["category"], public["body"]))
            )
            if (not query or query in haystack) and (
                not category or normalize_editorial_search(public["category"]) == category
            ):
                output.append(public)
    return output
