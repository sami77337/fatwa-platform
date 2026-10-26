"""Verify pinned synthetic receipt declarations, never archive contents.

The external digest is a caller trust anchor, not an owner signature. A verified
receipt says nothing about whether its declared sources exist or are authentic.
"""

from __future__ import annotations

import json
import ntpath
import re
import unicodedata
from dataclasses import dataclass
from datetime import datetime, timedelta
from hashlib import sha256

from apps.source_readiness.service import MAX_MANIFEST_BYTES, parse_manifest

BASE_SHA = "92fa517ecdefe3f1a92a1ab145ff55943474df44"
SCHEMA = "fatwa.synthetic-source-receipt.v1"
MAX_SOURCES = 32
MAX_DECLARED_BYTES = 2**63 - 1


@dataclass(frozen=True)
class Verdict:
    status: str
    reasons: tuple[str, ...] = ()
    receipt_sha256: str | None = None
    source_count: int = 0

    def as_dict(self) -> dict:
        verified = self.status == "RECEIPT_VERIFIED"
        return {
            "schema": "fatwa.synthetic-source-receipt-report.v1",
            "status": self.status,
            "reasons": list(self.reasons),
            "receipt_sha256": self.receipt_sha256,
            "source_count": self.source_count,
            "receipt_fields": "VERIFIED_AGAINST_CALLER_PIN" if verified else "NOT_VERIFIED",
            "declaration_scope": "LOCALLY_FABRICATED_SYNTHETIC_ONLY",
            "source_bytes": "NOT_SUPPLIED",
            "owner_archives": "NOT_SUPPLIED",
            "archive_verification": "NOT_RUN",
            "heading_count_verification": "NOT_RUN",
            "ordering_verification": "NOT_RUN",
            "catalog_connection": "NOT_CONNECTED",
            "owner_acceptance": "NOT_RUN",
            "gates": {
                "B": "NOT_PASSED",
                "C": "HOLD",
                "D": "HOLD",
                "E": "HOLD",
                "Phase01": "BLOCKED",
                "scope": "SCOPE_DEVIATION_HOLD",
                "deployment": "NOT_DEPLOYED",
                "U03_U10": "OWNER_APPROVAL_PENDING",
            },
        }


def _reject(code: str) -> None:
    raise ValueError(code)


def _object(pairs: list[tuple[str, object]]) -> dict:
    result = {}
    for key, value in pairs:
        if key in result:
            _reject("duplicate_json_key")
        result[key] = value
    return result


def _fields(value: object, names: set[str]) -> None:
    if type(value) is not dict or set(value) != names:
        _reject("invalid_fields")


def _digest(value: object, length: int = 64) -> bool:
    return type(value) is str and re.fullmatch(r"[0-9a-f]{%d}" % length, value) is not None


def _identifier(value: object) -> bool:
    return (
        type(value) is str and re.fullmatch(r"synthetic-[a-z0-9][a-z0-9-]{0,99}", value) is not None
    )


def _time(value: object) -> datetime:
    if (
        type(value) is not str
        or re.fullmatch(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z", value) is None
    ):
        _reject("invalid_timestamp")
    try:
        return datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ")
    except ValueError:
        raise ValueError("invalid_timestamp") from None


def _basename(value: object) -> str:
    if (
        type(value) is not str
        or not 1 <= len(value) <= 255
        or value != value.strip()
        or value.endswith(".")
        or any(char in value for char in '/\\:<>"|?*%')
        or any(unicodedata.category(char).startswith("C") for char in value)
        or value in (".", "..")
        or ntpath.isreserved(value)
        or not value.startswith("synthetic-")
    ):
        _reject("unsafe_logical_name")
    return value


def _unique(value: str, seen: set[str]) -> None:
    # Compare potential aliases without changing the original declaration.
    key = unicodedata.normalize("NFC", value).casefold()
    if key in seen:
        _reject("ambiguous_source_identity")
    seen.add(key)


def _validate(data: object, as_of: datetime, expected_revision: str) -> int:
    _fields(
        data,
        {"schema", "fabrication", "receipt_id", "base_sha", "issued_at", "expires_at", "sources"},
    )
    if data["schema"] != SCHEMA or data["fabrication"] != "EXPLICIT_LOCAL_SYNTHETIC":
        _reject("explicit_synthetic_receipt_required")
    if not _identifier(data["receipt_id"]):
        _reject("invalid_receipt_id")
    if not _digest(data["base_sha"], 40) or data["base_sha"] != expected_revision:
        _reject("stale_base_revision")
    issued, expires = _time(data["issued_at"]), _time(data["expires_at"])
    if not issued < expires <= issued + timedelta(days=7):
        _reject("invalid_validity_window")
    if not issued <= as_of < expires:
        _reject("stale_or_future_receipt")
    sources = data["sources"]
    if type(sources) is not list or not 1 <= len(sources) <= MAX_SOURCES:
        _reject("invalid_source_count")
    identities = {
        key: set()
        for key in ("archive", "edition", "dataset", "name", "edition_id", "archive_sha256")
    }
    for entry in sources:
        _fields(
            entry,
            {
                "archive_id",
                "archive_name",
                "archive_size_bytes",
                "input_size_bytes",
                "ordering_claim",
                "manifest",
            },
        )
        if not _identifier(entry["archive_id"]):
            _reject("invalid_archive_id")
        name = _basename(entry["archive_name"])
        if not name.endswith(".zip"):
            _reject("invalid_archive_extension")
        for field in ("archive_size_bytes", "input_size_bytes"):
            if type(entry[field]) is not int or not 1 <= entry[field] <= MAX_DECLARED_BYTES:
                _reject("invalid_declared_size")
        # Public existing validator owns CatalogSpec and source identity rules.
        try:
            manifest = parse_manifest(
                json.dumps(entry["manifest"], ensure_ascii=True).encode("ascii")
            )
        except (ValueError, TypeError, OverflowError):
            raise ValueError("invalid_readiness_manifest") from None
        spec = manifest["spec"]
        if manifest["source_kind"] != "synthetic":
            _reject("owner_source_not_allowed")
        if not _identifier(manifest["dataset_id"]) or not _identifier(spec["edition_key"]):
            _reject("invalid_synthetic_identity")
        if spec["expected_rows"] < spec["expected_roots"] + spec["expected_max_depth"] - 1:
            _reject("inconsistent_heading_counts")
        _basename(spec["input_name"])
        for kind, value in (
            ("archive", entry["archive_id"]),
            ("name", name),
            ("edition", spec["edition_key"]),
            ("dataset", manifest["dataset_id"]),
            ("edition_id", str(manifest["edition_id"])),
            ("archive_sha256", spec["source_archive_sha256"]),
        ):
            _unique(value, identities[kind])
        # No new heading interpretation: bind an explicit order declaration to
        # the existing input digest and expected heading count, without rows.
        order = entry["ordering_claim"]
        _fields(order, {"kind", "heading_count", "input_sha256"})
        if (
            order["kind"] != "source_order_unique_ascending"
            or type(order["heading_count"]) is not int
            or order["heading_count"] != spec["expected_rows"]
            or order["input_sha256"] != spec["source_input_sha256"]
        ):
            _reject("ordering_claim_mismatch")
    return len(sources)


def verify_receipt(
    receipt: bytes | None,
    *,
    expected_sha256: str | None = None,
    as_of: str | None = None,
    expected_revision: str = BASE_SHA,
) -> Verdict:
    """Pure, deterministic receipt validation. No file, database or network I/O.

    Pin exact UTF-8 bytes externally, including line endings; never normalize the
    receipt before hashing. Missing evidence is not source acceptance.
    """
    if receipt is None:
        return Verdict("NOT_RUN", ("receipt_not_supplied",))
    if type(receipt) is not bytes or len(receipt) > MAX_MANIFEST_BYTES:
        return Verdict("FAIL", ("invalid_receipt_size",))
    observed = sha256(receipt).hexdigest()
    if expected_sha256 is None or as_of is None:
        return Verdict("BLOCKED", ("external_pin_and_as_of_required",), observed)
    if not _digest(expected_sha256) or not _digest(expected_revision, 40):
        return Verdict("FAIL", ("invalid_trust_anchor",), observed)
    if observed != expected_sha256:
        return Verdict("FAIL", ("receipt_sha256_mismatch",), observed)
    try:
        data = json.loads(
            receipt.decode("utf-8"),
            object_pairs_hook=_object,
            parse_constant=lambda _: _reject("nonfinite_json_number"),
        )
        count = _validate(data, _time(as_of), expected_revision)
    except (UnicodeError, RecursionError, json.JSONDecodeError):
        return Verdict("FAIL", ("invalid_receipt_json",), observed)
    except (ValueError, TypeError, OverflowError):
        # Do not echo attacker-controlled values, paths or parser exception text.
        return Verdict("FAIL", ("receipt_contract_invalid",), observed)
    return Verdict("RECEIPT_VERIFIED", receipt_sha256=observed, source_count=count)
