"""Inspect current authorized records without repairing content or grading scholarship."""

import os
from contextlib import contextmanager
from copy import deepcopy

from django.apps import apps
from django.conf import settings
from django.utils import timezone

from apps.case_citations.services import _projection_expiry_guard
from apps.casework import services as cases
from apps.casework.models import Case
from apps.data_privacy import integration as privacy
from apps.data_privacy.services import PrivacyDenied
from apps.delivery_queue.services import synthetic_queue_atomic
from apps.mufti_review.identity import IdentityUnavailable, resolve_identity
from apps.platform_recovery.integration import mutation_context, mutation_service

PAGE_SIZE = 8
STATES = {
    "OK": "لم يُكتشف خلل ضمن هذا الفحص",
    "TECHNICAL": "خلل تقني يحتاج معالجة",
    "REVIEW": "بلاغ يحتاج مراجعة بشرية",
    "NOT_CHECKED": "لم يكتمل هذا الفحص",
    "NOT_APPLICABLE": "غير مطلوب لهذه القضية",
}
TECHNICAL = {
    "case_tracking_mismatch",
    "case_source_inconsistent",
    "case_evidence_inconsistent",
    "case_answer_inconsistent",
    "case_history_inconsistent",
    "case_decision_history_inconsistent",
    "quality_attribution_inconsistent",
    "attachment_integrity_failed",
    "private_original_integrity_failed",
    "answer_manifest_invalid",
    "answer_manifest_inconsistent",
    "answer_media_integrity_failed",
    "answer_media_content_invalid",
    "answer_media_validation_changed",
    "answer_parts_inconsistent",
    "answer_text_inconsistent",
    "answer_media_metadata_inconsistent",
    "citation_snapshot_inconsistent",
    "citation_source_changed",
    "existing_verified_source_required",
    "transcript_binding_inconsistent",
    "timed_snapshot_changed",
    "timed_source_changed",
    "pdf_snapshot_changed",
    "pdf_source_changed",
}


def enabled():
    if (
        os.environ.get("FATWA_PRODUCTION") != "0"
        or getattr(settings, "FATWA_DATA_QUALITY_ENABLED", False) is not True
    ):
        raise cases.CaseConflict("data_quality_disabled")


def _actor(identity):
    return (
        identity.subject_id,
        identity.role,
        identity.active,
        identity.case_keys,
        identity.auth_epoch,
    )


def _check(code, title, state, detail):
    return {"code": code, "title": title, "state": state, "label": STATES[state], "detail": detail}


def _probe(code, title, callback, *, failure):
    try:
        callback()
    except cases.CaseConflict as exc:
        if str(exc) in TECHNICAL:
            return _check(code, title, "TECHNICAL", failure)
        # Rights withdrawal, a disabled feature or unavailable policy is not a
        # broken source. Never expose its identifier, title or exception text.
        return _check(
            code,
            title,
            "NOT_CHECKED",
            "الصلاحية الحالية أو خدمة التحقق لم تسمح بإكمال الفحص. لا يُستنتج أن المادة مفقودة.",
        )
    return _check(code, title, "OK", "اجتازت السجلات المتاحة الفحص المحدد في وقت هذه القراءة.")


def _attribution(case):
    for event in case.events.select_related("answer", "decision"):
        record = (
            event.answer
            if event.action == "SAVE_ANSWER"
            else event.decision
            if event.action in {"APPROVE", "RETURN_FOR_CHANGES"}
            else None
        )
        if event.answer_id:
            privacy.current("ANSWER", event.answer_id)
        if event.decision_id:
            privacy.current("ANSWER", event.decision.answer_id)
        if record is not None and (
            event.subject_id != record.subject_id
            or any(
                not cases._ref(value)
                for value in (record.subject_id, record.provider_id, record.auth_epoch)
            )
        ):
            raise cases.CaseConflict("quality_attribution_inconsistent")


def _attachments(case, common):
    from apps.case_attachments.services import staff_list

    staff_list(case_id=str(case.pk), **common)


def _answer_files(case, actor, common):
    from apps.answer_media.services import manifest_for_locked_answer

    answer = case.answers.order_by("-revision").first()
    if answer is not None:
        privacy.current("ANSWER", answer.pk)
        cases._answer_citations(answer)
        cases._answer_annotations(answer, actor=actor, provider=common["provider"])
        manifest_for_locked_answer(answer)


def _references(case, actor, common):
    from apps.case_citations.services import read_citations

    answer = case.answers.order_by("-revision").first()
    if answer is not None:
        privacy.current("ANSWER", answer.pk)
        read_citations(case_id=str(case.pk), answer_id=str(answer.pk), **common)
        cases._answer_annotations(answer, actor=actor, provider=common["provider"])


def _reports(case, common, report_policy):
    if (
        not apps.is_installed("apps.content_reports")
        or getattr(settings, "FATWA_CONTENT_REPORTS_ENABLED", False) is not True
    ):
        return _check(
            "reports", "بلاغات تنتظر مراجعة", "NOT_APPLICABLE", "مسار البلاغات غير مفعّل هنا."
        )
    from apps.content_reports.services import staff_desk

    try:
        # An optional reader without a usable initial version stays unchecked.
        # A later successful callback cannot make an unpinned count releasable.
        if report_policy is None or report_policy[2] is None:
            raise cases.CaseConflict("quality_report_policy_unavailable")
        rows = staff_desk(case_id=str(case.pk), **common)["reports"]
    except cases.CaseConflict:
        return _check(
            "reports",
            "بلاغات تنتظر مراجعة",
            "NOT_CHECKED",
            "تعذر فحص البلاغات ضمن الصلاحية الحالية.",
        )
    pending = sum(row["state"] in {"OPEN", "IN_REVIEW"} for row in rows)
    return _check(
        "reports",
        "بلاغات تنتظر مراجعة",
        "REVIEW" if pending else "OK",
        f"توجد {pending} بلاغات متاحة قيد المراجعة؛ وجود البلاغ لا يثبت خطأ المحتوى."
        if pending
        else "لا توجد بلاغات متاحة قيد المراجعة. هذا ليس تقييمًا لصحة المحتوى.",
    )


def _verify_available(case):
    # A diagnostic result is itself a projection of its original inputs. Do not
    # grade hidden answer/attachment integrity or infer that a withheld source
    # is broken. The generic incomplete check exposes no source identity/count.
    for identifier in case.answers.values_list("pk", flat=True):
        privacy.current("ANSWER", identifier)
    for evidence in case.evidence.all():
        if not privacy.evidence_allowed(evidence):
            raise PrivacyDenied("privacy_quality_source_unavailable")
    cases._verify(case)


def _inspect_case(case, actor, common, report_policy):
    integrity = _probe(
        "canonical",
        "الأصل والوقائع والإصدارات والسجل",
        lambda: _verify_available(case),
        failure="سجل مطلوب مفقود أو غير متسق مع إصدارات القضية وبصماتها؛ يحتاج إصلاحًا تشغيليًا مخوّلًا.",
    )
    checks = [integrity]
    if integrity["state"] == "OK":
        checks.append(
            _probe(
                "attribution",
                "نسبة الحفظ والاعتماد إلى صاحب الإجراء",
                lambda: _attribution(case),
                failure="تختلف هوية صاحب الحفظ أو القرار عن الحدث المرتبط به، أو تنقص بيانات النسبة المطلوبة.",
            )
        )
        for app, code, title, callback, failure in (
            (
                "apps.case_attachments",
                "attachments",
                "ملفات الوقائع المطلوبة",
                lambda: _attachments(case, common),
                "تعذر التحقق من أصل ملف مسجل أو من بصمته أو ارتباطه بالواقعة الأصلية.",
            ),
            (
                "apps.answer_media",
                "answer_files",
                "أجزاء أحدث جواب وملفاته",
                lambda: _answer_files(case, actor, common),
                "ملف مطلوب أو ترتيب أجزاء أو بصمة إصدار الجواب غير متسق. لم يُستبدل الأصل أو يُعدل الجواب.",
            ),
            (
                "apps.case_citations",
                "references",
                "مصادر أحدث جواب ومواضعه الدقيقة",
                lambda: _references(case, actor, common),
                "تعذر التحقق من النسخة أو الموضع المحفوظ لإحالة. لا يجوز استبدال المصدر تلقائيًا.",
            ),
        ):
            if apps.is_installed(app):
                checks.append(_probe(code, title, callback, failure=failure))
            else:
                checks.append(_check(code, title, "NOT_CHECKED", "الفاحص غير متاح في هذه البيئة."))
        checks.append(_reports(case, common, report_policy))
    return {
        "public_ref": case.public_ref,
        "revision": case.revision,
        "evidence_version": case.evidence_version,
        "checks": checks,
        "technical_count": sum(c["state"] == "TECHNICAL" for c in checks),
        "review_count": sum(c["state"] == "REVIEW" for c in checks),
        "unchecked_count": sum(c["state"] == "NOT_CHECKED" for c in checks),
    }


def _report_policy_pin():
    """Version only the optional report reader; never infer a usable grant.

    Source citations use the locked rights ledger. Actual timed/PDF annotation
    reads enroll their media policy and deadline in _answer_use_boundary, so an
    unused generic TOC projection contract must not disable this dashboard.
    """
    if (
        not apps.is_installed("apps.content_reports")
        or getattr(settings, "FATWA_CONTENT_REPORTS_ENABLED", False) is not True
    ):
        return None
    from apps.content_reports.services import _report_policy

    policy = getattr(settings, "FATWA_CONTENT_REPORTS_AUTHORITY", None)
    try:
        _, epoch = _report_policy()
    except cases.CaseConflict:
        epoch = None
    # Retain the object as well as its id: replacement cannot reuse that id or
    # be hidden by an authority's custom equality implementation.
    return id(policy), policy, epoch


def _configuration():
    """Pin the gates and adapter identities used by these diagnostic readers."""
    flags = []
    for name in (
        "FATWA_CONTENT_REPORTS_ENABLED",
        "FATWA_CASE_ATTACHMENTS_ENABLED",
        "FATWA_CASE_CITATIONS_ENABLED",
        "FATWA_ANSWER_MEDIA_ENABLED",
        "FATWA_TIMED_CITATIONS_ENABLED",
        "FATWA_PDF_CITATIONS_ENABLED",
        "FATWA_SOURCE_RIGHTS_ENFORCED",
        "FATWA_SOURCE_RIGHTS_ENABLED",
    ):
        value = getattr(settings, name, None)
        # Literal True/False are security gates; equality with 1/0 is insufficient.
        flags.append((name, type(value), value))
    bindings = []
    for name in ("FATWA_SOURCE_RIGHTS_AUTHORITY", "FATWA_PRIVATE_MEDIA_STORAGE"):
        adapter = getattr(settings, name, None)
        bindings.append((name, id(adapter), adapter))
    return tuple(flags), tuple(bindings)


def _record_pins(case_ids):
    result = [list(Case.objects.filter(pk__in=case_ids).order_by("pk").values())]
    if apps.is_installed("apps.source_rights"):
        from apps.source_rights.models import RightsAction, RightsRevision, SourceRegistration

        result.extend(
            (
                list(
                    SourceRegistration.objects.filter(case_id__in=case_ids).order_by("pk").values()
                ),
                list(RightsRevision.objects.filter(case_id__in=case_ids).order_by("pk").values()),
                list(
                    RightsAction.objects.filter(revision__case_id__in=case_ids)
                    .order_by("pk")
                    .values()
                ),
            )
        )
    if apps.is_installed("apps.content_reports"):
        from apps.content_reports.models import ContentReport, ReportEvent

        result.extend(
            (
                list(ContentReport.objects.filter(case_id__in=case_ids).order_by("pk").values()),
                list(
                    ReportEvent.objects.filter(report__case_id__in=case_ids).order_by("pk").values()
                ),
            )
        )
    return result


@mutation_context
@privacy.contextual
@contextmanager
def projection(*, subject_id, provider, page=1, case_ref=None, synthetic_fixtures_only=False):
    enabled()
    if (
        type(page) is not int
        or not 1 <= page <= 8
        or (case_ref is not None and (type(case_ref) is not str or not cases._ref(case_ref)))
    ):
        raise cases.CaseConflict("quality_selection_invalid")
    cases._guard(synthetic_fixtures_only)
    try:
        initial = resolve_identity(provider, subject_id)
        provider_id = provider.provider_id
        common = dict(subject_id=subject_id, provider=provider, synthetic_fixtures_only=True)
        with synthetic_queue_atomic(), cases._answer_use_boundary(), _projection_expiry_guard():
            available = Case.objects.filter(public_ref__in=initial.case_keys).order_by("id")
            if case_ref is not None:
                available = available.filter(public_ref=case_ref)
                if not available.exists():
                    raise cases.CaseConflict("quality_case_unavailable")
            visible = []
            # Valid identities contain at most 64 case refs. Apply independent
            # source classification before any page/count is constructed.
            for case in available.select_for_update():
                actor = cases._identity(provider, subject_id, case)
                if _actor(actor) != _actor(initial):
                    raise cases.CaseConflict("quality_identity_changed")
                try:
                    with privacy.staff_case(case, actor, provider):
                        privacy.current("CASE", case.pk, action="SEARCH")
                except PrivacyDenied:
                    if case_ref is not None:
                        raise
                    continue
                visible.append(case)
            count = len(visible)
            rows = visible[(page - 1) * PAGE_SIZE : page * PAGE_SIZE]
            identifiers = [case.pk for case in rows]
            configuration = _configuration()
            report_policy = _report_policy_pin()
            pins = deepcopy(_record_pins(identifiers))
            inspected = []
            for case in rows:
                actor = cases._identity(provider, subject_id, case)
                if _actor(actor) != _actor(initial):
                    raise cases.CaseConflict("quality_identity_changed")
                with privacy.staff_case(case, actor, provider):
                    inspected.append(_inspect_case(case, actor, common, report_policy))
            result = {
                "rows": inspected,
                "scanned_at": timezone.now(),
                "page": page,
                "previous_page": page - 1 if page > 1 else None,
                "next_page": page + 1 if page * PAGE_SIZE < count else None,
                "case_ref": case_ref,
                "page_case_count": len(inspected),
                "technical_count": sum(r["technical_count"] for r in inspected),
                "review_count": sum(r["review_count"] for r in inspected),
                "unchecked_count": sum(r["unchecked_count"] for r in inspected),
            }
            yield result
            enabled()
            if (
                _actor(resolve_identity(provider, subject_id)) != _actor(initial)
                or provider.provider_id != provider_id
            ):
                raise cases.CaseConflict("quality_identity_changed")
            if _report_policy_pin() != report_policy or _configuration() != configuration:
                raise cases.CaseConflict("quality_policy_changed")
            if _record_pins(identifiers) != pins:
                raise cases.CaseConflict("quality_records_changed")
    except IdentityUnavailable as exc:
        raise cases.CaseConflict("quality_identity_changed") from exc


@mutation_service
def dashboard(**kwargs):
    with projection(**kwargs) as result:
        return result
