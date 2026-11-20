"""One token-authorized snapshot, no parallel case, answer or delivery records."""

from contextlib import contextmanager
from copy import deepcopy

from django.apps import apps
from django.conf import settings

from apps.casework import delivery
from apps.casework import services as cases
from apps.platform_recovery.integration import mutation_context, mutation_service
from apps.requester_access_review import services as access

LABELS = {
    "UNDER_REVIEW": "الجواب قيد المراجعة",
    "APPROVED_UNAVAILABLE": "الجواب معتمد لكنه غير متاح حاليًا",
    "PRIVATE_AVAILABLE": "الجواب متاح داخل البوابة الخاصة",
    "PROVIDER_ACCEPTED": "أبلغ مزود القناة عن قبول الإرسال؛ لم يكتمل إثبات التسليم",
    "SIGNED_DELIVERED": "اكتمل إثبات تسليم جميع الأجزاء الموقّعة",
    "UNRESOLVED": "التسليم غير محسوم أو يحتاج تدخلًا بشريًا",
    "NOT_PROVEN": "لم يثبت تسليم الجواب عبر القناة",
}


def enabled():
    if getattr(settings, "FATWA_REQUESTER_PORTAL_ENABLED", False) is not True:
        raise cases.CaseConflict("requester_portal_disabled")


@mutation_context
@contextmanager
def page_projection(*, token, expected_result, synthetic_fixtures_only=False):
    """Keep the private snapshot authorized through enrichment and HTML rendering.

    A later component may observe a withdrawn release while an earlier component
    still holds answer text and part links. The whole page uses the canonical
    case/queue lock and existing media-policy/expiry boundary. Re-reading after
    rendering checks the current capability, release, answer and delivery facts;
    a changed projection discards the already generated response.
    """
    enabled()
    with delivery._token_case(token, synthetic_fixtures_only):
        current = snapshot(token=token, synthetic_fixtures_only=synthetic_fixtures_only)
        if current != expected_result:
            raise cases.CaseConflict("portal_page_changed")
        # Presentation code cannot change the baseline used by the final check.
        baseline = deepcopy(current)
        yield current
        if snapshot(token=token, synthetic_fixtures_only=synthetic_fixtures_only) != baseline:
            raise cases.CaseConflict("portal_page_changed")


def _delivery_state(status, summary):
    if summary is not None:
        if summary["delivery_verified"] is True:
            state = "SIGNED_DELIVERED"
        elif summary["failed_parts"] or summary["unresolved_parts"]:
            state = "UNRESOLVED"
        elif summary["accepted_parts"]:
            state = "PROVIDER_ACCEPTED"
        elif summary["human_action"] or summary["verified_parts"]:
            state = "UNRESOLVED"  # Partial receipts cannot certify the whole answer.
        else:
            state = "NOT_PROVEN"
    elif status["delivery_verified"] is True:
        state = "SIGNED_DELIVERED"
    elif status["delivery_status"] in {"CURRENT_APPROVAL_REQUIRED", "NOT_STAGED"}:
        state = "NOT_PROVEN"
    else:
        state = "UNRESOLVED"
    return {"state": state, "label": LABELS[state], "summary": summary, "read_confirmed": False}


@mutation_service
def snapshot(*, token, synthetic_fixtures_only=False):
    enabled()
    # Same case/queue lock order as V9. Nested existing service calls participate
    # in this transaction, so facts cannot change between conversation and answer.
    with delivery._token_case(token, synthetic_fixtures_only) as case:
        source = access.requester_snapshot(
            token,
            verifier=getattr(settings, "FATWA_CASE_DELIVERY_PROVIDER_VERIFIER", None),
            show_approved_answer=getattr(settings, "FATWA_CASEWORK_PRIVATE_ANSWER_ENABLED", False)
            is True,
            synthetic_fixtures_only=synthetic_fixtures_only,
        )
        status = source["case"]
        attachments = []
        attachments_enabled = getattr(settings, "FATWA_CASE_ATTACHMENTS_ENABLED", False) is True
        if attachments_enabled:
            from apps.case_attachments.services import requester_list

            rows = requester_list(token=token, synthetic_fixtures_only=synthetic_fixtures_only)
            attachments = [
                {
                    key: row[key]
                    for key in (
                        "id",
                        "filename",
                        "size",
                        "media_type",
                        "kind",
                        "created_at",
                        "evidence_version",
                    )
                }
                for row in rows["attachments"]
            ]
        answer, summary = None, source["composite_delivery"]
        try:
            if source["private_media_availability"]["available"]:
                from apps.answer_media.services import requester_snapshot

                package = requester_snapshot(
                    token=token, synthetic_fixtures_only=synthetic_fixtures_only
                )["package"]
                if (
                    package["answer_id"] != str(case.approved_answer_id)
                    or package["evidence_version"] != status["evidence_version"]
                ):
                    raise cases.CaseConflict("portal_answer_changed")
                answer = {
                    "text": package["text"],
                    "revision": package["answer_revision"],
                    "parts": [
                        {
                            key: row[key]
                            for key in ("id", "ordinal", "kind", "filename", "media_type", "size")
                        }
                        for row in package["parts"]
                        if row["kind"] != "TEXT"
                    ],
                }
            elif source["private_answer"] is not None:
                answer = {**source["private_answer"], "parts": []}
            if answer is not None:
                answer["citations"] = []
                if apps.is_installed("apps.case_citations"):
                    from apps.case_citations.services import citations_for_locked_answer

                    # Authority comes from exact current private-answer release,
                    # not a staff impersonation or a guessed answer ID.
                    citations = citations_for_locked_answer(case.approved_answer)
                    answer["citations"] = [
                        {
                            key: row["source"][key]
                            for key in (
                                "work_title",
                                "heading_title",
                                "edition_title",
                                "publisher",
                                "printed_part",
                                "printed_page",
                                "path",
                            )
                        }
                        for row in citations
                    ]
                # Recheck authority after reading media/source metadata.
                if source["private_media_availability"]["available"]:
                    from apps.answer_media.services import private_availability_for_locked_case

                    if not private_availability_for_locked_case(case)["available"]:
                        raise cases.CaseConflict("portal_release_changed")
        except cases.CaseConflict:
            answer, summary = None, None
        answer_state = (
            "PRIVATE_AVAILABLE"
            if answer is not None
            else "APPROVED_UNAVAILABLE"
            if status["status"] == "ANSWERED"
            else "UNDER_REVIEW"
        )
        # Explicit allowlist: no drafts, decisions, actor IDs, raw inbound payload,
        # research notes, signatures, leases, audit events or storage locations.
        result = {
            "public_ref": status["public_ref"],
            "revision": status["revision"],
            "evidence_version": status["evidence_version"],
            "clarification": status["clarification"],
            "history": [row for row in source["requester_history"] if row["kind"] != "answer"],
            "attachments": attachments,
            "attachments_enabled": attachments_enabled,
            "answer": answer,
            "answer_state": answer_state,
            "answer_label": LABELS[answer_state],
            "delivery": _delivery_state(status, summary),
            "read_confirmed": False,
            "access_reviews": source["reviews"],
        }
        final = cases.requester_status(token, synthetic_fixtures_only=synthetic_fixtures_only)
        if (final["revision"], final["evidence_version"]) != (
            result["revision"],
            result["evidence_version"],
        ):
            raise cases.CaseConflict("portal_snapshot_changed")
        return result


@mutation_service
def submit_reply(*, token, text, expected_revision, attachment=None, synthetic_fixtures_only=False):
    """Append a literal reply and optional file atomically using existing services.

    A clarification reply first clears the clarification through add_followup;
    upload then appends its separate immutable evidence. Both commit or neither
    commits. External digest locks surround the outer transaction (V9 GC contract).
    """
    enabled()
    cases._text(text)
    cases.requester_status(token, synthetic_fixtures_only=synthetic_fixtures_only)
    if attachment is None:
        return cases.add_followup(
            token=token,
            text=text,
            expected_revision=expected_revision,
            synthetic_fixtures_only=synthetic_fixtures_only,
        )
    if type(attachment) is not dict or set(attachment) != {"raw", "filename", "media_type"}:
        raise cases.CaseConflict("portal_attachment_invalid")
    from apps.case_attachments import services as attachments
    from apps.case_attachments.storage_bindings import binding_locks
    from apps.private_media.storage import configured_storage
    from apps.private_media.validation import MediaValidationError

    attachments._enabled()
    media = attachments._validate(**attachment)
    try:
        storage = configured_storage()
        with (
            binding_locks(storage, [media.sha256]),
            delivery._token_case(token, synthetic_fixtures_only),
        ):
            reply = cases.add_followup(
                token=token,
                text=text,
                expected_revision=expected_revision,
                synthetic_fixtures_only=synthetic_fixtures_only,
            )
            attachments.upload(
                token=token,
                expected_revision=reply["revision"],
                synthetic_fixtures_only=synthetic_fixtures_only,
                **attachment,
            )
            return cases.requester_status(token, synthetic_fixtures_only=synthetic_fixtures_only)
    except MediaValidationError as exc:
        raise cases.CaseConflict("private_storage_unavailable") from exc


def journey(result):
    """Presentation-only next step and timeline from the existing safe projection."""
    if result["clarification"]:
        next_step = dict(
            title="مطلوب توضيح منك",
            text="أرسل ردك ويمكنك إرفاق ملف معه في الخطوة نفسها.",
            anchor="followup",
            action="الرد على الاستيضاح",
        )
    elif result["answer"] is not None:
        next_step = dict(
            title="جوابك متاح هنا",
            text="يمكنك قراءة الجواب أو فتح أجزائه. حالة القناة مستقلة أدناه.",
            anchor="answer",
            action="قراءة الجواب وأجزائه",
        )
    else:
        next_step = dict(
            title="قضيتك لدى الفريق",
            text="لا يلزم تكرار السؤال. يمكنك إضافة معلومات جديدة عند الحاجة.",
            anchor="followup",
            action="إضافة معلومات للقضية",
        )
    timeline = [dict(row) for row in result["history"]]
    timeline.extend(
        dict(
            kind="attachment",
            label="مرفق محفوظ ضمن القضية",
            text=row["filename"],
            created_at=row["created_at"],
            evidence_version=row["evidence_version"],
            attachment_id=row["id"],
        )
        for row in result["attachments"]
    )
    timeline.sort(key=lambda row: (row["evidence_version"], row["created_at"]))
    return dict(next_step=next_step, timeline=timeline)
