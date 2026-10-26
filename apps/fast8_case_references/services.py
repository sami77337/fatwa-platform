"""Compose existing contracts without source discovery, I/O or scholarly decisions."""

import json
from dataclasses import asdict, dataclass
from hashlib import sha256

from apps.editorial_workbench.batches import BatchOverview, PreparedCase
from apps.editorial_workbench.packets import CaseReviewPacket, build_packet, serialize_packet
from apps.editorial_workbench.services import WorkbenchCase, build_prepared_workbench
from apps.fiqh_reading_trail.services import ReadingTrail
from apps.reference_links.resolution import (
    KIND,
    CatalogReadError,
    Heading,
    ReadOnlyCatalog,
)
from apps.reference_triage.services import CaseTriage, ReferenceTriage, build_investigation
from apps.research_bridge.services import bridge_reference


class DossierError(ValueError):
    """An exact synthetic occurrence cannot be established."""


@dataclass(frozen=True, slots=True)
class CaseReferenceDossier:
    json_bytes: bytes

    @property
    def sha256(self) -> str:
        return sha256(self.json_bytes).hexdigest()

    def payload(self) -> dict:
        return json.loads(self.json_bytes)


class _ExactCatalog:
    """Close legacy resolver numeric equality gaps at this adapter boundary."""

    def __init__(self, catalog: ReadOnlyCatalog):
        self.catalog = catalog

    def lookup(self, edition_id: int, source_row_id: int):
        rows = self.catalog.lookup(edition_id, source_row_id)
        for row in rows:
            if type(row) is not Heading or any(
                type(getattr(row, field)) is not int
                for field in ("edition_id", "source_row_id", "printed_page")
            ):
                raise CatalogReadError("invalid_numeric_evidence")
        return rows


def _same(left: object, right: object) -> bool:
    # Canonical encoding also distinguishes bool/float from integer identities.
    return serialize_packet({"value": left}) == serialize_packet({"value": right})


def _bind(case: CaseTriage, packet: CaseReviewPacket, batch: BatchOverview | None) -> dict:
    if type(case) is not CaseTriage or type(packet) is not CaseReviewPacket:
        raise DossierError("invalid_case_contract")
    if type(case.references) is not tuple or len(case.references) > 100:
        raise DossierError("invalid_reference_occurrences")
    # Reuse packet authority for source bytes, hashes, selection and provenance.
    expected = build_packet(case.case, batch)
    if packet.json_bytes != expected.json_bytes:
        raise DossierError("packet_case_mismatch")
    payload = packet.payload()
    if case.source_sha256 != payload["source"]["text_sha256"]:
        raise DossierError("case_source_mismatch")
    expected_batch = getattr(
        case.case, "batch_id", "revision-history" if case.case.key == "history" else "wave7"
    )
    if case.batch_id != expected_batch:
        raise DossierError("case_batch_mismatch")
    raw_refs = payload["reference_verification"]["results"]
    if len(case.references) != len(raw_refs):
        raise DossierError("reference_count_mismatch")
    for ordinal, (ref, raw) in enumerate(zip(case.references, raw_refs, strict=True), 1):
        if (
            type(ref) is not ReferenceTriage
            or type(ref.ordinal) is not int
            or type(raw["reference_ordinal"]) is not int
            or ref.ordinal != ordinal
            or raw["reference_ordinal"] != ordinal
        ):
            raise DossierError("reference_order_mismatch")
        source = raw["source"]
        pairs = (
            (ref.raw_status, raw["status"]),
            (ref.contract_status, raw["contract_status"]),
            (ref.reasons, raw["reasons"]),
            (ref.explanation, raw["explanation_ar"]),
            (ref.reason_explanations, raw["reason_explanations_ar"]),
            (json.loads(ref.original_identity), raw.get("original_identity", {})),
            (json.loads(ref.verified_identity), raw["verified_identity"]),
            (json.loads(ref.evidence), raw["evidence"]),
            (ref.source_text, source["text"]),
            (ref.source_start, source["start"]),
            (ref.source_end, source["end"]),
            (ref.source_sha256, sha256(source["text"].encode("utf-8")).hexdigest()),
        )
        if not all(_same(left, right) for left, right in pairs):
            raise DossierError("reference_packet_mismatch")
        if (ref.status == "verified") != (ref.raw_status == "verified"):
            raise DossierError("reference_status_mismatch")
    return payload


def _compose(
    case: CaseTriage,
    packet: CaseReviewPacket,
    *,
    batch: BatchOverview | None = None,
    trail: ReadingTrail | None = None,
    catalog: ReadOnlyCatalog | None = None,
) -> CaseReferenceDossier:
    """Internal composition of code-selected fixtures; never an upload interface."""
    payload = _bind(case, packet, batch)
    checked_catalog = _ExactCatalog(catalog) if catalog is not None else None
    entries = []
    for ref, raw in zip(case.references, payload["reference_verification"]["results"], strict=True):
        entry = {
            "reference_ordinal": ref.ordinal,
            "upstream_status": ref.raw_status,
            "contract_status": ref.contract_status,
            "unresolved_reasons": ref.reasons,
            "explanation_ar": ref.explanation,
            "reason_explanations_ar": ref.reason_explanations,
            "provenance": {
                "source_sha256": ref.source_sha256,
                "source_start": ref.source_start,
                "source_end": ref.source_end,
                "source_kind": raw.get(
                    "source_kind",
                    "original_utf8_slice"
                    if ref.source_start is not None
                    else "serialized_reference",
                ),
                "offset_unit": "utf8_bytes_end_exclusive" if ref.source_start is not None else None,
            },
            "status": "UNRESOLVED",
            "reason": "upstream_unverified",
            "bridge_status": "NOT_RUN",
            "trail_status": "NOT_RUN",
            "evidence": None,
            "verified_identity": None,
            "citation_html_text": None,
            "catalog_url": None,
            "reading_trail": None,
        }
        if ref.status == "verified":
            if checked_catalog is None:
                entry.update(status="NOT_CONNECTED", reason="catalog_not_supplied")
            else:
                bridge = bridge_reference(ref, checked_catalog)
                entry.update(bridge_status=bridge.status, reason=bridge.reason)
                if bridge.status == "verified":
                    if trail is None:
                        entry.update(status="NOT_CONNECTED", reason="reading_trail_not_supplied")
                    elif type(case.case) is not WorkbenchCase:
                        entry.update(
                            status="NOT_CONNECTED", reason="prepared_case_trail_unsupported"
                        )
                    else:
                        navigation = trail.from_reference(case, ref.ordinal, checked_catalog)
                        entry.update(trail_status=navigation.status, reason=navigation.reason)
                        if navigation.status == "verified" and navigation.current is not None:
                            # Repeated reads must agree; do not join evidence from two snapshots.
                            if not _same(
                                asdict(bridge.evidence), asdict(navigation.current.evidence)
                            ):
                                entry.update(reason="catalog_changed_during_read")
                            else:
                                entry.update(
                                    status="VERIFIED",
                                    evidence=asdict(navigation.current.evidence),
                                    verified_identity=json.loads(ref.verified_identity),
                                    citation_html_text=navigation.current.citation,
                                    catalog_url=navigation.current.catalog_url,
                                    reading_trail=asdict(navigation),
                                )
        entries.append(entry)
    verified = sum(entry["status"] == "VERIFIED" for entry in entries)
    status = "MISSING" if not entries else "VERIFIED" if verified == len(entries) else "INCOMPLETE"
    result = {
        "schema": "fatwa.synthetic-case-reference-dossier.v1",
        "synthetic_only": True,
        "kind": KIND,
        "status": status,
        "identity": payload["identity"],
        "batch_id": case.batch_id,
        "provenance": {
            "packet_sha256": packet.sha256,
            "input_sha256": payload["source"]["input_sha256"],
            "case_source_sha256": case.source_sha256,
            "source_kind": payload["source"]["kind"],
            "offset_unit": payload["source"]["offset_unit"],
            "verification_scope": payload["reference_verification"]["scope"],
            "verification_revision": payload["reference_verification"]["revision"],
            "catalog_checksum": trail.prepared.checksum if trail is not None else None,
        },
        "references": entries,
        "reference_count": len(entries),
        "verified_count": verified,
        "missing_reason": "no_reference_occurrences" if not entries else None,
        "preparation_errors": payload["preparation_errors"],
        "limit_ar": payload["reference_verification"]["limit_ar"],
        "holds": [*payload["holds"], "U03/U10 OWNER_APPROVAL_PENDING"],
    }
    return CaseReferenceDossier(serialize_packet(result))


def build_dossier(
    case_key: str,
    *,
    synthetic_fixtures_only: bool = False,
    trail: ReadingTrail | None = None,
    catalog: ReadOnlyCatalog | None = None,
) -> CaseReferenceDossier:
    """Select one existing fixed synthetic case, never by external ID or text.

    Missing contracts stay disconnected. Supplying a catalog never selects a
    default Django adapter or discovers an edition. No source text is exported.
    """
    if synthetic_fixtures_only is not True:
        raise DossierError("synthetic_opt_in_required")
    if type(case_key) is not str or not 1 <= len(case_key) <= 100:
        raise DossierError("invalid_case_key")
    if trail is not None and type(trail) is not ReadingTrail:
        raise DossierError("invalid_trail_contract")
    if catalog is not None and not callable(getattr(catalog, "lookup", None)):
        raise DossierError("invalid_catalog_contract")
    matches = tuple(row for row in build_investigation().cases if row.case.key == case_key)
    if len(matches) != 1:
        raise DossierError("case_not_found_or_ambiguous")
    case = matches[0]
    batch = None
    if isinstance(case.case, PreparedCase):
        batches = tuple(
            item for item in build_prepared_workbench().batches if item.batch_id == case.batch_id
        )
        if len(batches) != 1:
            raise DossierError("original_batch_not_supplied")
        batch = batches[0]
    return _compose(case, build_packet(case.case, batch), batch=batch, trail=trail, catalog=catalog)
