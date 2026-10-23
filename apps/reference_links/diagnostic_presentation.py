"""Pure Arabic inspection documents for the existing synthetic diagnostic report.

These return ordinary strings: HTML is escaped, text must be served as text/plain.
No route, template, safe-marking, source lookup, archive inspection or I/O exists
here. Report decisions and their order belong exclusively to diagnostics.py.
The byte budget rejects the whole document; it never cuts original evidence.
"""

import json
from collections.abc import Iterator
from hashlib import sha256
from html import escape

from .diagnostics import ReferenceDiagnosticReport

MAX_OUTPUT_BYTES = 16_000_000
DEFAULT_OUTPUT_BYTES = 4_000_000
_TITLE = "تقرير تشخيص الإحالات الاصطناعية للقراءة فقط"
_LIMIT = (
    "النتائج تطابق تقني مع لقطة فهرس اصطناعي مصرح بها فقط؛ "
    "لا تثبت صحة علمية أو ملاءمة إحالة، ولا تعني فحص الأرشيف. "
    "هذا فهرس كتاب مرجعي وليس نصوص فتاوى، ولا يجيز نشرها أو اعتمادها. "
    "عناوين المصادر نصوص خاملة؛ لا يجري فتحها أو جلبها."
)


class DiagnosticPresentationError(ValueError):
    """The caller did not provide the explicit synthetic presentation contract."""


class _Output:
    def __init__(self, limit: int) -> None:
        self.limit = limit
        self.size = 0
        self.parts: list[str] = []

    def add(self, text: str) -> None:
        try:
            size = len(text.encode("utf-8", errors="strict"))
        except UnicodeError as error:
            raise DiagnosticPresentationError("invalid_utf8") from error
        if self.size + size > self.limit:
            raise DiagnosticPresentationError("output_limit_exceeded")
        self.size += size
        self.parts.append(text)

    def finish(self) -> str:
        return "".join(self.parts)


def _prepare(
    report: ReferenceDiagnosticReport, acknowledgement: bool, limit: int,
) -> tuple[dict[str, object], _Output]:
    if acknowledgement is not True:
        raise DiagnosticPresentationError("synthetic_acknowledgement_required")
    if type(report) is not ReferenceDiagnosticReport:
        raise DiagnosticPresentationError("diagnostic_report_required")
    if type(limit) is not int or not 1 <= limit <= MAX_OUTPUT_BYTES:
        raise DiagnosticPresentationError("invalid_output_limit")
    return report.to_payload(), _Output(limit)


def _json(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False)


def _source_blocks(source: dict[str, object]) -> Iterator[tuple[str, str]]:
    text = source["text"]
    yield "p", (
        f"بداية البايت: {source['start']}؛ نهاية البايت المستثناة: {source['end']}؛ "
        f"SHA256 للنص الأصلي بترميز UTF-8: {sha256(text.encode('utf-8')).hexdigest()}"
    )
    yield "pre", text


def _blocks(payload: dict[str, object]) -> Iterator[tuple[str, str]]:
    """Keep supplied item, reference, reason, binding and catalog order intact."""
    yield "h2", "هوية المدخل وحدود التقرير والبوابات"
    yield "pre", _json({key: value for key, value in payload.items()
                        if key not in {"items", "asserted_catalog", "trusted_binding", "summary"}})
    yield "h2", "روابط الإعداد الاصطناعي المصرح بها"
    yield "pre", _json(payload["trusted_binding"])
    yield "h2", "لقطة الفهرس المصرح بها دون إعادة تحقق"
    if not payload["asserted_catalog"]:
        yield "p", "لا توجد صفوف فهرس مصرح بها."
    for number, row in enumerate(payload["asserted_catalog"], 1):
        yield "h3", f"صف الفهرس {number}"
        yield "pre", _json(row)
    yield "h2", "العناصر ونصوص المصدر الأصلية"
    if not payload["items"]:
        yield "p", "لا توجد عناصر في التقرير."
    for item in payload["items"]:
        yield "h3", f"العنصر {item['row_ordinal']}"
        yield "p", "نص العنصر الأصلي كما ورد، مع هوية موضعه في المدخل."
        yield from _source_blocks(item["source"])
        if not item["references"]:
            yield "p", "لا توجد إحالات مسجلة لهذا العنصر."
        for reference in item["references"]:
            yield "h4", f"العنصر {item['row_ordinal']} — الإحالة {reference['reference_ordinal']}"
            yield "p", (
                f"الحالة التقنية: {reference['contract_status']} ({reference['status']})؛ "
                f"{reference['explanation_ar']}"
            )
            yield "p", reference["verification_limit_ar"]
            if not reference["reasons"]:
                yield "p", "لا توجد أسباب تشخيصية مسجلة؛ لا يعني ذلك اعتمادا علميا."
            for reason, explanation in zip(reference["reasons"],
                                           reference["reason_explanations_ar"], strict=True):
                yield "p", f"رمز السبب الأصلي: {reason}؛ {explanation}"
            yield "p", "نص مؤشر الإحالة الأصلي (ليس صياغة إحالة علمية)."
            yield from _source_blocks(reference["source"])
            yield "p", "الهوية المسجلة في التقرير؛ الكائن الفارغ يعني عدم وجود هوية مثبتة."
            yield "pre", _json(reference["verified_identity"])
            if reference["evidence"] is None:
                yield "p", "لا يوجد دليل مطابق مسجل في التقرير؛ لم تنشأ إحالة أو بيانات بديلة."
            else:
                yield "p", "بيانات دليل التقرير كما وردت؛ null قيمة غائبة لم يتم استكمالها."
                yield "pre", _json(reference["evidence"])


def render_reference_diagnostics_html(
    report: ReferenceDiagnosticReport, *, synthetic_fixtures_only: bool = False,
    max_output_bytes: int = DEFAULT_OUTPUT_BYTES,
) -> str:
    """Return a standalone escaped RTL document, or reject its entire UTF-8 size.

    Requires an existing report and literal True acknowledgement. URLs remain
    inert text. The caller owns delivery; this function writes no artifact.
    """
    payload, output = _prepare(report, synthetic_fixtures_only, max_output_bytes)
    output.add('<!doctype html>\n<html lang="ar" dir="rtl">\n<head>\n')
    output.add('<meta charset="utf-8">\n<meta name="viewport" content="width=device-width">\n')
    output.add(f"<title>{_TITLE}</title>\n</head>\n<body>\n<main aria-labelledby=\"report-title\">\n")
    output.add(f'<h1 id="report-title">{_TITLE}</h1>\n<p>{_LIMIT}</p>\n')
    output.add('<table>\n<caption>عدد الإحالات حسب الحالة التقنية فقط</caption>\n')
    output.add('<thead><tr><th scope="col">الحالة</th><th scope="col">العدد</th></tr></thead>\n<tbody>\n')
    for status, count in payload["summary"].items():
        output.add(f'<tr><th scope="row"><bdi dir="ltr">{escape(status, quote=True)}</bdi></th>'
                   f'<td>{escape(str(count), quote=True)}</td></tr>\n')
    output.add("</tbody>\n</table>\n")
    for kind, text in _blocks(payload):
        # HTML normalizes literal CR/CRLF before parsing. A character reference
        # retains the original CR in source text nodes and their copied bytes.
        escaped = escape(text, quote=True).replace("\r", "&#13;")
        if kind == "pre":
            # The code child also prevents HTML's initial-pre-newline stripping.
            output.add(f'<pre dir="auto"><code>{escaped}</code></pre>\n')
        else:
            output.add(f"<{kind}>{escaped}</{kind}>\n")
    output.add("</main>\n</body>\n</html>\n")
    return output.finish()


def render_reference_diagnostics_text(
    report: ReferenceDiagnosticReport, *, synthetic_fixtures_only: bool = False,
    max_output_bytes: int = DEFAULT_OUTPUT_BYTES,
) -> str:
    """Return plain text for text/plain consumers; never embed it as HTML."""
    payload, output = _prepare(report, synthetic_fixtures_only, max_output_bytes)
    output.add(f"{_TITLE}\n\n{_LIMIT}\n\nعدد الإحالات حسب الحالة التقنية فقط\n")
    output.add(_json(payload["summary"]) + "\n\n")
    for _, text in _blocks(payload):
        output.add(text + "\n\n")
    return output.finish()
