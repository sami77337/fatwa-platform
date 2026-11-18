"""Private inspection of the existing immutable rights ledger, never a grant API."""

from django.utils import timezone

from apps.casework import services as cases
from apps.platform_recovery.integration import mutation_service

from . import services
from .models import RightsRevision, SourceRegistration, SourceVersion

USE_LABELS = {
    "READ": "قراءة المادة المتاحة",
    "CITE": "الاستشهاد بموضع الفهرس",
    "RELATE": "اقتراح علاقة علمية",
    "PREVIEW_METADATA": "إظهار بيانات الفهرس في معاينة مصرح بها",
    "FULL_TEXT": "قراءة متن الكتاب",
    "QUOTE": "نقل اقتباس من المادة",
    "PUBLISH": "نشر المادة الأصلية",
}
ACTION_LABELS = {
    "APPROVE": "اعتماد مستقل للحقوق المحددة",
    "REJECT": "رفض الاقتراح",
    "REVOKE": "سحب الإتاحة",
}
STATE_LABELS = {
    "UNKNOWN": "لم يُراجع حق هذه النسخة",
    "PENDING": "اقتراح ينتظر مراجعة مستقلة",
    "ALLOWED": "الاستخدامات المحددة معتمدة لهذه النسخة والقضية",
    "RESTRICTED": "مقيد بقرار مراجعة",
    "EXPIRED": "انتهت مدة القرار",
    "REJECTED": "رُفض الاقتراح",
    "REVOKED": "سُحبت الإتاحة",
    "SOURCE_CHANGED": "تغير المصدر؛ يلزم فحص هوية جديدة",
}


def material(source):
    snapshot = source.snapshot
    if source.kind == "TOC_METADATA":
        origin = snapshot["source"]
        fields = (
            ("الكتاب", "work_title"),
            ("الموضع", "heading_title"),
            ("الطبعة", "edition_title"),
            ("مفتاح الطبعة", "edition_key"),
            ("الناشر", "publisher"),
            ("الجزء", "printed_part"),
            ("الصفحة", "printed_page"),
            ("نطاق المصدر", "source_namespace"),
            ("رقم الكتاب في المصدر", "source_book_id"),
            ("الموضع في النسخة", "source_row_id"),
            ("بصمة أرشيف المصدر", "source_archive_sha256"),
            ("بصمة ملف الاستيراد", "source_input_sha256"),
        )
        return {
            "kind": source.kind,
            "label": "بيانات فهرس كتاب؛ ليست متن الكتاب",
            "description": "المرجع 622 فهرس لكتاب محدد. عنوان الموضع والجزء والصفحة ليسوا اقتباسًا أو متنًا فقهيًا.",
            "has_recorded_text": False,
            "identity": [{"label": label, "value": origin.get(key, "")} for label, key in fields],
            "snapshot_sha256": snapshot["source_sha256"],
        }
    return {
        "kind": source.kind,
        "label": "سؤال من تفريغ خاص محفوظ بالفعل",
        "description": "نص السؤال موجود في حزمته الخاصة؛ لا يُعرض هنا. فتحه يحتاج حق القراءة وصلاحية فتح التفريغ القائمة، ولا يبيح اقتباسه أو نشره.",
        "has_recorded_text": True,
        "identity": [
            {"label": label, "value": snapshot[key]}
            for label, key in (
                ("هوية المصدر", "source_id"),
                ("هوية السؤال داخل التفريغ", "pair_id"),
                ("بداية الموضع بالمللي ثانية", "start_ms"),
                ("نهاية الموضع بالمللي ثانية", "end_ms"),
                ("بصمة الحزمة الأصلية", "bundle_sha256"),
                ("بصمة المصدر", "source_sha256"),
                ("بصمة نص السؤال", "question_sha256"),
            )
        ],
        "snapshot_sha256": snapshot["question_sha256"],
    }


def usage_matrix(kind, state, uses):
    supported = services.USES if kind == "TOC_METADATA" else services.PRIVATE_USES
    rows = []
    for code, label in USE_LABELS.items():
        if code not in supported:
            reason = {
                "FULL_TEXT": "لا يوجد متن كتاب مسجل في هذه الهوية.",
                "QUOTE": "الاستشهاد ليس اقتباسًا. لا يوجد عقد مصرح للاقتباس من هذه المادة.",
                "PUBLISH": "لا يوجد إذن نشر للمادة الأصلية. موافقة نشر الجواب التحريري مستقلة ولا تمنح هذا الحق.",
                "CITE": "هذا سؤال تفريغ خاص؛ لا يُعامل كإحالة كتاب موثقة.",
                "PREVIEW_METADATA": "هوية التفريغ الخاص وبياناته ليست متاحة للمعاينة العامة.",
            }[code]
            status = "UNSUPPORTED"
        elif state == "ALLOWED" and code in uses:
            status = "ALLOWED"
            reason = "قرار حالي لهذه القضية والهوية فقط؛ يعاد الفحص عند كل استخدام."
            if code == "READ" and kind == "TOC_METADATA":
                reason = "قراءة بيانات الفهرس فقط، لا متن الكتاب."
            elif code == "PREVIEW_METADATA":
                reason = (
                    "بيانات الفهرس فقط مع سياسة معاينة وموافقة نشر مستقلتين؛ ليس إذن نشر الأصل."
                )
        else:
            status = "NOT_GRANTED"
            reason = (
                STATE_LABELS[state]
                if state != "ALLOWED"
                else "هذا الاستخدام غير مدرج في القرار الحالي."
            )
        rows.append({"code": code, "label": label, "status": status, "reason": reason})
    return rows


def review_options(source, revision, *, case, actor, provider, source_current=True):
    if revision is None or services._state(revision) in {"REJECTED", "REVOKED"}:
        return []
    options = []
    for action, label in ACTION_LABELS.items():
        if action in {"APPROVE", "REJECT"} and services._state(revision) != "PENDING":
            continue
        if action == "APPROVE" and (
            not source_current
            or (revision.provider_id, revision.subject_id)
            == (provider.provider_id, actor.subject_id)
        ):
            continue
        try:
            services._permit(actor, provider, case, action, source.sha256)
        except cases.CaseConflict:
            continue
        options.append({"value": action, "label": label})
    return options


def decorate_record(record, source, revisions, *, case, actor, provider):
    """Presentation only; record is already a private VIEW-authorized projection."""
    latest = revisions[0] if revisions else None
    record["material"] = material(source)
    record["state_label"] = STATE_LABELS[record["state"]]
    record["latest_uses"] = list(latest.uses) if latest else []
    record["usage_matrix"] = usage_matrix(source.kind, record["state"], record["latest_uses"])
    for row in record["history"]:
        row["is_current"] = bool(latest and row["id"] == str(latest.pk))
        row["review_options"] = (
            review_options(
                source,
                latest,
                case=case,
                actor=actor,
                provider=provider,
                source_current=record["state"] != "SOURCE_CHANGED",
            )
            if row["is_current"]
            else []
        )
    return record


@mutation_service
def inspect_source(
    *, case_id, subject_id, provider, source_id, revision_number=0, synthetic_fixtures_only=False
):
    """Inspect one registered source, its current restrictions and a pinned revision."""
    services._enabled()
    if type(revision_number) is not int or not 0 <= revision_number <= 64:
        raise cases.CaseConflict("source_rights_revision_invalid")
    with cases._staff_case(case_id, subject_id, provider, synthetic_fixtures_only) as (case, actor):
        services._permit(actor, provider, case, "VIEW")
        source = SourceVersion.objects.filter(pk=cases._uuid(source_id)).first()
        if (
            source is None
            or not SourceRegistration.objects.filter(case=case, source=source).exists()
        ):
            raise cases.CaseConflict("source_rights_target_unavailable")
        if source.sha256 != services._digest(source.snapshot):
            raise cases.CaseConflict("source_rights_source_changed")
        revisions = list(
            RightsRevision.objects.filter(case=case, source=source).order_by("-number")
        )
        latest = revisions[0] if revisions else None
        selected = (
            next((r for r in revisions if r.number == revision_number), None)
            if revision_number
            else latest
        )
        if revision_number and selected is None:
            raise cases.CaseConflict("source_rights_revision_unavailable")
        previous = next(
            (r for r in revisions if selected and r.number == selected.number - 1), None
        )
        state = services._state(latest)
        try:
            services._current_source(source, case)
        except cases.CaseConflict:
            state = "SOURCE_CHANGED"
        comparison = []
        if selected:
            for key, label in (
                ("uses", "الاستخدامات"),
                ("basis", "مرجع مستند الحقوق"),
                ("note", "سبب القرار"),
                ("valid_until", "نهاية المدة"),
            ):
                before = getattr(previous, key) if previous else None
                after = getattr(selected, key)
                comparison.append(
                    {
                        "field": key,
                        "label": label,
                        "before": before,
                        "after": after,
                        "changed": before != after,
                    }
                )
        services._identity(case, actor, provider)
        # Rights review may inspect history even after rights lapse. This is not
        # downstream material access, and never displays private transcript text.
        return {
            "case_ref": case.public_ref,
            "revision": case.revision,
            "evidence_version": case.evidence_version,
            "source_id": str(source.pk),
            "source_sha256": source.sha256,
            "source_created_at": source.created_at,
            "material": material(source),
            "current_state": state,
            "current_state_label": STATE_LABELS[state],
            "current_number": latest.number if latest else 0,
            "current_until": latest.valid_until if latest else None,
            "usage_matrix": usage_matrix(source.kind, state, latest.uses if latest else []),
            "selected": selected,
            "selected_is_current": bool(selected and selected == latest),
            "previous_number": previous.number if previous else None,
            "comparison": comparison,
            "versions": [{"number": r.number} for r in revisions],
            "selected_actions": list(
                selected.actions.order_by("id").values("action", "note", "subject_id", "created_at")
            )
            if selected
            else [],
            "inspected_at": timezone.now(),
        }
