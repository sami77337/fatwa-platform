"""Stateless browser workflow. Signed state is synthetic data, never an access grant."""

import base64
import os
import re
from hashlib import sha256
from pathlib import Path

from django.conf import settings
from django.core import signing
from django.core.exceptions import DisallowedHost, SuspiciousOperation
from django.http import HttpResponse
from django.middleware.csrf import get_token
from django.shortcuts import render
from django.views.decorators.csrf import csrf_protect
from django.views.decorators.debug import sensitive_post_parameters

from apps.editorial_workbench.reviewer_access import browser_proof
from apps.transcript_pipeline import MAX_BYTES

from .services import Document, ValidationError, export_bundle, open_document, review, revise

BASE = "/transcripts/"
STATE_SALT = "fatwa.transcript-workbench.v1"
ROUTES = {
    BASE: ("GET", "HEAD", "POST"),
    BASE + "review/": ("POST",),
    BASE + "example/": ("GET", "HEAD"),
    BASE + "workbench.css": ("GET", "HEAD"),
}
MAX_BODY = 4_000_000
FINDING_LABELS = {
    "overlap": "تداخل بين مقطعين؛ راجع البداية والنهاية يدويًا",
    "gap": "فترة زمنية غير مغطاة",
    "input_order": "ترتيب الإدخال يختلف عن ترتيب الأزمنة",
    "duplicate_segment_id": "معرّف مقطع مكرر؛ صححه في الملف ثم أعد الاستيراد",
    "duplicate_span": "الفترة الزمنية مكررة",
    "ambiguous_pair": "أكثر من سؤال أو جواب في الزوج نفسه؛ صحح الربط في الملف",
    "question_required": "الزوج لا يحتوي على سؤال؛ صحح الملف ثم أعد الاستيراد",
    "answer_must_follow_question": "يجب أن يبدأ الجواب بعد نهاية السؤال",
    "answer_not_supplied": "لم يُرفق جواب لهذا السؤال",
}


def _private(response):
    response["Cache-Control"] = "private, no-store, max-age=0"
    response["Vary"] = "Cookie"
    response["X-Content-Type-Options"] = "nosniff"
    response["Referrer-Policy"] = "same-origin"
    response["X-Robots-Tag"] = "noindex, nofollow, noarchive"
    response["Content-Security-Policy"] = (
        "default-src 'none'; style-src 'self'; form-action 'self'; "
        "base-uri 'none'; frame-ancestors 'none'"
    )
    return response


def _failure(status):
    return _private(HttpResponse("تعذر قبول الطلب في مساحة التفريغات المحلية.", status=status))


class LocalGuard:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if (
            os.environ.get("FATWA_PRODUCTION") != "0"
            or getattr(settings, "FATWA_TRANSCRIPT_WORKBENCH_ENABLED", False) is not True
        ):
            return _failure(503)
        if request.META.get("REMOTE_ADDR") not in {"127.0.0.1", "::1"}:
            return _failure(403)
        try:
            if not re.fullmatch(r"(?:127\.0\.0\.1|\[::1\])(?::[0-9]{1,5})?", request.get_host()):
                return _failure(400)
        except DisallowedHost:
            return _failure(400)
        if request.path not in ROUTES:
            return _failure(404)
        if request.method not in ROUTES[request.path]:
            response = _failure(405)
            response["Allow"] = ", ".join(ROUTES[request.path])
            return response
        if request.META.get("QUERY_STRING"):
            return _failure(400)
        try:
            length = int(request.META.get("CONTENT_LENGTH") or "0")
            if not 0 <= length <= MAX_BODY or len(request.body) > MAX_BODY:
                return _failure(413)
        except (ValueError, SuspiciousOperation):
            return _failure(413)
        response = _private(self.get_response(request))
        if request.method == "HEAD":
            response.content = b""
        return response


def _seal(request, document):
    payload = {
        "original": base64.b64encode(document.original).decode("ascii"),
        "original_suffix": document.original_suffix,
        "current": base64.b64encode(document.current).decode("ascii"),
        "current_suffix": document.current_suffix,
        "revision": document.revision,
        "binding": browser_proof(request, STATE_SALT, sha256(document.original).hexdigest()),
    }
    return signing.dumps(payload, salt=STATE_SALT, compress=False)


def _unseal(request, state):
    if not 1 <= len(state) <= 3_600_000:
        raise ValidationError("review: state_invalid")
    try:
        saved = signing.loads(state, salt=STATE_SALT, max_age=1800)
        original = base64.b64decode(saved["original"], validate=True)
        current = base64.b64decode(saved["current"], validate=True)
        binding = browser_proof(request, STATE_SALT, sha256(original).hexdigest())
        if not signing.constant_time_compare(saved["binding"], binding):
            raise ValueError("binding")
        return Document(
            original, saved["original_suffix"], current, saved["current_suffix"], saved["revision"]
        )
    except (signing.BadSignature, ValueError, TypeError, KeyError) as exc:
        raise ValidationError("review: state_invalid_or_expired") from exc


def _fields(request, names, optional=()):
    if request.content_type not in {"application/x-www-form-urlencoded", "multipart/form-data"}:
        raise ValidationError("form: unsupported_format")
    values = request.POST
    required = set(names) | {"csrfmiddlewaretoken"}
    if not required <= set(values) <= required | set(optional) or any(
        len(values.getlist(key)) != 1 for key in values
    ):
        raise ValidationError("form: invalid_fields")
    return values


def _integer(value):
    if type(value) is not str or not re.fullmatch(r"0|[1-9][0-9]{0,7}", value):
        raise ValidationError("form: integer_required")
    return int(value)


def _page(request, document=None, *, index=0, error="", status=200):
    get_token(request)
    context = {"error": error}
    if document:
        rows, timeline, queue, queue_error = review(document)
        for finding in timeline["findings"]:
            finding["label"] = FINDING_LABELS.get(finding["code"], "مقطع يحتاج إلى مراجعة")
            finding["severity_label"] = {
                "error": "خطأ",
                "warning": "تنبيه",
                "info": "معلومة",
            }[finding["severity"]]
        if not 0 <= index < len(rows):
            raise ValidationError("review: invalid_segment")
        context.update(
            state=_seal(request, document),
            rows=rows,
            selected=rows[index],
            index=index,
            timeline=timeline,
            can_export=queue is not None,
            queue_error=queue_error,
            entries=queue.entries if queue else (),
            revision=document.revision,
            original_sha=sha256(document.original).hexdigest(),
            current_sha=sha256(document.current).hexdigest(),
        )
    return render(request, "workbench.html", context, status=status)


@sensitive_post_parameters()
@csrf_protect
def index(request):
    if request.method in {"GET", "HEAD"}:
        return _page(request)
    try:
        values = _fields(request, {"synthetic_only"})
        if values["synthetic_only"] != "yes" or set(request.FILES) != {"transcript"}:
            raise ValidationError("form: acknowledgement_and_file_required")
        if len(request.FILES.getlist("transcript")) != 1:
            raise ValidationError("form: one_file_required")
        upload = request.FILES["transcript"]
        if upload.size > MAX_BYTES:
            return _failure(413)
        document = open_document(
            upload.read(MAX_BYTES + 1),
            Path(upload.name).suffix.lower(),
            synthetic_fixtures_only=True,
        )
        return _page(request, document)
    except (ValidationError, SuspiciousOperation):
        return _page(
            request,
            error="لم يُستورد الملف. تحقق من صيغة JSON أو CSV أو JSONL، "
            "والحقول المطلوبة وإقرار البيانات الاصطناعية؛ الحد مليون بايت.",
            status=400,
        )


@sensitive_post_parameters()
@csrf_protect
def update(request):
    try:
        action = request.POST.get("action")
        names = {"state", "action"}
        if action in {"select", "revise"}:
            names |= {"index"}
        if action == "revise":
            names |= {"start_ms", "end_ms", "text"}
        if action not in {"select", "revise", "export"}:
            raise ValidationError("form: invalid_action")
        fields = _fields(request, names, {"replace_text"} if action == "revise" else ())
        if request.FILES:
            raise ValidationError("form: unexpected_file")
        document = _unseal(request, fields["state"])
        index = _integer(fields["index"]) if "index" in fields else 0
        if action == "export":
            raw = export_bundle(document)
            response = HttpResponse(raw, content_type="application/zip")
            response["Content-Disposition"] = (
                'attachment; filename="synthetic-transcript-review.zip"'
            )
            response["X-Export-SHA256"] = sha256(raw).hexdigest()
            return response
        if action == "revise":
            if fields.get("replace_text") not in (None, "yes"):
                raise ValidationError("form: invalid_replacement")
            try:
                document = revise(
                    document,
                    index=index,
                    start_ms=_integer(fields["start_ms"]),
                    end_ms=_integer(fields["end_ms"]),
                    replacement_text=fields["text"]
                    if fields.get("replace_text") == "yes"
                    else None,
                )
            except ValidationError:
                return _page(
                    request,
                    document,
                    index=index,
                    error="لم يُحفظ التعديل. أدخل فترة صحيحة ونصًا غير فارغ ضمن الحدود.",
                    status=400,
                )
        return _page(request, document, index=index)
    except (ValidationError, SuspiciousOperation):
        return _page(
            request,
            error="تعذر تنفيذ الطلب. قد تكون المراجعة منتهية أو من متصفح آخر، "
            "أو توجد أخطاء تمنع التصدير. أعد استيراد الملف عند الحاجة.",
            status=400,
        )


def example(request):
    raw = (
        Path(__file__).resolve().parents[3]
        / "tools/transcript_pipeline/examples/synthetic-manual.json"
    ).read_bytes()
    response = HttpResponse(raw, content_type="application/json; charset=utf-8")
    response["Content-Disposition"] = 'attachment; filename="synthetic-manual.json"'
    return response


def stylesheet(request):
    raw = (Path(__file__).parent / "workbench.css").read_text(encoding="utf-8")
    return HttpResponse(raw, content_type="text/css; charset=utf-8")
