"""Pin a canonical case occurrence to one independently supplied catalog snapshot.

Only code-selected synthetic cases are supported. A match is technical evidence,
never source-owner acceptance, a scholarly citation decision, or authorization.
"""

import json
from contextlib import contextmanager
from dataclasses import asdict, dataclass

from django.core.exceptions import AppRegistryNotReady, ImproperlyConfigured

from apps.editorial_workbench.packets import CaseReviewPacket, serialize_packet
from apps.editorial_workbench.services import WorkbenchCase, build_prepared_workbench
from apps.fast8_case_references.services import _bind
from apps.fast8_fiqh_navigation.services import CatalogNavigation, CatalogReader, CatalogSnapshot
from apps.fiqh_reading_trail.services import ReadingTrail
from apps.intake_workflow.contracts import parse_synthetic_payload, validate_verified_identity
from apps.reference.records import MAX_BIGINT, PreparedCatalog
from apps.reference_links.resolution import KIND, CatalogReadError, Heading
from apps.reference_triage.services import build_investigation

HOLDS = (
    "Gate B NOT_PASSED",
    "C/D/E HOLD",
    "Phase01 BLOCKED",
    "SCOPE_DEVIATION_HOLD",
    "NOT_DEPLOYED",
    "U03/U10 OWNER_APPROVAL_PENDING",
)


@dataclass(frozen=True, slots=True)
class JoinRequest:
    case_key: str
    packet_sha256: str
    row_sha256: str
    reference_ordinal: int
    occurrence_sha256: str
    catalog_checksum: str
    edition_id: int
    source_row_id: int
    source_id: str


@dataclass(frozen=True, slots=True)
class JoinResult:
    json_bytes: bytes

    def payload(self) -> dict:
        return json.loads(self.json_bytes)


def _result(status: str, reason: str, joined: dict | None = None) -> JoinResult:
    return JoinResult(
        serialize_packet(
            {
                "schema": "fatwa.synthetic-case-source-join.v1",
                "synthetic_only": True,
                "kind": KIND,
                "status": status,
                "reason": reason,
                "join": joined,
                "owner_source": "NOT_CONNECTED",
                "source_acceptance": "NOT_RUN",
                "scholarly_acceptance": "NOT_RUN",
                "holds": HOLDS,
            }
        )
    )


def _validate_request(request: JoinRequest) -> None:
    if type(request) is not JoinRequest:
        raise ValueError("invalid_request")
    for field in ("case_key", "source_id"):
        value = getattr(request, field)
        if type(value) is not str or not 1 <= len(value) <= 100 or value != value.strip():
            raise ValueError("invalid_request")
    for field in ("packet_sha256", "row_sha256", "occurrence_sha256", "catalog_checksum"):
        digest = getattr(request, field)
        if (
            type(digest) is not str
            or len(digest) != 64
            or any(c not in "0123456789abcdef" for c in digest)
        ):
            raise ValueError("invalid_digest")
    for field in ("reference_ordinal", "edition_id", "source_row_id"):
        value = getattr(request, field)
        if type(value) is not int or not 1 <= value <= MAX_BIGINT:
            raise ValueError("invalid_identity")
    if request.reference_ordinal > 100:
        raise ValueError("invalid_ordinal")


class _SnapshotReader:
    """Reuse an already-open snapshot; never start a second physical transaction."""

    def __init__(self, value: CatalogSnapshot):
        self.value = value

    @contextmanager
    def snapshot(self, edition_id: int):
        yield self.value


class _StrictEvidence:
    def __init__(self, catalog):
        self.catalog = catalog

    def lookup(self, edition_id, source_row_id):
        rows = self.catalog.lookup(edition_id, source_row_id)
        for row in rows:
            if type(row) is not Heading or any(
                type(getattr(row, field)) is not int
                for field in ("edition_id", "source_row_id", "printed_page")
            ):
                raise ValueError("invalid_catalog_identity")
        return rows


def _original_occurrence(payload: dict, reference, ordinal: int) -> dict:
    """Reparse the original input, including exact row and reference byte spans."""
    source = payload["source"]
    if source["kind"] != "original_utf8_slice":
        raise ValueError("original_occurrence_required")
    raw = source["input_text"].encode("utf-8")
    parsed = parse_synthetic_payload(raw, synthetic_fixtures_only=True)
    rows = [
        i
        for i, row in enumerate(parsed.item_sources)
        if (row.start, row.end, row.text) == (source["start"], source["end"], source["text"])
    ]
    if len(rows) != 1:
        raise ValueError("original_row_mismatch")
    index = rows[0]
    original = parsed.reference_sources[index][ordinal - 1]
    if (original.start, original.end, original.text) != (
        reference.source_start,
        reference.source_end,
        reference.source_text,
    ):
        raise ValueError("original_occurrence_mismatch")
    # Wave7 diagnostics retain the source slice but omit original_identity.
    # Recover the pointer only from those validated bytes, never from a mapping.
    return parsed.items[index]["reference_links"][ordinal - 1]


def join_case_source(
    request: JoinRequest,
    packet: CaseReviewPacket,
    *,
    prepared: PreparedCatalog | None = None,
    reader: CatalogReader | None = None,
    synthetic_fixtures_only: bool = False,
) -> JoinResult:
    """No I/O except the explicitly injected reader; no default DB or uploads.

    row_sha256 is the existing case-source row text hash, not an invented hash
    of a source-book row. PreparedCatalog checksum covers every heading field.
    Closed results deliberately contain no citation, source text or partial join.
    """
    if synthetic_fixtures_only is not True:
        return _result("REJECTED", "synthetic_opt_in_required")
    try:
        _validate_request(request)
        matches = tuple(c for c in build_investigation().cases if c.case.key == request.case_key)
        if len(matches) != 1:
            return _result("NOT_CONNECTED", "case_not_connected")
        case = matches[0]
        if type(packet) is not CaseReviewPacket or packet.sha256 != request.packet_sha256:
            return _result("REJECTED", "packet_digest_mismatch")
        batch = None
        if type(case.case) is not WorkbenchCase:
            batch = next(
                b for b in build_prepared_workbench().batches if b.batch_id == case.batch_id
            )
        # FAST8 validates the complete packet against the code-selected case,
        # not against caller-rebuilt or mutually tampered case/packet objects.
        payload = _bind(case, packet, batch)
        if request.row_sha256 != payload["source"]["text_sha256"]:
            return _result("REJECTED", "row_digest_mismatch")
        if not case.references:
            return _result("NOT_CONNECTED", "no_reference_occurrences")
        if type(case.case) is not WorkbenchCase:
            return _result("NOT_CONNECTED", "prepared_case_original_occurrence_unsupported")
        if request.reference_ordinal > len(case.references):
            return _result("REJECTED", "reference_ordinal_mismatch")
        ref = case.references[request.reference_ordinal - 1]
        if (ref.status, ref.raw_status, ref.contract_status, ref.reasons) != (
            "verified",
            "verified",
            "VERIFIED",
            (),
        ):
            return _result("NOT_CONNECTED", "original_reference_unverified")
        original_identity = _original_occurrence(payload, ref, request.reference_ordinal)
        if request.occurrence_sha256 != ref.source_sha256:
            return _result("REJECTED", "occurrence_digest_mismatch")
        identity = validate_verified_identity(json.loads(ref.verified_identity))
        if any(
            getattr(request, field) != identity[field]
            for field in ("edition_id", "source_row_id", "source_id")
        ):
            return _result("REJECTED", "reference_identity_mismatch")
        if prepared is None:
            return _result("NOT_CONNECTED", "source_contract_not_supplied")
        trail = ReadingTrail(prepared, request.edition_id)
        if trail.prepared.checksum != request.catalog_checksum:
            return _result("REJECTED", "catalog_checksum_mismatch")
        records = tuple(
            r for r in trail.prepared.records if r.source_row_id == request.source_row_id
        )
        if len(records) != 1:
            return _result("NOT_CONNECTED", "source_row_not_connected")
        record = records[0]
        if record.source_id != identity["source_id"]:
            return _result("REJECTED", "source_id_mismatch")
        if reader is None:
            return _result("NOT_CONNECTED", "catalog_not_supplied")
        # A single physical snapshot binds topology, opaque IDs and every lookup.
        with reader.snapshot(request.edition_id) as snapshot:
            if type(snapshot) is not CatalogSnapshot:
                raise ValueError("invalid_snapshot")
            checked = CatalogSnapshot(
                snapshot.edition_id, snapshot.prepared, _StrictEvidence(snapshot.evidence)
            )
            result = CatalogNavigation(prepared, request.edition_id).from_reference(
                {"edition": str(request.edition_id), "source_row_id": str(request.source_row_id)},
                case,
                request.reference_ordinal,
                _SnapshotReader(checked),
            )
            if result.trail.status != "verified":
                status = (
                    "NOT_CONNECTED"
                    if result.trail.reason
                    in ("catalog_unavailable", "identity_not_found", "NOT_CONNECTED")
                    else "REJECTED"
                )
                outcome = _result(status, result.trail.reason)
            else:
                current = result.trail.current
                outcome = _result(
                    "VERIFIED_TECHNICAL",
                    "exact_case_source_join",
                    {
                        "case_identity": payload["identity"],
                        "batch_id": case.batch_id,
                        "reference_ordinal": request.reference_ordinal,
                        "original_identity": original_identity,
                        "verified_identity": identity,
                        "evidence": asdict(current.evidence),
                        "source_record": asdict(record),
                        "edition_title": result.edition_title,
                        "publisher": result.publisher,
                        "citation_html_text": current.citation,
                        "catalog_url": current.catalog_url,
                        "provenance": {
                            "packet_sha256": packet.sha256,
                            "row_sha256": request.row_sha256,
                            "input_sha256": payload["source"]["input_sha256"],
                            "row_start": payload["source"]["start"],
                            "row_end": payload["source"]["end"],
                            "occurrence_sha256": ref.source_sha256,
                            "occurrence_start": ref.source_start,
                            "occurrence_end": ref.source_end,
                            "offset_unit": payload["source"]["offset_unit"],
                            "catalog_checksum": trail.prepared.checksum,
                        },
                    },
                )
        # Returning only after __exit__ prevents failed transactions leaking success.
        return outcome
    except (CatalogReadError, AppRegistryNotReady, ImproperlyConfigured):
        return _result("NOT_CONNECTED", "catalog_unavailable")
    except (ValueError, TypeError, KeyError, AttributeError, IndexError, StopIteration):
        return _result("REJECTED", "contract_mismatch")
