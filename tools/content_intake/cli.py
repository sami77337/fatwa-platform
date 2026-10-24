"""Stdlib-only prepared intake CLI. All row numbers are one-based record ordinals."""

import argparse
import csv
import hashlib
import io
import json
import sys
import unicodedata
from collections import Counter
from pathlib import Path
from urllib.parse import urlsplit

SCHEMA = "fatwa.prepared-intake.v1"
MAX_BYTES = 1_000_000
MAX_ROWS = 1000
MAX_REFERENCES = 100
FIELDS = {"external_id", "question", "title", "prepared_clip_url", "staff_notes", "reference_links"}
LINK_FIELDS = {"source_id", "heading_id"}
TEXT_LIMITS = {"external_id": 100, "question": 20000, "title": 20000,
               "prepared_clip_url": 2048, "staff_notes": 20000}


class CSVRow(dict):
    """Keep malformed CSV cells intact and diagnostics outside submitted fields."""

    def __init__(self, row):
        super().__init__(row)
        self.missing_cells = tuple(field for field, value in row.items()
                                   if field is not None and value is None)


def csv_rows(reader):
    for row in reader:
        yield CSVRow(row) if None in row or None in row.values() else row


def encoded(value):
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n").encode("utf-8")


def digest(data):
    return hashlib.sha256(data).hexdigest()


def unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def parse_json(text):
    try:
        value = json.loads(text, object_pairs_hook=unique_object,
                           parse_constant=lambda value: (_ for _ in ()).throw(ValueError(value)))
        # Escaped lone surrogates can decode successfully, including in blocked rows.
        json.dumps(value, ensure_ascii=False, allow_nan=False).encode("utf-8", errors="strict")
    except RecursionError as exc:
        raise ValueError("JSON nesting exceeds parser bounds") from exc
    return value


def bounded_rows(rows):
    result = []
    for number, row in enumerate(rows, 1):
        if number > MAX_ROWS:
            raise ValueError("items: expected_at_most_1000")
        result.append(row)
    return result


def load(raw, suffix):
    if not isinstance(raw, bytes) or len(raw) > MAX_BYTES:
        raise ValueError("input: invalid_size_or_type")
    text = raw.decode("utf-8-sig", errors="strict")
    if suffix == ".csv":
        reader = csv.DictReader(io.StringIO(text, newline=""), strict=True)
        headers = reader.fieldnames
        if not headers or len(headers) != len(set(headers)) or set(headers) - FIELDS:
            raise ValueError("missing, duplicate or unknown CSV columns")
        return bounded_rows(csv_rows(reader))
    if suffix == ".jsonl":
        # Only physical CR/LF delimit records. Unicode separators inside JSON
        # strings are original question text, not JSONL record boundaries.
        return bounded_rows(parse_json(line) for line in io.StringIO(text, newline="") if line.strip())
    if suffix != ".json":
        raise ValueError("input extension must be .csv, .json or .jsonl")
    value = parse_json(text)
    if isinstance(value, dict):
        if set(value) != {"schema", "items"} or value["schema"] != SCHEMA:
            raise ValueError("invalid prepared-intake envelope")
        value = value["items"]
    if not isinstance(value, list):
        raise ValueError("JSON input must be an array or prepared-intake envelope")
    return bounded_rows(value)


def valid_url(value):
    try:
        url = urlsplit(value)
        return (url.scheme in {"http", "https"} and bool(url.hostname)
                and url.username is None and url.password is None
                and url.port != 0 and not url.fragment
                and not any(c.isspace() or unicodedata.category(c).startswith("C") for c in value)
                and "\\" not in value)
    except ValueError:
        return False


def normalize(rows):
    """Validate C1 rows; canonical original strings are never trimmed or searched."""
    rows = bounded_rows(rows)
    items, findings = [], []
    # Count original, typed identities before accepting any row. A later invalid
    # row cannot leave its earlier duplicate eligible for downstream intake.
    identities = Counter(row["external_id"] for row in rows
                         if isinstance(row, dict) and isinstance(row.get("external_id"), str))

    def finding(row, field, code, severity="error"):
        findings.append(dict(row=row, field=field, code=code, severity=severity))

    for number, row in enumerate(rows, 1):
        start = len(findings)
        if not isinstance(row, dict):
            finding(number, "", "record_must_be_object")
            continue
        if set(row) - FIELDS:
            finding(number, "", "unknown_columns_or_extra_cells")
        if isinstance(row, CSVRow):
            for field in row.missing_cells:
                finding(number, field, "csv_missing_cell")
            if None in row:
                finding(number, "", "csv_extra_cells")
        item = {}
        for field in ("external_id", "question", "prepared_clip_url", "staff_notes", "title"):
            if field == "title" and field not in row:
                continue
            value = row.get(field, "")
            if field == "question" and "question" not in row:
                value = row.get("title", "")
            if not isinstance(value, str):
                finding(number, field, "must_be_string")
                value = ""
            if len(value) > TEXT_LIMITS[field]:
                finding(number, field, f"too_long_max_{TEXT_LIMITS[field]}")
            # Prepared text keeps tabs/newlines; IDs follow D3's strict control rule.
            invalid_id_control = field == "external_id" and any(
                ord(c) < 32 or ord(c) == 127 for c in value)
            if invalid_id_control or any(
                    unicodedata.category(c) == "Cs" or (ord(c) < 32 and c not in "\n\r\t") for c in value):
                finding(number, field, "invalid_unicode_or_control")
            if field != "title":
                item[field] = value
            if field == "external_id" and value != value.strip():
                finding(number, field, "id_whitespace_not_allowed")
        if "title" in row:
            if not isinstance(row["title"], str) or not row["title"].strip():
                finding(number, "title", "blank_or_invalid_title")
            elif "question" in row and row["title"] != row["question"]:
                finding(number, "title", "ambiguous_title_question")
        for field in ("external_id", "question"):
            if not item[field].strip():
                finding(number, field, "required")
        identity = row.get("external_id")
        if isinstance(identity, str) and identities[identity] > 1:
            finding(number, "external_id", "duplicate_id")
        url = item["prepared_clip_url"]
        if not url:
            finding(number, "prepared_clip_url", "media_link_missing_review_required", "review")
        elif not valid_url(url):
            finding(number, "prepared_clip_url", "invalid_http_url")
        links = row.get("reference_links", [])
        if isinstance(links, str):
            try:
                links = parse_json(links) if links.strip() else []
            except ValueError:
                links = None
        if isinstance(links, list) and len(links) > MAX_REFERENCES:
            finding(number, "reference_links", "expected_list_at_most_100")
            links = []
        elif not isinstance(links, list) or any(
            not isinstance(link, dict) or set(link) != LINK_FIELDS
            or any(not isinstance(v, str) or not v.strip() or v != v.strip()
                   or any(unicodedata.category(c).startswith("C") for c in v)
                   for v in link.values())
            for link in (links if isinstance(links, list) else [])
        ):
            finding(number, "reference_links", "expected_source_id_heading_id_string_pairs")
            links = []
        item["reference_links"] = links
        for field, value in item.items():
            if isinstance(value, str) and value.lstrip().startswith(("=", "+", "-", "@")):
                finding(number, field, "spreadsheet_formula_text_preserved", "review")
        if not any(f["severity"] == "error" for f in findings[start:]):
            items.append(item)
    return items, findings


def artifacts(raw, suffix):
    rows = load(raw, suffix)
    items, findings = normalize(rows)
    envelope = encoded({"schema": SCHEMA, "items": items})
    lines = b"".join((json.dumps(item, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8") for item in items)
    outputs = {"intake.json": envelope, "intake.jsonl": lines}
    manifest = {"schema": SCHEMA, "input_sha256": digest(raw), "input_format": suffix,
                "row_count": len(rows), "valid_row_count": len(items), "findings": findings,
                "status": "INVALID" if any(f["severity"] == "error" for f in findings) else "REVIEW_REQUIRED" if findings else "VALID",
                "outputs": {name: {"sha256": digest(data), "bytes": len(data)} for name, data in outputs.items()}}
    return outputs, manifest


def main(argv=None):
    arguments = sys.argv[1:] if argv is None else list(argv)
    if arguments and arguments[0] == "diagnose":
        # Keep all historical C1 commands and their artifacts unchanged.
        from .diagnostic_cli import main as diagnose_main
        return diagnose_main(arguments[1:])
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("diagnose", help="Offline synthetic batch reconciliation (diagnose --help)")
    for name in ("validate", "preview", "export", "check"):
        command = sub.add_parser(name)
        command.add_argument("input", type=Path)
        if name in {"export", "check"}:
            command.add_argument("--bundle", type=Path, required=True)
    synthetic_check = sub.add_parser("wave7-check", help="Pure check of an acknowledged Wave7 synthetic batch")
    synthetic_check.add_argument("input",type=Path)
    synthetic_check.add_argument("--synthetic-fixtures-only",action="store_true")
    args = parser.parse_args(argv)
    if args.command == "wave7-check":
        # Lazy pure-only import: legacy C1 remains usable without Django setup.
        from apps.intake_workflow.contracts import ContractError
        from apps.intake_workflow.intake import check_intake
        try:
            if args.synthetic_fixtures_only is not True:
                raise ContractError('synthetic_acknowledgement_required')
            with args.input.open("rb") as stream:
                raw = stream.read(MAX_BYTES+1)
            report = check_intake(raw,synthetic_fixtures_only=True).report()
        except ContractError as exc:
            report = dict(status="ERROR",code=exc.code,status_code=exc.status_code)
        except OSError:
            report = dict(status="ERROR",code="SOURCE_READ_FAILED",status_code=400)
        sys.stdout.buffer.write(encoded(report))
        return 1 if report["status"] == "ERROR" else 0
    try:
        with args.input.open("rb") as stream:
            raw = stream.read(MAX_BYTES + 1)
        outputs, manifest = artifacts(raw, args.input.suffix.lower())
        if args.command == "check":
            expected = {**outputs, "manifest.json": encoded(manifest)}
            if any((args.bundle / name).read_bytes() != data for name, data in expected.items()):
                raise ValueError("bundle differs from deterministic input-derived output")
        elif args.command == "export" and manifest["status"] != "INVALID":
            target = args.bundle.resolve()
            root = Path.cwd().resolve()
            if not target.is_relative_to(root) or target == root:
                raise ValueError("bundle must be a new directory beneath the current working directory")
            target.mkdir(exist_ok=False)
            for name, data in {**outputs, "manifest.json": encoded(manifest)}.items():
                with (target / name).open("xb") as stream:
                    stream.write(data)
        if args.command == "preview":
            sys.stdout.buffer.write(encoded({"envelope": json.loads(outputs["intake.json"]),
                                             "manifest": manifest}))
        else:
            sys.stdout.buffer.write(encoded(manifest))
        return 1 if manifest["status"] == "INVALID" else 0
    except (OSError, ValueError, csv.Error, UnicodeError) as exc:
        sys.stdout.buffer.write(encoded({"status": "INVALID", "error": str(exc)}))
        return 1
