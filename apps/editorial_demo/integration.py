"""Compose the existing D1/D3 pipeline on fixed synthetic bytes, without I/O.

This is not an input endpoint or a source acceptance. Rendering uses matching
original pointers, full mapped source identity and matching evidence, not flags.
"""
from dataclasses import asdict, dataclass
import hashlib
import json
from types import MappingProxyType

from apps.fatwa_drafts.intake import ReferenceLink, ValidationError, clip_url
from apps.prepared_pipeline import C1Pointer, ExplicitMapping, prepare_batch
from apps.reference_links.bridge import (
    BridgeConfig, EditionMap, HeadingMap, SourceIdentity, exact_text, resolve_prepared_pointers,
)
from apps.reference_links.resolution import Heading, SnapshotCatalog
from tools.content_intake.cli import parse_json


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

# Query values select these fixtures only, never a path or submitted content.
SYNTHETIC_BATCHES = MappingProxyType({"default": "دفعة الاستلام الأساسية", "mixed": "دفعة متنوعة"})
_MIXED_ROWS = (
    {"external_id": "SYN-P01", "question": "  سؤالٌ اصطناعيٌّ آخر\tللمراجعة\nفقط  ",
     "prepared_clip_url": "https://example.invalid/alternate.mp4", "reference_links": []},
    {"external_id": "SYN-M02", "question": "سؤال اصطناعي بمقطع مرفوض",
     "prepared_clip_url": "https://example.invalid:8443/blocked.mp4", "reference_links": []},
    {"external_id": "SYN-M03", "question": "سؤال اصطناعي بإحالة غير صالحة",
     "prepared_clip_url": "", "reference_links": [{"source_id": 7, "heading_id": None}]},
    {"external_id": "SYN-M04", "question": "سؤال اصطناعي ينتظر المقطع",
     "prepared_clip_url": "", "reference_links": []},
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


def _reference(expected: dict, item: dict, pointer, bridge: BridgeConfig, heading_index) -> PreviewReference:
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
    mapping = heading_index.get((expected.get("source_id"), expected.get("heading_id")))
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


def _row_references(original: dict, report: dict, resolved, bridge, heading_index):
    expected = original.get("reference_links", [])
    if resolved is None:
        # D1-blocked rows and D3-incompatible IDs stay visible. No verified
        # evidence is attached, and neither case can hide valid siblings.
        return tuple(PreviewReference("unverified", None, "invalid_input")
                     for _ in expected) if isinstance(expected, list) else ()
    if len(expected) != len(report["references"]) or len(expected) != len(resolved.reference_links):
        return tuple(PreviewReference("unverified", None, "reference_mismatch") for _ in expected)
    return tuple(_reference(source, item, pointer, bridge, heading_index) for source, item, pointer in
                 zip(expected, report["references"], resolved.reference_links, strict=True))


def compose_synthetic_batch(raw: bytes, *, synthetic_fixtures_only: bool = False,
                            reference_map, bridge_config, catalog) -> tuple[IntegratedPreviewRow, ...]:
    """Pure composition; acknowledgement asserts caller-supplied data is synthetic.

    Dependencies are explicit trusted caller configuration. No identity is inferred
    from question text. Pins are assertions, not proof of an inspected archive.
    """
    if synthetic_fixtures_only is not True:
        raise ValidationError("preview: synthetic_fixture_acknowledgement_required")
    if not isinstance(raw, bytes) or len(raw) > 1_000_000:
        raise ValidationError("json: invalid_size_or_type")
    try:
        envelope = parse_json(raw.decode("utf-8", errors="strict"))
        json.dumps(envelope, ensure_ascii=False).encode("utf-8", errors="strict")
    except (UnicodeError, ValueError, RecursionError) as exc:
        raise ValidationError("json: invalid_utf8_or_json") from exc
    if (not isinstance(envelope, dict) or set(envelope) != {"schema", "items"}
            or envelope["schema"] != SCHEMA or not isinstance(envelope["items"], list)
            or not 1 <= len(envelope["items"]) <= 1000):
        raise ValidationError("envelope: invalid")
    originals = envelope["items"]
    if any(isinstance(row, dict) and isinstance(row.get("reference_links"), list)
           and len(row["reference_links"]) > 100 for row in originals):
        raise ValidationError("reference_links: at_most_100")
    bridge = bridge_config
    batch = prepare_batch(raw, synthetic_fixtures_only=True, reference_map=reference_map, catalog=catalog)
    reports = batch.report["items"]
    if (
        len(reports) != len(originals)
        or batch.report.get("input_sha256") != hashlib.sha256(raw).hexdigest()
        or batch.report.get("synthetic_only") is not True
        or batch.report.get("human_editing_performed") is not False
    ):
        raise ValueError("synthetic_pipeline_alignment_failed")
    # D1 owns row validation. D3's envelope intentionally rejects duplicates and
    # malformed links: never feed it blocked rows or drop those rows from display.
    eligible_positions = set()
    for position, (original, report) in enumerate(zip(originals, reports, strict=True)):
        if "blocked-invalid" in report["statuses"]:
            continue
        # C2 permits internal tab/newline/DEL in an opaque external ID; D3's
        # exact-text contract is stricter. Retain the original receipt and require
        # review for that row, without renaming its ID or losing its siblings.
        try:
            exact_text(original.get("external_id"))
        except ValueError:
            continue
        eligible_positions.add(position)
    eligible = [originals[position] for position in sorted(eligible_positions)]
    # Compact serialization preserves the 1 MB bound instead of adding separators
    # to an otherwise eligible near-limit original envelope.
    resolution_raw = json.dumps({"schema": SCHEMA, "items": eligible}, ensure_ascii=False,
                                separators=(",", ":"), allow_nan=False).encode("utf-8")
    if len(resolution_raw) > 1_000_000:
        raise ValidationError("json: invalid_size_or_type")
    resolved_rows = resolve_prepared_pointers(
        resolution_raw, bridge, catalog,
    ) if eligible else ()
    if len(resolved_rows) != len(eligible):
        raise ValueError("synthetic_pipeline_alignment_failed")
    resolutions = iter(resolved_rows)
    # One local index per composition, never a global cache or per-pointer scan.
    heading_index = {(row.c1_source_id, row.c1_heading_id): row for row in bridge.headings}
    rendered = []
    for position, (original, report) in enumerate(zip(originals, reports, strict=True)):
        if report["original"] != original:
            raise ValueError("synthetic_pipeline_identity_mismatch")
        flags = set(report["statuses"])
        if flags - {*STATUS_LABELS, "references-unverified"} or len(flags & set(STATUS_LABELS)) != 1:
            raise ValueError("synthetic_pipeline_invalid_status")
        blocked = "blocked-invalid" in flags
        source = original if isinstance(original, dict) else {}
        resolved = next(resolutions) if position in eligible_positions else None
        if resolved is not None and source.get("external_id") != resolved.external_id:
            raise ValueError("synthetic_pipeline_identity_mismatch")
        draft = report["draft"]
        if blocked and draft is not None:
            raise ValueError("synthetic_pipeline_blocked_draft")
        if draft is not None:
            intake, revisions = draft.get("intake", {}), draft.get("history", [])
            if (
                intake.get("external_id") != source.get("external_id")
                or intake.get("question") != original.get("question", original.get("title", ""))
                or intake.get("prepared_clip_url") != original.get("prepared_clip_url", "")
                or len(revisions) != 1 or revisions[0].get("answer") != ""
                or revisions[0].get("action") != "received"
            ):
                raise ValueError("synthetic_pipeline_draft_identity_mismatch")
        refs = _row_references(source, report, resolved, bridge, heading_index)
        issues = []
        media_issue = _media_issue(source.get("prepared_clip_url", ""))
        if media_issue:
            issues.append(media_issue)
        if not source.get("reference_links"):
            issues.append("references_missing")
        issues.extend(ref.issue_code for ref in refs if ref.issue_code)
        if blocked or resolved is None:
            issues.append("invalid_input")
        issue_codes = tuple(dict.fromkeys(issues))
        if blocked:
            status = "blocked-invalid"
        elif draft is None or "needs-editor-review" in flags or "references-unverified" in flags or issue_codes:
            status = "needs-editor-review"
        else:
            status = "ready-for-editor"
        rendered.append(IntegratedPreviewRow(
            source.get("external_id", "") if isinstance(source.get("external_id", ""), str) else "",
            source.get("question", source.get("title", ""))
            if isinstance(source.get("question", source.get("title", "")), str) else "",
            source.get("prepared_clip_url", "")
            if isinstance(source.get("prepared_clip_url", ""), str) else "", status, draft is not None, refs,
            len(report["findings"]), issue_codes,
        ))
    return tuple(rendered)


def build_batch_preview_rows(batch: str) -> tuple[IntegratedPreviewRow, ...]:
    """Allowlisted deterministic fixtures; no path or payload accepted by views."""
    if batch not in SYNTHETIC_BATCHES:
        raise ValueError("unknown_synthetic_batch")
    items = _SYNTHETIC_ROWS if batch == "default" else _MIXED_ROWS
    raw = json.dumps({"schema": SCHEMA, "items": items}, ensure_ascii=False,
                     sort_keys=True, separators=(",", ":")).encode("utf-8")
    mapping, bridge, catalog = _synthetic_dependencies()
    return compose_synthetic_batch(raw, synthetic_fixtures_only=True,
                                   reference_map=mapping, bridge_config=bridge, catalog=catalog)


def build_preview_rows() -> tuple[IntegratedPreviewRow, ...]:
    """Backward-compatible no-argument wrapper for the original synthetic batch."""
    return build_batch_preview_rows("default")
