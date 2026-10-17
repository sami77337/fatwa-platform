"""Foundation storage probe only, NOT an E1 intake/replay/review implementation."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))
os.environ["DJANGO_SETTINGS_MODULE"] = "config.settings.wave7_test"


def inspect_batch(key):
    from apps.intake_workflow.models import IntakeBatch, IntakeItem, IntakeReference, ReviewEvent
    batch = IntakeBatch.objects.get(idempotency_key=key)
    raw = bytes(batch.original_payload)
    return {"batch_id": str(batch.pk), "payload_sha256": batch.payload_sha256,
            "raw_sha256": hashlib.sha256(raw).hexdigest(), "raw_text": raw.decode("utf-8"),
            "payload_snapshot": batch.payload_snapshot,
            "items": list(IntakeItem.objects.filter(batch=batch).values(
                "row_ordinal", "external_id", "question_original", "original_row", "source_byte_start",
                "source_byte_end", "intake_status", "review_status")),
            "references": list(IntakeReference.objects.filter(intake_item__batch=batch).order_by(
                "intake_item__row_ordinal", "reference_ordinal").values(
                "original_pointer", "source_byte_start", "source_byte_end", "reference_status", "citation_text")),
            "event_count": ReviewEvent.objects.filter(intake_item__batch=batch).count()}


def create_foundation_probe(key):
    from apps.intake_workflow import contracts as c, fixtures as f
    from apps.intake_workflow.guards import synthetic_atomic
    from apps.intake_workflow.models import IntakeBatch, IntakeItem, IntakeReference
    parsed = c.parse_synthetic_payload(f.synthetic_payload(), synthetic_fixtures_only=True)
    # No D1/D3/E1/E2 service result is invented here. Every row remains RECEIVED.
    with synthetic_atomic(synthetic_fixtures_only=True):
        batch = IntakeBatch.objects.create(idempotency_key=key, original_payload=parsed.raw,
                                          payload_sha256=parsed.payload_sha256)
        for ordinal, (row, source) in enumerate(zip(parsed.items, parsed.item_sources, strict=True), 1):
            row_object = row if isinstance(row, dict) else {}
            item = IntakeItem.objects.create(batch=batch, row_ordinal=ordinal,
                external_id=c.valid_external_id(row_object.get("external_id")),
                question_original=row_object.get("question") if isinstance(row_object.get("question"), str) else None,
                original_row=source.text, source_byte_start=source.start, source_byte_end=source.end)
            for reference_ordinal, pointer in enumerate(parsed.reference_sources[ordinal-1], 1):
                IntakeReference.objects.create(intake_item=item, reference_ordinal=reference_ordinal,
                    original_pointer=pointer.text, source_byte_start=pointer.start, source_byte_end=pointer.end)
    return inspect_batch(key)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=["create", "inspect"])
    parser.add_argument("--key", required=True)
    args = parser.parse_args()
    import django
    django.setup()
    from target import select_existing_test_database
    select_existing_test_database()
    result = create_foundation_probe(args.key) if args.action == "create" else inspect_batch(args.key)
    print(json.dumps(result, ensure_ascii=False))  # metadata/text only; never rewrite source values


if __name__ == "__main__":
    main()
