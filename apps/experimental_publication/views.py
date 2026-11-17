"""Explicit POST actions composed into the existing guarded staff URL."""

from django.conf import settings
from django.core.exceptions import SuspiciousOperation
from django.db import DatabaseError
from django.middleware.csrf import get_token
from django.shortcuts import render
from django.views.decorators.csrf import csrf_protect
from django.views.decorators.debug import sensitive_post_parameters

from apps.casework import services as cases
from apps.casework_web.access import RequestDirectory, current_staff
from apps.casework_web.guard import denied, private
from apps.casework_web.views import InvalidForm, _form, _integer, _provider
from apps.intake_workflow.guards import SyntheticWriteDenied
from apps.mufti_review.identity import IdentityUnavailable

from . import services

ACTIONS = {
    "pub_open",
    "pub_correct",
    "pub_create",
    "pub_review",
    "pub_approve",
    "pub_withdraw",
    "pub_library",
    "pub_read",
}


MESSAGES = {
    "pub_create": "حُفظت نسخة مرشحة جديدة. الخطوة التالية مراجعة التحرير والخصوصية.",
    "pub_review": "سُجلت المراجعة. تنتظر النسخة موافقة مخوّل نشر مستقل.",
    "pub_approve": "سُجلت موافقة النشر. افتح النسخة الحالية في المكتبة المغلقة.",
    "pub_withdraw": "سُحبت النسخة من العرض والبحث. بقي تاريخها محفوظًا.",
}
ERRORS = {
    "case_revision_changed": "تغيّرت القضية منذ فتح النموذج. راجع الحالة الحالية قبل إعادة التحرير.",
    "case_evidence_changed": "تغيّرت الوقائع. يلزم مراجعة الجواب واعتماده قبل إعداد نسخة نشر جديدة.",
    "current_approval_required": "لا يوجد جواب حالي معتمد. عُد إلى القضية لمتابعة المراجعة.",
    "publication_source_changed": "تغيّر الجواب أو وقائعه؛ هذه النسخة لم تعد صالحة للإجراء المطلوب.",
    "publication_citation_source_changed": "تغيّر مصدر الإحالة. راجع المصدر قبل إنشاء نسخة جديدة.",
    "publication_edition_changed": "توجد نسخة مرشحة أحدث. تابع النسخة الأحدث الظاهرة أدناه.",
    "publication_correction_source_changed": "تغيّر أساس التصحيح. افتح النسخة الحالية وابدأ تصحيحًا جديدًا.",
    "independent_publication_approver_required": "يلزم مخوّل نشر مستقل عن محرر النسخة ومراجعها ومعتمد الجواب.",
    "publication_action_denied": "هويتك الحالية لا تحمل تفويض هذا الإجراء. بقيت النسخة دون تغيير.",
    "publication_authority_required": "تفويض النشر المستقل غير مهيأ؛ تبقى الإتاحة مغلقة.",
    "publication_transition_invalid": "سبق تنفيذ الإجراء أو سُحبت النسخة. راجع حالتها الحالية أدناه.",
}


def _desk_page(request, common, fields, *, correction=None, error=None, status=200):
    selected = services.desk(**common)  # Rechecks identity/scope before any recovery output.
    request.publication_authorized_case_ref = selected["public_ref"]
    attempted = None
    if error and fields["action"] == "pub_create":
        values = {key: fields[key] for key in ("title", "category", "body")}
        try:
            for key, value in values.items():
                cases._text(value, optional=True)
                if len(value) > {"title": 160, "category": 80, "body": cases.MAX_TEXT}[key]:
                    raise cases.CaseConflict("invalid_case_text")
        except cases.CaseConflict:
            pass
        else:
            attempted = values  # Copy-only buffer, never bound to fresh revision pins.
    return private(
        render(
            request,
            "experimental_publication/desk.html",
            {
                "selected": selected,
                "correction": correction,
                "attempted": attempted,
                "message": MESSAGES.get(fields["action"], "") if not error else "",
                "error": ERRORS.get(
                    str(error),
                    "لم يُحفظ الإجراء. راجع الحالة الحالية وصحة النص والصلاحية قبل المحاولة مجددًا.",
                )
                if error
                else "",
                "library_query": fields.get("library_query", ""),
                "library_category": fields.get("library_category", ""),
            },
            status=status,
        )
    )


@sensitive_post_parameters("body", "title", "query")
@csrf_protect
def workspace(request):
    try:
        services._enabled()
        if request.method != "POST" or request.POST.get("action") not in ACTIONS:
            raise InvalidForm("publication_form_invalid")
        directory = _provider()
        identity = current_staff(request, directory)
        provider = RequestDirectory(
            directory, identity, authenticated_provider_id=directory.provider_id
        )
        action = request.POST.get("action")
        required = {"action", "query"} if action == "pub_library" else {"action", "case_ref"}
        if action == "pub_library" and "category" in request.POST:
            required.add("category")
        if action == "pub_read":
            required = {"action", "edition_id"}
            if "query" in request.POST or "category" in request.POST:
                required |= {"query", "category"}
        if action == "pub_open" and "edition_id" in request.POST:
            required = {"action", "edition_id"}
        if action == "pub_correct":
            required.add("edition_id")
        if action == "pub_create":
            required |= {"revision", "evidence_version", "title", "category", "body"}
            if "source_edition_id" in request.POST:
                required.add("source_edition_id")
        elif action in {"pub_review", "pub_approve", "pub_withdraw"}:
            required |= {"edition_id", "confirm"}
        if action not in {"pub_library", "pub_read"} and (
            "library_query" in request.POST or "library_category" in request.POST
        ):
            required |= {"library_query", "library_category"}
        fields = _form(request, required)
        for key in ("library_query", "library_category", "query"):
            value = fields.get(key, "")
            cases._text(value, optional=True)
            if len(value) > 80:
                raise InvalidForm("publication_form_invalid")
        if request.FILES:
            raise InvalidForm("publication_form_invalid")
        common = {
            "subject_id": identity.subject_id,
            "provider": provider,
            "synthetic_fixtures_only": True,
        }
        get_token(request)
        if action == "pub_library":
            return private(
                render(
                    request,
                    "experimental_publication/library.html",
                    {
                        "publications": services.library(
                            **common, query=fields["query"], category=fields.get("category", "")
                        ),
                        "categories": sorted(
                            {row["category"] for row in services.library(**common)}
                        ),
                        "query": fields["query"],
                        "category": fields.get("category", ""),
                    },
                )
            )
        if action == "pub_read":
            for key in ("query", "category"):
                if len(fields.get(key, "")) > 80:
                    raise InvalidForm("publication_form_invalid")
            edition = next(
                (row for row in services.library(**common) if row["id"] == fields["edition_id"]),
                None,
            )
            if edition is None:
                return denied("publication_unavailable", 404)
            return private(
                render(
                    request,
                    "experimental_publication/detail.html",
                    {
                        "edition": edition,
                        "knowledge_enabled": getattr(
                            settings, "FATWA_KNOWLEDGE_LINKS_ENABLED", False
                        )
                        is True,
                        "query": fields.get("query", ""),
                        "category": fields.get("category", ""),
                    },
                )
            )
        if action == "pub_open" and "edition_id" in fields:
            try:
                selected = services.editorial_case(**common, edition_id=fields["edition_id"])
            except cases.CaseConflict:
                return denied("publication_unavailable", 404)
        else:
            scoped = cases.list_cases(**common)
            selected = next(
                (row for row in scoped if row["public_ref"] == fields["case_ref"]), None
            )
        if selected is None:
            return denied("publication_unavailable", 404)
        common["case_id"] = selected["case_id"]
        try:
            correction = None
            if action == "pub_correct":
                correction = services.correction_draft(**common, edition_id=fields["edition_id"])
            elif action == "pub_create":
                services.create_edition(
                    **common,
                    expected_revision=_integer(fields["revision"]),
                    expected_evidence_version=_integer(fields["evidence_version"]),
                    title=fields["title"],
                    category=fields["category"],
                    body=fields["body"],
                    source_edition_id=fields.get("source_edition_id"),
                )
            elif action != "pub_open":
                if fields["confirm"] != "yes":
                    raise InvalidForm("publication_confirmation_required")
                services.act(
                    **common,
                    edition_id=fields["edition_id"],
                    action={
                        "pub_review": "REVIEW",
                        "pub_approve": "APPROVE",
                        "pub_withdraw": "WITHDRAW",
                    }[action],
                    reviewed=True,
                )
        except cases.CaseConflict as exc:
            return _desk_page(request, common, fields, error=exc, status=409)
        return _desk_page(request, common, fields, correction=correction)
    except (InvalidForm, SuspiciousOperation):
        return denied("publication_form_invalid", 400)
    except IdentityUnavailable:
        return denied("staff_identity_required", 403)
    except cases.CaseConflict:
        return denied("publication_action_not_accepted", 409)
    except (DatabaseError, SyntheticWriteDenied):
        return denied("publication_store_unavailable", 503)
