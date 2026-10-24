"""Synthetic-only offline batch reconciliation; no network, database or public upload."""

import argparse
import json
import sys
from pathlib import Path

from apps.fatwa_drafts.intake import ValidationError
from apps.prepared_pipeline.batches import PreparedInput
from apps.prepared_pipeline.diagnostics import diagnose_batches

from .cli import MAX_BYTES, MAX_ROWS


def _check_artifact(path: Path, expected: bytes) -> bool:
    # A corrupted bundle must not cause an unbounded local read.
    with path.open("rb") as stream:
        return stream.read(len(expected) + 1) == expected


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--synthetic-fixtures-only", action="store_true", required=True)
    parser.add_argument(
        "--batch",
        nargs=2,
        action="append",
        default=[],
        metavar=("ID", "FILE"),
        help="Explicit batch identity and local CSV/JSON/JSONL path; repeatable",
    )
    parser.add_argument("--expect-batch", action="append", default=[], metavar="ID")
    inventory = parser.add_mutually_exclusive_group()
    inventory.add_argument(
        "--source-id",
        action="append",
        metavar="ID",
        help="Explicit available source identity; repeatable, grants no trust",
    )
    inventory.add_argument("--empty-source-inventory", action="store_true")
    output = parser.add_mutually_exclusive_group()
    output.add_argument("--preview", action="store_true", help="Arabic recovery instructions")
    output.add_argument(
        "--show-row",
        nargs=2,
        metavar=("BATCH", "ROW"),
        help="Navigate to one original row and its duplicate locations",
    )
    output.add_argument(
        "--export-bundle", type=Path, help="New directory beneath current directory"
    )
    output.add_argument("--check-bundle", type=Path, help="Verify all four deterministic artifacts")
    args = parser.parse_args(argv)
    try:
        if not args.batch and not args.expect_batch:
            raise ValidationError("collection: batch_or_expectation_required")
        if len(args.batch) > MAX_ROWS:
            raise ValidationError("collection: expected_at_most_1000_inputs")
        sources, byte_count = [], 0
        for identity, filename in args.batch:
            path = Path(filename)
            # Validate the descriptor before reading; paths never appear in reports.
            PreparedInput(identity, b"", path.suffix.lower())
            with path.open("rb") as stream:
                raw = stream.read(MAX_BYTES - byte_count + 1)
            byte_count += len(raw)
            if byte_count > MAX_BYTES:
                raise ValidationError("collection: input_byte_limit_exceeded")
            sources.append(PreparedInput(identity, raw, path.suffix.lower()))
        result = diagnose_batches(
            sources,
            synthetic_fixtures_only=True,
            available_source_ids=[] if args.empty_source_inventory else args.source_id,
            expected_batch_ids=args.expect_batch,
        )
        if args.export_bundle or args.check_bundle:
            artifacts = result.artifacts()
            if args.check_bundle:
                if any(
                    not _check_artifact(args.check_bundle / name, data)
                    for name, data in artifacts.items()
                ):
                    raise ValidationError("bundle: deterministic_output_mismatch")
            else:
                target = args.export_bundle.resolve()
                root = Path.cwd().resolve()
                if not target.is_relative_to(root) or target == root:
                    raise ValidationError("bundle: new_directory_beneath_cwd_required")
                target.mkdir(exist_ok=False)
                for name, data in artifacts.items():
                    with (target / name).open("xb") as stream:
                        stream.write(data)
        if args.show_row:
            try:
                number = int(args.show_row[1])
            except ValueError:
                raise ValidationError("navigation: batch_and_positive_row_required") from None
            content = result.preview_ar(batch_id=args.show_row[0], row_number=number).encode(
                "utf-8"
            )
        else:
            content = result.preview_ar().encode("utf-8") if args.preview else result.json_bytes()
        sys.stdout.buffer.write(content)
        return int(result.has_errors)
    except OSError:
        code = "LOCAL_FILE_OPERATION_FAILED"
    except ValidationError as exc:
        # Validation errors contain fixed contract codes, never payloads or paths.
        code = str(exc)
    report = dict(
        status="ERROR",
        error_code=code,
        synthetic_only=True,
        recovery_ar="راجع الملفات المحلية وحدود الإدخال ومجلد التصدير؛ لا تستبدل الأصل أو حزمة سابقة.",
        gates={"B": "NOT_PASSED", "C": "HOLD", "D": "HOLD", "E": "HOLD"},
        phase01="BLOCKED",
        scope="SCOPE_DEVIATION_HOLD",
        deployment="NOT_DEPLOYED",
    )
    sys.stdout.buffer.write(
        (json.dumps(report, ensure_ascii=False, sort_keys=True) + "\n").encode()
    )
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
