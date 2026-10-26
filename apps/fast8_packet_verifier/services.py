"""Read-only diagnostics anchored in the existing canonical synthetic export.

No caller-selected fixture, external-ID join, database, source discovery or
network access. Hashes are integrity evidence, never signatures or approvals.
"""

import json
from collections import Counter
from hashlib import sha256

from apps.editorial_export import services as export
from apps.editorial_workbench import packets


class PacketVerificationError(ValueError):
    """A stable, content-free fail-closed code; no partial success receipt."""

    def __init__(self, code: str):
        self.code = "packet_verify: " + code
        super().__init__(self.code)


def require_development(synthetic_fixtures_only: bool) -> None:
    try:
        export.require_development(synthetic_fixtures_only)
    except export.ExportError as exc:
        raise PacketVerificationError("synthetic_development_only") from exc


def _fail(code: str) -> None:
    raise PacketVerificationError(code)


def _pairs(pairs: list[tuple[str, object]]) -> dict:
    result = {}
    for key, value in pairs:
        if key in result:
            _fail("duplicate_key")
        result[key] = value
    return result


def _constant(_value: str) -> None:
    _fail("invalid_json")


def _decode(raw: bytes, *, manifest: bool = False) -> dict:
    limit = export.MAX_FILE_BYTES if manifest else packets.MAX_PACKET_BYTES
    if type(raw) is not bytes:
        _fail("invalid_input_type")
    if len(raw) > limit:
        _fail("byte_limit")
    try:
        value = json.loads(
            raw.decode("utf-8", errors="strict"),
            object_pairs_hook=_pairs,
            parse_constant=_constant,
        )
        if type(value) is not dict:
            _fail("invalid_payload")
        canonical = export.encode_json(value) if manifest else packets.serialize_packet(value)
    except UnicodeError as exc:
        raise PacketVerificationError("invalid_utf8") from exc
    except RecursionError as exc:
        raise PacketVerificationError("structure_limit") from exc
    except (packets.PacketDataError, export.ExportError) as exc:
        # Both authoritative serializers use fixed, content-free error codes.
        raise PacketVerificationError(str(exc).split(": ", 1)[-1]) from exc
    except ValueError as exc:
        if isinstance(exc, PacketVerificationError):
            raise
        raise PacketVerificationError("invalid_json") from exc
    if raw != canonical:
        _fail("noncanonical_manifest" if manifest else "noncanonical_packet")
    return value


def _same(left: object, right: object) -> bool:
    # JSON bool/int equality must never make True an acceptable ordinal 1.
    return export.encode_json(left) == export.encode_json(right)


def _sequence(actual: object, expected: list, field: str, code: str) -> None:
    if type(actual) is not list or any(type(item) is not dict for item in actual):
        _fail("invalid_contract")
    if len(actual) < len(expected):
        _fail(code + "_missing")
    if len(actual) > len(expected):
        _fail(code + "_extra")
    keys = [export.encode_json(item[field]) for item in actual]
    expected_keys = [export.encode_json(item[field]) for item in expected]
    if keys != expected_keys:
        _fail(
            code
            + (
                "_order_mismatch"
                if Counter(keys) == Counter(expected_keys)
                else "_identity_mismatch"
            )
        )


def _source(actual: dict, expected: dict) -> None:
    for text, digest in (("input_text", "input_sha256"), ("text", "text_sha256")):
        if type(actual[text]) is not str:
            _fail("invalid_contract")
        if sha256(actual[text].encode("utf-8")).hexdigest() != actual[digest]:
            _fail("source_digest_mismatch")
    if actual["kind"] == "original_utf8_slice":
        start, end = actual["start"], actual["end"]
        raw = actual["input_text"].encode("utf-8")
        if (
            type(start) is not int
            or type(end) is not int
            or not 0 <= start < end <= len(raw)
            or raw[start:end] != actual["text"].encode("utf-8")
            or actual["offset_unit"] != "utf8_bytes_end_exclusive"
        ):
            _fail("source_slice_mismatch")
    if not _same(actual, expected):
        _fail("source_identity_mismatch")


def verify_packet(
    packet_bytes: bytes,
    manifest_bytes: bytes,
    *,
    case_key: str,
    synthetic_fixtures_only: bool = False,
) -> bytes:
    """Verify ONE default-selection exported packet and its unchanged manifest.

    Explicit case_key pins intent independently of the input. Only this checkout's
    fixed fixture keys are allowed. The manifest is replayed in full, but no claim
    is made about absent report/CSV files: use verify_export for an entire bundle.
    Return bounded canonical JSON without source text, or raise one exact code.
    """
    require_development(synthetic_fixtures_only)
    packet = _decode(packet_bytes)
    manifest = _decode(manifest_bytes, manifest=True)
    try:
        bundle = export.build_export(synthetic_fixtures_only=True)
    except (ValueError, TypeError) as exc:
        raise PacketVerificationError("fixture_replay_unavailable") from exc
    expected_entries = bundle.report()["cases"]
    entry = (
        next((e for e in expected_entries if e["packet"]["identity"]["case_key"] == case_key), None)
        if type(case_key) is str
        else None
    )
    if entry is None:
        _fail("unknown_case")
    expected = entry["packet"]
    expected_manifest = json.loads(bundle.file("manifest.json"))
    try:
        if set(packet) != set(expected):
            _fail("packet_fields_mismatch")
        if not _same(packet["identity"], expected["identity"]):
            _fail("case_identity_mismatch")
        _source(packet["source"], expected["source"])
        _sequence(packet["snapshots"], expected["snapshots"], "number", "revision")
        revision_digests = []
        for actual, original in zip(packet["snapshots"], expected["snapshots"], strict=True):
            digest = sha256(packets.serialize_packet(actual)).hexdigest()
            if digest != sha256(packets.serialize_packet(original)).hexdigest():
                _fail("revision_digest_mismatch")
            revision_digests.append({"number": actual["number"], "sha256": digest})
        _sequence(
            packet["snapshot_observations"],
            expected["snapshot_observations"],
            "revision",
            "observation",
        )
        if not _same(packet["snapshot_observations"], expected["snapshot_observations"]):
            _fail("observation_record_mismatch")
        references = packet["reference_verification"]["results"]
        original_references = expected["reference_verification"]["results"]
        _sequence(references, original_references, "reference_ordinal", "reference")
        if not _same(references, original_references):
            _fail("reference_record_mismatch")
        if packet_bytes != packets.serialize_packet(expected):
            _fail("packet_replay_mismatch")
        # Full identities preserve row/batch/source membership, including rows
        # with duplicate external IDs. Never collapse these into an ID-keyed map.
        members = manifest["case_inputs"]
        _sequence(members, expected_manifest["case_inputs"], "identity", "manifest")
        index = next(i for i, e in enumerate(expected_entries) if e is entry)
        member = members[index]
        digest = sha256(packet_bytes).hexdigest()
        if member["packet_sha256"] != digest:
            _fail("packet_digest_mismatch")
        if not _same(member, expected_manifest["case_inputs"][index]):
            _fail("manifest_member_mismatch")
        if manifest_bytes != bundle.file("manifest.json"):
            _fail("manifest_replay_mismatch")
    except (KeyError, TypeError, IndexError, export.ExportError, packets.PacketDataError) as exc:
        raise PacketVerificationError("invalid_contract") from exc
    return export.encode_json(
        {
            "schema": "synthetic-single-packet-verification.v1",
            "status": "VERIFIED",
            "synthetic_only": True,
            "case_key": case_key,
            "packet_sha256": digest,
            "manifest_sha256": sha256(manifest_bytes).hexdigest(),
            "input_sha256": expected["source"]["input_sha256"],
            "source_text_sha256": expected["source"]["text_sha256"],
            "revision_digests": revision_digests,
            "reference_ordinals": [r["reference_ordinal"] for r in references],
            "verification": "exact fixed-synthetic packet and manifest replay; no bundle-file verification or scholarly approval",
            "holds": export.HOLDS,
            "owner_policy": "U03/U10 OWNER_APPROVAL_PENDING",
        }
    )
