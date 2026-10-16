"""Compose the existing D1/D3 pipeline on fixed synthetic bytes, without I/O.

This is not an input endpoint or a source acceptance. Rendering uses matching
original pointers, full mapped source identity and matching evidence, not flags.
"""
from dataclasses import asdict, dataclass
import hashlib
import json

from apps.fatwa_drafts.intake import ReferenceLink, ValidationError, clip_url
from apps.prepared_pipeline import C1Pointer, ExplicitMapping, prepare_batch
from apps.reference_links.bridge import (
    BridgeConfig, EditionMap, HeadingMap, SourceIdentity, resolve_prepared_pointers,
)
from apps.reference_links.resolution import Heading, SnapshotCatalog


SCHEMA = "fatwa.prepared-intake.v1"
STATUS_LABELS = {
    "ready-for-editor": "سجل استلام اصطناعي جاهز للعرض على المحرر",
    "needs-editor-review": "يحتاج مراجعة بشرية؛ المراجع غير محسومة أو المقطع ناقص",
    "blocked-invalid": "مدخل مرفوض بسبب بيانات غير صالحة",
}
ISSUE_LABELS = {
    "media_missing": "رابط المقطع غير مرفق",
    "media_invalid": "رابط المقطع غير صالح",
    "references_missing": "لم تُرفق إحالات مرجعية",
    "reference_unverified": "الإحالة غير محسومة وتحتاج مراجعة",
    "reference_mismatch": "بيانات الإحالة غير متطابقة بين المسارين",
    "invalid_input": "توجد بيانات إدخال غير صالحة",
}

# Fabricated test identities only; never owner source data.
_SYNTHETIC_ROWS = (
    {
        "external_id": "SYN-P01",
        "question": "  سؤال اصطناعي في الطهارة للمراجعة فقط  ",
        "prepared_clip_url": "https://example.invalid/finished-001.mp4",
        "reference_links": [{"source_id": "synthetic-source", "heading_id": "synthetic-heading"}],
    },
    {
        "external_id": "SYN-P02",
        "question": "سؤال اصطناعي في الصلاة دون إحالة محسومة",
        "prepared_clip_url": "https://example.invalid/finished-002.mp4",
        "reference_links": [{"source_id": "unmapped-source", "heading_id": "unmapped-heading"}],
    },
    {
        "external_id": "SYN-P03",
        "question": "سؤال اصطناعي في الصيام ينتظر المقطع الجاهز",
        "prepared_clip_url": "",
        "reference_links": [],
    },
    {
        "external_id": "SYN-P04",
        "question": "سؤال اصطناعي في الزكاة بمقطع غير صالح",
        "prepared_clip_url": "http://example.invalid/finished-004.mp4",
        "reference_links": [],
    },
)


def _media_issue(value: str) -> str:
    if not value:
        return "media_missing"
    try:
        clip_url(value)
    except ValidationError:
        return "media_invalid"
    return ""


@dataclass(frozen=True, slots=True)
class PreviewReference:
    status: str
    citation: str | None
    issue_code: str = ""

    @property
    def status_label(self) -> str:
        return "مطابقة عنوان فهرس اصطناعي فقط" if self.status == "verified" else "إحالة غير محسومة"


@dataclass(frozen=True, slots=True)
class IntegratedPreviewRow:
    external_id: str
    question: str
    prepared_clip_url: str
    status: str
    draft_created: bool
    references: tuple[PreviewReference, ...]
    input_findings: int
    issue_codes: tuple[str, ...] = ()

    @property
    def status_label(self) -> str:
        return STATUS_LABELS[self.status]

    @property
    def issue_labels(self) -> tuple[str, ...]:
        return tuple(ISSUE_LABELS[code] for code in self.issue_codes)

    @property
    def media_status(self) -> str:
        issue = _media_issue(self.prepared_clip_url)
        if issue == "media_missing":
            return "رابط المقطع ناقص"
        if issue == "media_invalid":
            return "رابط المقطع غير صالح"
        return "رابط المقطع الجاهز (مثال غير قابل للفتح)"


def _synthetic_dependencies():
    identity = SourceIdentity("synthetic-only", "622", "demo-edition", "a" * 64, "b" * 64)
    mapping = HeadingMap("synthetic-source", "synthetic-heading", "synthetic-row", 73)
    bridge = BridgeConfig(EditionMap(identity, 41), (mapping,))
    catalog = SnapshotCatalog((
        Heading(
            41, 73, "مرجع فقهي اصطناعي", "باب تجريبي للطهارة",
            "الأول", 12, ("كتاب الطهارة", "باب تجريبي للطهارة"),
            identity.source_namespace, identity.source_book_id, identity.source_input_sha256,
        ),
    ))
    c2 = ReferenceLink(**asdict(identity), source_id=mapping.c2_source_id)
    d1_map = {
        C1Pointer(mapping.c1_source_id, mapping.c1_heading_id): ExplicitMapping(
            c2, bridge.edition.edition_id, mapping.source_row_id, "synthetic-wave5-only"
        )
    }
    return d1_map, bridge, catalog


def _reference(expected: dict, item: dict, pointer, bridge: BridgeConfig) -> PreviewReference:
    mismatch = PreviewReference("unverified", None, "reference_mismatch")
    if (
        item.get("original") != expected
        or len(pointer.original_pointer) != len(expected)
        or dict(pointer.original_pointer) != expected
    ):
        return mismatch
    if item.get("outcome") != "verified" or pointer.status.value != "verified":
        return PreviewReference("unverified", None, "reference_unverified")
    evidence = pointer.evidence
    mapping = next((row for row in bridge.headings if
                    (row.c1_source_id, row.c1_heading_id) ==
                    (expected.get("source_id"), expected.get("heading_id"))), None)
    if type(evidence) is not Heading or mapping is None:
        return mismatch
    pin = asdict(bridge.edition.identity)
    mapped = item.get("mapping", {})
    if (
        mapped.get("c2") != {**pin, "source_id": mapping.c2_source_id}
        or mapped.get("edition_id") != bridge.edition.edition_id
        or mapped.get("source_row_id") != mapping.source_row_id
        or evidence.edition_id != bridge.edition.edition_id
        or evidence.source_row_id != mapping.source_row_id
        or item.get("provenance") != asdict(evidence)
        or any(getattr(evidence, key) != pin[key] for key in
               ("source_namespace", "source_book_id", "source_input_sha256"))
    ):
        return mismatch
    # Plain text only: Django escapes once. Never trust/mark-safe adapter markup.
    citation = (
        f"إحالة إلى عنوان في فهرس {evidence.work_title}: {' / '.join(evidence.path)}"
        f"، ج {evidence.printed_part}، ص {evidence.printed_page} (عنوان فهرس، وليس نص فتوى)."
    )
    return PreviewReference("verified", citation)


def _row_references(original: dict, report: dict, resolved, bridge, blocked: bool):
    expected = original.get("reference_links", [])
    if blocked:
        # D1 may omit normalized references for a blocked row. Keep the row visible
        # but never attach verified evidence to it or fail the whole batch for it.
        return tuple(PreviewReference("unverified", None, "invalid_input") for _ in expected)
    if len(expected) != len(report["references"]) or len(expected) != len(resolved.reference_links):
        return tuple(PreviewReference("unverified", None, "reference_mismatch") for _ in expected)
    return tuple(_reference(source, item, pointer, bridge) for source, item, pointer in
                 zip(expected, report["references"], resolved.reference_links, strict=True))


def build_preview_rows() -> tuple[IntegratedPreviewRow, ...]:
    """Deterministic, in-memory processing of fixed synthetic fixtures only."""
    raw = json.dumps({"schema": SCHEMA, "items": _SYNTHETIC_ROWS}, ensure_ascii=False,
                     sort_keys=True, separators=(",", ":")).encode("utf-8")
    originals = json.loads(raw)["items"]
    d1_map, bridge, catalog = _synthetic_dependencies()
    batch = prepare_batch(raw, synthetic_fixtures_only=True, reference_map=d1_map, catalog=catalog)
    resolved_rows = resolve_prepared_pointers(raw, bridge, catalog)
    reports = batch.report["items"]
    if (
        len(reports) != len(originals) or len(resolved_rows) != len(originals)
        or batch.report.get("input_sha256") != hashlib.sha256(raw).hexdigest()
        or batch.report.get("synthetic_only") is not True
        or batch.report.get("human_editing_performed") is not False
    ):
        raise ValueError("synthetic_pipeline_alignment_failed")
    rendered = []
    for original, report, resolved in zip(originals, reports, resolved_rows, strict=True):
        if report["original"] != original or original.get("external_id") != resolved.external_id:
            raise ValueError("synthetic_pipeline_identity_mismatch")
        flags = set(report["statuses"])
        if flags - {*STATUS_LABELS, "references-unverified"} or len(flags & set(STATUS_LABELS)) != 1:
            raise ValueError("synthetic_pipeline_invalid_status")
        blocked = "blocked-invalid" in flags
        draft = report["draft"]
        if blocked and draft is not None:
            raise ValueError("synthetic_pipeline_blocked_draft")
        if draft is not None:
            intake, revisions = draft.get("intake", {}), draft.get("history", [])
            if (
                intake.get("external_id") != resolved.external_id
                or intake.get("question") != original.get("question", original.get("title", ""))
                or intake.get("prepared_clip_url") != original.get("prepared_clip_url", "")
                or len(revisions) != 1 or revisions[0].get("answer") != ""
                or revisions[0].get("action") != "received"
            ):
                raise ValueError("synthetic_pipeline_draft_identity_mismatch")
        refs = _row_references(original, report, resolved, bridge, blocked)
        issues = []
        media_issue = _media_issue(original.get("prepared_clip_url", ""))
        if media_issue:
            issues.append(media_issue)
        if not original.get("reference_links"):
            issues.append("references_missing")
        issues.extend(ref.issue_code for ref in refs if ref.issue_code)
        if blocked:
            issues.append("invalid_input")
        issue_codes = tuple(dict.fromkeys(issues))
        if blocked:
            status = "blocked-invalid"
        elif draft is None or "needs-editor-review" in flags or "references-unverified" in flags or issue_codes:
            status = "needs-editor-review"
        else:
            status = "ready-for-editor"
        rendered.append(IntegratedPreviewRow(
            resolved.external_id, original.get("question", original.get("title", "")),
            original.get("prepared_clip_url", ""), status, draft is not None, refs,
            len(report["findings"]), issue_codes,
        ))
    return tuple(rendered)
