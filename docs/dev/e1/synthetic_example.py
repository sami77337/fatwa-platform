"""Exact, invented E1/E2 handoff inputs. No owner source or external I/O."""
from dataclasses import asdict
import json
import sys

from apps.fatwa_drafts.intake import ReferenceLink
from apps.prepared_pipeline import C1Pointer, ExplicitMapping, prepare_batch
from apps.reference_links.bridge import BridgeConfig, EditionMap, HeadingMap, SourceIdentity
from apps.reference_links.resolution import Heading, SnapshotCatalog


def build_inputs():
    identity = SourceIdentity("synthetic-e1-only", "622", "invented-edition", "a" * 64, "b" * 64)
    headings = (HeadingMap("synthetic-source", "opaque-heading", "opaque-c2-valid", 9),
                HeadingMap("mismatched-source", "opaque-other", "opaque-c2-mismatch", 10))
    bridge_config = BridgeConfig(EditionMap(identity, 7), headings)
    reference_map = {
        C1Pointer(h.c1_source_id, h.c1_heading_id): ExplicitMapping(
            ReferenceLink(**asdict(identity), source_id=h.c2_source_id),
            7, h.source_row_id, "Wave6ContractTests.test_published_synthetic_example")
        for h in headings
    }
    catalog = SnapshotCatalog([
        Heading(7, h.source_row_id, "مرجع اصطناعي", "باب اصطناعي", "الأول", 12,
                ("باب اصطناعي",), namespace, "622", "b" * 64)
        for h, namespace in zip(headings, (identity.source_namespace, "different-namespace"), strict=True)
    ])
    question = " \tسُؤالٌ اصطناعيّ\r\nالسطرُ الثاني\n  "
    def row(external_id, **changes):
        return {"external_id": external_id, "question": question,
                "prepared_clip_url": "https://example.invalid/finished.mp4", **changes}
    def pointer(h):
        return {"source_id": h.c1_source_id, "heading_id": h.c1_heading_id}
    rows = [
        row("SYN-E1-valid", reference_links=[pointer(headings[0])], staff_notes=" ملاحظةٌ\t\n "),
        row("SYN-E1-missing", prepared_clip_url=""),
        row("SYN-E1-invalid", prepared_clip_url="https://example.invalid:444/a"),
        row("SYN-E1-duplicate"), row("SYN-E1-duplicate"),
        row("SYN-E1-unmapped", reference_links=[{"source_id": "unknown", "heading_id": "unknown"}]),
        row("SYN-E1-mismatch", reference_links=[pointer(headings[1])]),
    ]
    raw = json.dumps({"schema": "fatwa.prepared-intake.v1", "items": rows}, ensure_ascii=False,
                     sort_keys=True, separators=(",", ":")).encode("utf-8")
    return raw, reference_map, bridge_config, catalog


if __name__ == "__main__":
    raw, reference_map, _, catalog = build_inputs()
    sys.stdout.buffer.write(prepare_batch(raw, synthetic_fixtures_only=True,
                                         reference_map=reference_map, catalog=catalog).json_bytes())
