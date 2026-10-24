"""Preview acknowledged synthetic files offline, or run the inline example."""

import argparse
import hashlib
import json
import sys
from pathlib import Path

from apps.fatwa_drafts.intake import ValidationError
from tools.content_intake.cli import MAX_BYTES, MAX_ROWS

from . import prepare_batch
from .batches import BatchCollection, PreparedBatch, PreparedInput, prepare_batches


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--json", action="store_true", help="Deterministic machine report")
    parser.add_argument(
        "--synthetic-fixtures-only",
        action="store_true",
        help="Acknowledge supplied files contain only synthetic fixtures",
    )
    parser.add_argument("inputs", type=Path, nargs="*", help="Synthetic CSV, JSON or JSONL files")
    args = parser.parse_args(argv)
    if args.inputs:
        if not args.synthetic_fixtures_only:
            parser.error("file inputs require --synthetic-fixtures-only")
        return _files(args.inputs)
    raw = json.dumps(
        {
            "schema": "fatwa.prepared-intake.v1",
            "items": [
                {
                    "external_id": "synthetic-001",
                    "question": "سؤال تجريبي بلا جواب أو حكم",
                    "prepared_clip_url": "https://example.invalid/finished-synthetic.mp4",
                    "reference_links": [
                        {"source_id": "synthetic-source", "heading_id": "synthetic-heading"}
                    ],
                },
                {"external_id": "synthetic-002", "question": "سؤال تجريبي ينتظر رابط المقطع"},
            ],
        },
        ensure_ascii=False,
    ).encode("utf-8")
    batch = prepare_batch(raw, synthetic_fixtures_only=True)
    sys.stdout.buffer.write(
        batch.json_bytes() if args.json else (batch.preview_ar() + "\n").encode("utf-8")
    )
    return 0


def _files(paths):
    try:
        if len(paths) > MAX_ROWS:
            raise ValidationError("collection: expected_at_most_1000_inputs")
        inputs, errors, order, byte_count = [], {}, [], 0
        for number, path in enumerate(paths, 1):
            # Ordinal identities remain bounded and unique even for equal filenames.
            identity = f"input-{number:04d}"
            order.append(identity)
            suffix = path.suffix.lower()
            try:
                with path.open("rb") as stream:
                    raw = stream.read(MAX_BYTES + 1)
            except OSError:
                errors[identity] = PreparedBatch(
                    identity, None, suffix, error_code="SOURCE_READ_FAILED"
                )
                continue
            byte_count += len(raw)
            if byte_count > MAX_BYTES:
                raise ValidationError("collection: input_byte_limit_exceeded")
            if suffix not in (".csv", ".json", ".jsonl"):
                errors[identity] = PreparedBatch(
                    identity,
                    hashlib.sha256(raw).hexdigest(),
                    suffix,
                    error_code="UNSUPPORTED_FORMAT",
                )
                continue
            inputs.append(PreparedInput(identity, raw, suffix))
        collection = prepare_batches(inputs, synthetic_fixtures_only=True)
        by_id = {entry.batch_id: entry for entry in collection.batches} | errors
        collection = BatchCollection(tuple(by_id[identity] for identity in order))
        sys.stdout.buffer.write(collection.json_bytes())
        return 1 if collection.has_errors else 0
    except ValidationError:
        # Do not include paths, source text, or exception strings in file errors.
        report = dict(
            status="ERROR",
            error_code="COLLECTION_LIMIT_EXCEEDED",
            synthetic_only=True,
            human_editing_performed=False,
        )
        sys.stdout.buffer.write(
            (json.dumps(report, sort_keys=True, separators=(",", ":")) + "\n").encode()
        )
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
