"""Same-case navigation and evidence grouping, with no new operational state."""


def evidence_history(snapshot, attachments, origins):
    """Join already-authorized projections only by their canonical evidence version."""
    latest = snapshot["latest_answer"]
    entries = [dict(version=1, text=snapshot["original_question"]), *snapshot["followups"]]
    return [
        {
            **entry,
            "current": entry["version"] == snapshot["evidence_version"],
            "newer_than_answer": bool(latest and entry["version"] > latest["evidence_version"]),
            "attachments": [a for a in attachments if a["evidence_version"] == entry["version"]],
            "origins": [o for o in origins if o["evidence_version"] == entry["version"]],
            "answer_revisions": [
                answer["revision"]
                for answer in snapshot["answers"]
                if answer["evidence_version"] == entry["version"]
            ],
        }
        for entry in entries
    ]


def connected_actions(tabs, *, manifest, waiting):
    """Navigation only: controls open existing panels, never approve/release/send."""
    enabled = {tab["key"]: tab for tab in tabs}
    groups = (
        (
            "facts",
            "الوقائع والأصل",
            (
                ("overview", "السؤال والوقائع والمرفقات", "mufti-evidence-history"),
                ("origins", "مراجعة أصل الرسائل ومتابعتها", ""),
            ),
        ),
        (
            "research",
            "البحث والإحالات",
            (
                ("rights", "راجع نوع المصدر وحقوق استعماله", ""),
                ("research", "ابحث وافتح مصدرًا مصرحًا", ""),
                ("citations", "راجع إحالات إصدار الجواب", ""),
            ),
        ),
        (
            "answer",
            "التحرير والمراجعة",
            (
                (
                    "answer" if manifest else "overview",
                    "تحرير النص مع الأجزاء" if manifest else "تحرير مسودة الجواب",
                    "" if manifest else "editor",
                ),
                ("overview", "مراجعة الإصدار والقرار البشري", "review"),
            ),
        ),
        (
            "private",
            "الإتاحة والتسليم",
            (
                ("answer", "راجع الإتاحة الخاصة المستقلة", ""),
                ("delivery", "خطة التسليم وحالة كل جزء", ""),
                ("pilot", "تسجيل نتائج المحاكي المحلي بشريًا", ""),
            ),
        ),
        (
            "publication",
            "النشر التجريبي المستقل",
            (("publication", "النسخة التحريرية والمكتبة والعودة", ""),),
        ),
    )
    result = []
    for key, label, links in groups:
        actions = []
        for tab_key, text, fragment in links:
            if tab_key not in enabled:
                continue
            if waiting and key == "answer" and "تحرير" in text:
                continue
            tab = enabled[tab_key]
            actions.append({"action": tab["action"], "label": text, "fragment": fragment})
        if actions:
            result.append({"key": key, "label": label, "actions": actions})
    return result
