"""Wave5 local demonstration: compose D1 and D3 on fixed synthetic bytes only.

No request payload, filesystem, database, network, AI, or production side effects.
D1's eligibility and D3's exact source identity must both agree before display.
"""
from dataclasses import dataclass
import json

from apps.fatwa_drafts.intake import ReferenceLink
from apps.prepared_pipeline import C1Pointer, ExplicitMapping, prepare_batch
from apps.reference_links.bridge import (
    BridgeConfig,
    EditionMap,
    HeadingMap,
    SourceIdentity,
    resolve_prepared_pointers,
)
from apps.reference_links.resolution import Heading, SnapshotCatalog


SCHEMA = "fatwa.prepared-intake.v1"
STATUS_LABELS = {
    "ready-for-editor": "سجل استلام اصطناعي جاهز للعرض على المحرر",
    "needs-editor-review": "يحتاج مراجعة بشرية؛ المراجع غير محسومة أو المقطع ناقص",
    "blocked-invalid": "مدخل مرفوض بسبب بيانات غير صالحة",
}

# These labels/sha strings are fabricated test identities, NOT owner data.
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


@dataclass(frozen=True, slots=True)
class PreviewReference:
    status: str
    citation: str | None

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

    @property
    def status_label(self) -> str:
        return STATUS_LABELS[self.status]

    @property
    def media_status(self) -> str:
        if not self.prepared_clip_url:
            return "رابط المقطع ناقص"
        if self.status == "blocked-invalid":
            return "رابط المقطع غير صالح"
        return "رابط المقطع الجاهز (مثال غير قابل للفتح)"


def _synthetic_dependencies():
    # Only the explicit mapping for SYN-P01 may verify; never infer from text.
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
    c2 = ReferenceLink(
        identity.source_namespace,
        identity.source_book_id,
        identity.edition_key,
        identity.source_archive_sha256,
        identity.source_input_sha256,
        mapping.c2_source_id,
    )
    d1_map = {
        C1Pointer(mapping.c1_source_id, mapping.c1_heading_id): ExplicitMapping(
            c2, bridge.edition.edition_id, mapping.source_row_id, "synthetic-wave5-only"
        )
    }
    return d1_map, bridge, catalog


def build_preview_rows() -> tuple[IntegratedPreviewRow, ...]:
    """Create a deterministic per-request in-memory preview; never accept real input."""
    raw = json.dumps(
        {"schema": SCHEMA, "items": _SYNTHETIC_ROWS},
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    d1_map, bridge, catalog = _synthetic_dependencies()
    batch = prepare_batch(raw, synthetic_fixtures_only=True, reference_map=d1_map, catalog=catalog)
    resolved_rows = resolve_prepared_pointers(raw, bridge, catalog)
    reported_rows = batch.report["items"]
    if len(reported_rows) != len(resolved_rows):
        raise ValueError("synthetic_pipeline_alignment_failed")

    rendered: list[IntegratedPreviewRow] = []
    for report, resolved in zip(reported_rows, resolved_rows, strict=True):
        original = report["original"]
        if not isinstance(original, dict) or original.get("external_id") != resolved.external_id:
            raise ValueError("synthetic_pipeline_identity_mismatch")
        d1_references = report["references"]
        if len(d1_references) != len(resolved.reference_links):
            raise ValueError("synthetic_pipeline_reference_count_mismatch")
        # Fail closed if a future adapter marks a pointer verified without both checks.
        refs = tuple(
            PreviewReference(
                "verified" if item["outcome"] == "verified" and pointer.status.value == "verified" else "unverified",
                pointer.citation if item["outcome"] == "verified" and pointer.status.value == "verified" else None,
            )
            for item, pointer in zip(d1_references, resolved.reference_links, strict=True)
        )
        draft = report["draft"]
        if draft is not None:
            intake = draft.get("intake", {})
            revisions = draft.get("history", [])
            if (
                intake.get("external_id") != resolved.external_id
                or intake.get("question") != original.get("question")
                or len(revisions) != 1
                or revisions[0].get("answer") != ""
                or revisions[0].get("action") != "received"
            ):
                raise ValueError("synthetic_pipeline_draft_identity_mismatch")
        flags = set(report["statuses"])
        if "blocked-invalid" in flags:
            status = "blocked-invalid"
        elif (
            draft is None
            or "needs-editor-review" in flags
            or "references-unverified" in flags
            or not refs
            or any(reference.status != "verified" for reference in refs)
        ):
            status = "needs-editor-review"
        else:
            status = "ready-for-editor"
        rendered.append(
            IntegratedPreviewRow(
                resolved.external_id,
                original.get("question", original.get("title", "")),
                original.get("prepared_clip_url", ""),
                status,
                draft is not None,
                refs,
                len(report["findings"]),
            )
        )
    return tuple(rendered)
