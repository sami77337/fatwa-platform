"""Current operational queue derived from real source records; no shadow status table."""

from contextlib import contextmanager

from apps.answer_media import services as media
from apps.answer_media.models import AnswerManifest
from apps.case_organization import services as organization
from apps.casework import services as cases
from apps.delivery_queue.models import DeliveryIntent
from apps.development_taxonomy.boundary import verify as verify_taxonomy
from apps.development_taxonomy.models import CaseClassification, HumanReview
from apps.experimental_publication import services as publication
from apps.experimental_publication.models import PublicationEdition
from apps.public_answer_media import services as recording
from apps.public_answer_media.models import RecordingTranscript

from . import coordination, lesson_links, notes, retry_projection, transcripts
from . import metadata as metadata_editor
from .boundary import rows, scope

FILTERS = {
    "all": "كل الإجراءات المخوّلة",
    "metadata": "تصنيف أو بيانات تنظيمية ناقصة",
    "delivery": "فشل التسليم والمطابقة",
    "publication": "إجراء نشر مطلوب",
    "transcript": "مراجعة التفريغ",
    "capability": "تدخل بسبب قدرات القناة",
}
SECTION_ACTIONS = {
    "metadata": "READ_METADATA",
    "delivery": "READ_DELIVERY",
    "publication": "READ_PUBLICATION",
    "transcript": "READ_TRANSCRIPT",
    "capability": "READ_CAPABILITY",
}
STAGES = {
    "RECEIVED": "سؤال جديد",
    "UNDER_REVIEW": "قيد المراجعة",
    "NEEDS_CLARIFICATION": "بانتظار استيضاح",
    "RETURNED_FOR_CHANGES": "أعيد للتعديل",
    "ANSWERED": "جواب معتمد محفوظ",
}
DELIVERY_STATES = {
    "STAGED": "مجهز ولم يرسل",
    "LEASED": "محاولة قيد التنفيذ",
    "SENT_UNCONFIRMED": "قبول مسجل؛ التسليم غير مؤكد",
    "DELIVERED": "حالة تسليم مسجلة",
    "FAILED_REQUIRES_REVIEW": "فشل مسجل يحتاج مراجعة",
    "UNKNOWN_REQUIRES_RECONCILIATION": "نتيجة غير محسومة تحتاج مطابقة",
}


def metadata(case, guard):
    history = organization._rows(case)
    latest = history[-1] if history else None
    tags = latest.tags if latest else []
    types = latest.question_types if latest else []
    binding = (
        CaseClassification.objects.filter(case=case)
        .select_related("version")
        .order_by("-sequence")
        .first()
    )
    classified = False
    if binding:
        verify_taxonomy(binding)
        verify_taxonomy(binding.version)
        review = HumanReview.objects.filter(version=binding.version).first()
        if review:
            verify_taxonomy(review)
        classified = bool(
            case.approved_answer_id
            and binding.answer_id == case.approved_answer_id
            and binding.evidence_version == case.evidence_version
            and review
            and review.action == "APPROVE"
            and review.content_digest == binding.version.digest
        )
    reasons = []
    if not tags:
        reasons.append("لم تسجل وسوم بشرية")
    if not types:
        reasons.append("لم يسجل نوع السؤال")
    if case.approved_answer_id and not classified:
        reasons.append("لا يوجد تصنيف فقهي حالي لهذا الجواب")
    return {
        "key": "metadata",
        "label": FILTERS["metadata"],
        "pending": bool(reasons),
        "reasons": reasons,
        "version": latest.version if latest else 0,
        "tags": tags,
        "question_types": [organization.QUESTION_TYPES[value] for value in types],
        "current_classification": classified,
    }


def delivery(case, guard):
    intents = rows(DeliveryIntent.objects.filter(case_key=case.public_ref))
    retries = guard.observe(lambda: retry_projection.read(case))
    resolved = set(retries["resolved"])
    parts = []
    for row in sorted(intents, key=lambda value: (value["answer_revision"], value["ordinal"])):
        if row["state"] not in DELIVERY_STATES:
            raise cases.CaseConflict("operational_delivery_history_invalid")
        logical = retries["logical"].get(row["intent_key"], {})
        parts.append(
            {
                "answer_revision": row["answer_revision"],
                "ordinal": logical.get("ordinal", row["ordinal"]),
                "queue_ordinal": row["ordinal"],
                "retry_number": logical.get("retry_number", 0),
                "resolved_by_retry": row["intent_key"] in resolved,
                "state": row["state"],
                "label": DELIVERY_STATES[row["state"]],
            }
        )
    failures = sum(
        part["state"] == "FAILED_REQUIRES_REVIEW" and not part["resolved_by_retry"]
        for part in parts
    )
    uncertain = sum(part["state"] == "UNKNOWN_REQUIRES_RECONCILIATION" for part in parts)
    return {
        "key": "delivery",
        "label": FILTERS["delivery"],
        "pending": bool(
            failures or uncertain or retries["unbound_claims"] or retries["verification_issue"]
        ),
        "reasons": (["يوجد جزء فاشل مسجل"] if failures else [])
        + (["توجد نتيجة تحتاج مطابقة بشرية"] if uncertain else [])
        + (["يوجد إذن تسليم غير مرتبط بسجل التسليم المرجعي"] if retries["unbound_claims"] else [])
        + (
            ["تعذر التحقق الحالي من سلسلة المحاولات اللاحقة"]
            if retries["verification_issue"]
            else []
        ),
        "parts": parts,
        "failed_parts": failures,
        "uncertain_parts": uncertain,
        "unbound_claims": len(retries["unbound_claims"]),
        "resolved_failed_attempts": sum(part["resolved_by_retry"] for part in parts),
        "notice": "هذه حالات السجل الداخلي. لا يثبت هذا العرض وصول الجواب أو يمنح إذن إرسال.",
    }


def publication_state(case, guard):
    latest = PublicationEdition.objects.filter(case=case).order_by("-number").first()
    result = {
        "key": "publication",
        "label": FILTERS["publication"],
        "pending": False,
        "reasons": [],
        "number": latest.number if latest else 0,
        "state": "لا توجد نسخة تحريرية",
    }
    if latest is None:
        return result
    publication._verify(latest)
    actions = set(latest.actions.values_list("action", flat=True))
    if "WITHDRAW" in actions:
        result["state"] = "نسخة مسحوبة محفوظة في التاريخ"
    elif (
        latest.answer_id != case.approved_answer_id
        or latest.evidence_version != case.evidence_version
    ):
        result.update(
            pending=True,
            state="تغير المصدر بعد النسخة التحريرية",
            reasons=["راجع النسخة مقابل الوقائع والجواب الحاليين"],
        )
    elif "APPROVE" in actions:
        result["state"] = "اعتماد نشر محفوظ؛ الإتاحة الحالية لها تحقق مستقل"
    elif "REVIEW" in actions:
        result.update(
            pending=True,
            state="تحتاج قرار نشر مستقلًا",
            reasons=["المراجعة محفوظة ولم يسجل اعتماد النشر"],
        )
    else:
        result.update(
            pending=True, state="تحتاج مراجعة تحريرية", reasons=["نسخة تحريرية محفوظة بلا مراجعة"]
        )
    return result


def transcript(case, guard):
    latest = {}
    for row in (
        RecordingTranscript.objects.filter(case=case)
        .select_related("part")
        .order_by("part_id", "number")[:8193]
    ):
        recording._verify(row)
        latest[row.part_id] = row
    if len(latest) > 64:
        raise cases.CaseConflict("operational_transcript_bound")
    versions, reasons = [], []
    for row in latest.values():
        actions = list(row.actions.order_by("sequence"))
        for action in actions:
            recording._verify(action)
        kinds = {action.action for action in actions}
        needed = "APPROVE_MEANING" if row.change_kind == "MEANING_REVIEW" else "REVIEW"
        current = (
            row.part.manifest.answer_id == case.approved_answer_id
            and row.evidence_version == case.evidence_version
        )
        pending = "WITHDRAW" not in kinds and (needed not in kinds or not current)
        state = (
            "تفريغ مسحوب"
            if "WITHDRAW" in kinds
            else "تغير مصدر التفريغ"
            if not current
            else "مراجعة محفوظة"
            if needed in kinds
            else "تحتاج مراجعة المعنى من مفتي مخول"
            if needed == "APPROVE_MEANING"
            else "تحتاج مراجعة تحريرية مستقلة"
        )
        versions.append(
            {
                "number": row.number,
                "change_kind": row.change_kind,
                "state": state,
                "pending": pending,
                "original_ordinal": row.part.ordinal,
            }
        )
        if pending and state not in reasons:
            reasons.append(state)
    return {
        "key": "transcript",
        "label": FILTERS["transcript"],
        "pending": bool(reasons),
        "reasons": reasons,
        "versions": versions,
        "notice": "العرض يبين حالة المراجعة. قراءة التسجيل أو نص التفريغ وتحريره لها صلاحيات مستقلة.",
    }


def capability(case, guard):
    result = {
        "key": "capability",
        "label": FILTERS["capability"],
        "pending": False,
        "reasons": [],
        "parts": [],
        "channel": "",
    }
    if not case.approved_answer_id:
        return result
    origin = cases._delivery_origin_for_locked_case(case)
    result["channel"] = origin["channel"]
    profile = guard.profile(origin["channel"])
    if profile is None:
        result.update(pending=True, reasons=["تعذر التحقق من قدرات حالية ومثبتة للقناة"])
        return result
    caps = profile.capabilities
    if (
        type(caps.supported) is not frozenset
        or not caps.supported <= {"text", "audio", "video", "image", "document", "link"}
        or type(caps.max_text_chars) is not int
        or not 1 <= caps.max_text_chars <= 100000
        or type(caps.delivery_receipts) is not bool
    ):
        raise cases.CaseConflict("operational_capability_invalid")
    manifest = AnswerManifest.objects.filter(answer_id=case.approved_answer_id).first()
    if manifest:
        originals = list(manifest.parts.order_by("ordinal"))
        if (
            len(originals) != manifest.part_count
            or media._digest([media._fields(row) for row in originals]) != manifest.sha256
        ):
            raise cases.CaseConflict("operational_manifest_invalid")
        parts = [
            {"ordinal": row.ordinal, "kind": row.kind, "size": row.size, "mime": row.media_type}
            for row in originals
        ]
    else:
        parts = [{"ordinal": 1, "kind": "TEXT", "size": 0, "mime": "text/plain"}]
    media_types = {
        "TEXT": "text",
        "FILE": "document",
        "AUDIO": "audio",
        "IMAGE": "image",
        "YOUTUBE_LINK": "link",
    }
    for part in parts:
        reasons = []
        if media_types.get(part["kind"]) not in caps.supported:
            reasons.append("نوع الجزء غير مدعوم")
        if part["kind"] == "TEXT" and len(case.approved_answer.text) > caps.max_text_chars:
            reasons.append("النص يتجاوز حد القناة")
        if part["kind"] != "TEXT" and (
            part["size"] > profile.max_media_bytes or part["mime"] not in profile.allowed_mime
        ):
            reasons.append("صيغة الملف أو حجمه خارج قدرة القناة")
        if not caps.delivery_receipts:
            reasons.append("إيصالات التسليم الموقعة غير متاحة")
        result["parts"].append(
            {"ordinal": part["ordinal"], "kind": part["kind"], "reasons": reasons}
        )
        for reason in reasons:
            if reason not in result["reasons"]:
                result["reasons"].append(reason)
    result["pending"] = bool(result["reasons"])
    return result


READERS = {
    "metadata": metadata,
    "delivery": delivery,
    "publication": publication_state,
    "transcript": transcript,
    "capability": capability,
}


def sections(case, guard, *, selected=None):
    result = []
    for key in SECTION_ACTIONS:
        if selected and key != selected:
            continue
        if guard.permit(case, SECTION_ACTIONS[key], key, required=bool(selected)):
            result.append(READERS[key](case, guard))
    return result


@contextmanager
def queue_projection(*, selected_filter="all", **common):
    if type(selected_filter) is not str or selected_filter not in FILTERS:
        raise cases.CaseConflict("operational_filter_invalid")
    with scope(**common) as guard:
        result, counts, metadata_cases = [], {key: 0 for key in FILTERS}, []
        coordination_cases = []
        lesson_cases = []
        transcript_cases = []
        for case in sorted(guard.locked.values(), key=lambda value: value.public_ref):
            if not guard.permit(case, "READ_QUEUE", "queue") or not guard.permit(
                case, "READ_CASE", "case"
            ):
                continue
            cases._verify(case)
            if metadata_editor.available(case, guard):
                metadata_cases.append({"public_ref": case.public_ref})
            if coordination.available(case, guard):
                coordination_cases.append(coordination.summary(case, guard))
            if lesson_links.available(case, guard):
                lesson_cases.append({"public_ref": case.public_ref})
            if transcripts.available(case, guard):
                transcript_cases.append({"public_ref": case.public_ref})
            available = sections(case, guard)
            pending = [row for row in available if row["pending"]]
            if not pending:
                continue
            counts["all"] += 1
            for row in pending:
                counts[row["key"]] += 1
            if selected_filter != "all" and not any(
                row["key"] == selected_filter for row in pending
            ):
                continue
            result.append(
                {
                    "public_ref": case.public_ref,
                    "stage": STAGES[case.stage],
                    "revision": case.revision,
                    "evidence_version": case.evidence_version,
                    "pending": pending,
                    "notes_available": any(notes.access(case, guard).values()),
                }
            )
        yield {
            "rows": result,
            "metadata_cases": metadata_cases,
            "coordination_cases": sorted(
                coordination_cases, key=lambda row: (row["rank"], row["public_ref"])
            ),
            "lesson_cases": lesson_cases,
            "transcript_cases": transcript_cases,
            "counts": counts,
            "selected_filter": selected_filter,
            "filters": [
                {"key": key, "label": label, "count": counts[key]} for key, label in FILTERS.items()
            ],
            "subject": guard.actor.subject_id,
            "role": guard.actor.role,
        }


@contextmanager
def detail_projection(*, case_ref, section, **common):
    if type(case_ref) is not str or len(case_ref) > 128 or section not in SECTION_ACTIONS:
        raise cases.CaseConflict("operational_detail_invalid")
    with scope(**common) as guard:
        case = next((row for row in guard.locked.values() if row.public_ref == case_ref), None)
        if case is None:
            raise cases.CaseConflict("operational_detail_unavailable")
        guard.permit(case, "READ_CASE", "case", required=True)
        cases._verify(case)
        detail = sections(case, guard, selected=section)[0]
        yield {
            "public_ref": case.public_ref,
            "stage": STAGES[case.stage],
            "revision": case.revision,
            "evidence_version": case.evidence_version,
            "question": case.source.original_question,
            "section": detail,
            "subject": guard.actor.subject_id,
            "role": guard.actor.role,
            "notes_available": any(notes.access(case, guard).values()),
            "metadata_available": metadata_editor.available(case, guard),
            "lesson_links_available": lesson_links.available(case, guard),
            "transcript_editor_available": transcripts.available(case, guard),
        }
