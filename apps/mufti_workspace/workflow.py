"""Actionable presentation of canonical facts; no policy, permission or write authority."""


def _destination(tabs, key, label, *, fragment=""):
    tab = next((item for item in tabs if item["key"] == key), None)
    if tab is None:
        return None
    return {"label": label, "action": tab["action"], "fragment": fragment}


def describe_work(snapshot, *, manifest, release, return_reason, tabs):
    """Explain established workflow blockers without inventing scholarly requirements.

    A metadata-matching release is a recorded act, not verified present access.
    Rights, scholarly source suitability and delivery proofs remain in their
    existing authorized panels; this helper does not infer any of them.
    """
    latest = snapshot["latest_answer"]
    stage = snapshot["status"]
    approved = stage == "ANSWERED" and bool(snapshot["approved_answer_id"])
    changed = [
        row
        for row in snapshot["followups"]
        if latest and row["version"] > latest["evidence_version"]
    ]
    blockers = []
    if stage == "NEEDS_CLARIFICATION":
        blockers.append(
            {
                "code": "CLARIFICATION_PENDING",
                "text": "يلزم رد السائل على الاستيضاح قبل حفظ جواب جديد أو اعتماده.",
            }
        )
    if latest is None:
        blockers.append({"code": "ANSWER_REQUIRED", "text": "لم يُحفظ جواب لهذه القضية بعد."})
    elif latest["evidence_version"] != snapshot["evidence_version"]:
        blockers.append(
            {
                "code": "EVIDENCE_CHANGED",
                "text": f"أحدث جواب مبني على الوقائع {latest['evidence_version']}؛ الوقائع الحالية {snapshot['evidence_version']}. راجع المستجدات واحفظ إصدارًا جديدًا.",
            }
        )
    if stage == "RETURNED_FOR_CHANGES":
        blockers.append(
            {
                "code": "REVISION_REQUIRED",
                "text": "هذا الإصدار أُعيد للتعديل؛ يلزم حفظ إصدار جديد قبل إعادة المراجعة.",
            }
        )

    if stage == "NEEDS_CLARIFICATION":
        heading, detail = (
            "بانتظار رد السائل",
            "راجع الاستيضاح والوقائع المحفوظة. لا تُغلق حالة الانتظار بتعديل الجواب.",
        )
        primary = _destination(
            tabs, "overview", "راجع الاستيضاح والوقائع", fragment="mufti-facts-heading"
        )
    elif changed:
        heading, detail = (
            "راجع الوقائع التي أُضيفت بعد آخر جواب",
            f"الجواب {latest['revision']} يحتاج مراجعة على الوقائع الحالية قبل اعتماد جديد.",
        )
        primary = _destination(
            tabs, "overview", "افتح المستجدات قبل التحرير", fragment="mufti-evidence-changes"
        )
    elif stage == "RETURNED_FOR_CHANGES":
        heading, detail = (
            "عدّل الجواب وفق سبب الإعادة",
            "يبقى الإصدار السابق محفوظًا؛ الحفظ ينشئ إصدارًا جديدًا للمراجعة.",
        )
        primary = _destination(tabs, "overview", "انتقل لتحرير إصدار جديد", fragment="editor")
    elif latest is None:
        heading, detail = (
            "حرر جوابًا بعد مراجعة السؤال",
            "اقرأ السؤال والتعقيبات، ثم اكتب الجواب البشري أو افتح محرر الأجزاء عند الحاجة.",
        )
        primary = _destination(tabs, "overview", "ابدأ تحرير الجواب", fragment="editor")
    elif approved and manifest and release["enabled"] and not release["recorded"]:
        heading, detail = (
            "راجع الإتاحة الخاصة للإصدار المعتمد",
            "لم يسجل قرار إتاحة مطابق لهذا الإصدار. افتح لوحة الأجزاء للمراجعة واتخاذ القرار الصريح.",
        )
        primary = _destination(tabs, "answer", "راجع الإتاحة الخاصة")
    elif approved and manifest and release["recorded"] and release["enabled"]:
        heading, detail = (
            "راجع الإتاحة وسجل التوصيل كلًا على حدة",
            "قرار الإتاحة مسجل لهذا الإصدار؛ صلاحية الوصول الحالية وإثبات تسليم كل جزء يحتاجان تحقق لوحتيهما.",
        )
        primary = _destination(tabs, "delivery", "افتح سجل التوصيل للتحقق") or _destination(
            tabs, "answer", "افتح الإتاحة للتحقق"
        )
    elif approved:
        heading, detail = (
            "الاعتماد مسجل لهذا الإصدار",
            "راجع السجل والأجزاء قبل أي تعديل جديد؛ تغيير الجواب أو الوقائع يتطلب اعتمادًا جديدًا.",
        )
        primary = _destination(tabs, "overview", "راجع الإصدار والاعتماد المسجل", fragment="review")
    else:
        heading, detail = (
            "راجع أحدث إصدار واتخذ القرار البشري",
            "اقرأ النص وجميع الأجزاء وإحالاتها قبل الاعتماد أو الإعادة للتعديل.",
        )
        primary = _destination(tabs, "overview", "انتقل لمراجعة الإصدار", fragment="review")
    if primary is None:
        primary = _destination(tabs, "overview", "افتح القضية الحالية", fragment="review")

    answer_state = (
        "MISSING" if latest is None else "STALE" if snapshot["stale_answer"] else "RECORDED"
    )
    review_state = "RECORDED" if approved else "BLOCKED" if blockers else "NEEDS_HUMAN_REVIEW"
    private_state = (
        "NOT_APPLICABLE"
        if not manifest
        else "DISABLED"
        if not release["enabled"]
        else "WAITING_APPROVAL"
        if not approved
        else "RECORDED_NOT_VERIFIED"
        if release["recorded"]
        else "NEEDS_EXPLICIT_RELEASE"
    )
    steps = [
        {
            "key": "facts",
            "label": "الوقائع",
            "state": "WAITING_REPLY" if stage == "NEEDS_CLARIFICATION" else "RECORDED",
            "detail": f"إصدار الوقائع المحفوظ {snapshot['evidence_version']}",
        },
        {
            "key": "answer",
            "label": "الجواب",
            "state": answer_state,
            "detail": "لا يوجد إصدار محفوظ"
            if latest is None
            else f"الجواب {latest['revision']} مبني على الوقائع {latest['evidence_version']}",
        },
        {
            "key": "review",
            "label": "المراجعة البشرية",
            "state": review_state,
            "detail": "اعتماد مسجل مطابق للوقائع الحالية"
            if approved
            else "توجد متطلبات إجرائية قبل الاعتماد"
            if blockers
            else "يلزم قرار مفتي بعد قراءة الإصدار كاملًا",
        },
        {
            "key": "private",
            "label": "الإتاحة الخاصة للأجزاء",
            "state": private_state,
            "detail": {
                "NOT_APPLICABLE": "الجواب النصي يتبع مسار الإتاحة القائم؛ لم يُتحقق منه هنا",
                "DISABLED": "الإتاحة الخاصة للأجزاء غير مفعلة",
                "WAITING_APPROVAL": "تنتظر اعتمادًا مطابقًا للوقائع الحالية",
                "RECORDED_NOT_VERIFIED": "قرار مطابق مسجل؛ الوصول الحالي غير مفحوص في هذا الملخص",
                "NEEDS_EXPLICIT_RELEASE": "تحتاج قرار إتاحة مستقلًا وصريحًا",
            }[private_state],
        },
    ]
    supporting = []
    for key, label in (
        ("origins", "راجع أصل الأحداث"),
        ("attachments", "راجع مرفقات الوقائع"),
        ("citations", "راجع إحالات هذا الإصدار"),
    ):
        action = _destination(tabs, key, label)
        if action:
            supporting.append(action)
    if manifest:
        action = _destination(tabs, "answer", "راجع جميع أجزاء الجواب")
        if action:
            supporting.append(action)
    return {
        "heading": heading,
        "detail": detail,
        "primary": primary,
        "actions": supporting,
        "blockers": blockers,
        "steps": steps,
        "changed_evidence": changed,
        "answer_evidence_version": latest["evidence_version"] if latest else None,
        "return_reason": return_reason if stage == "RETURNED_FOR_CHANGES" else "",
        "release_recorded": release["recorded"],
        "delivery_verified": None,
        "read_confirmed": None,
    }
