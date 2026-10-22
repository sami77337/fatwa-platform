"""Deterministic, read-only diagnostics for the fixed synthetic Wave7 TOC.

Verification here means agreement with explicitly asserted fabricated evidence.
It does not attest an archive, a citation's scholarly relevance, or a ruling.
The existing pure reference planner owns all mapping and resolution decisions.
"""

import json
from dataclasses import asdict, dataclass
from hashlib import sha256

from apps.intake_workflow import contracts as c, fixtures
from apps.intake_workflow.references import (
    ItemReferenceVerification,
    plan_reference_verification,
)

from .bridge import BridgeConfig
from .resolution import KIND, Heading


def _heading_payload(heading: Heading) -> dict[str, object]:
    payload = asdict(heading)
    payload["path"] = list(heading.path)
    return payload


def _require_immutable_fields(rows: tuple[Heading, ...]) -> None:
    # Frozen dataclasses do not enforce annotations at runtime. Reject mutable
    # field values before retaining a snapshot; never repair or coerce them.
    for row in rows:
        if (
            any(type(getattr(row, name)) is not str for name in (
                "work_title", "heading_title", "source_namespace",
                "source_book_id", "source_input_sha256",
            ))
            or any(getattr(row, name) is not None and type(getattr(row, name)) is not str
                   for name in ("printed_part", "edition_key", "source_archive_sha256"))
            or (row.printed_page is not None and type(row.printed_page) is not int)
            or type(row.path) is not tuple
            or any(type(title) is not str for title in row.path)
        ):
            raise c.ContractError("reference: immutable_heading_fields_required")


@dataclass(frozen=True, slots=True)
class ReferenceDiagnosticReport:
    """Presentation of existing immutable contracts, without a second resolver.

    Item and reference order, byte slices, asserted catalog rows (including
    duplicates/conflicts), and fixed bridge bindings retain their exact values.
    No timestamp, source discovery, citation rendering or I/O is performed here.
    """

    payload_sha256: str
    trusted_binding: BridgeConfig
    catalog_rows: tuple[Heading, ...]
    items: tuple[ItemReferenceVerification, ...]

    def to_payload(self) -> dict[str, object]:
        """Return fresh JSON-safe containers; original numeric tokens stay text."""
        labels = {
            c.ReferenceStatus.VERIFIED: "verified",
            c.ReferenceStatus.UNVERIFIED: "unresolved",
            c.ReferenceStatus.MISMATCHED: "mismatched",
        }
        summary = dict.fromkeys(labels.values(), 0)
        items = []
        for item in self.items:
            references = []
            for reference in item.references:
                status = labels[reference.status]
                summary[status] += 1
                references.append({
                    "reference_ordinal": reference.reference_ordinal,
                    "status": status,
                    "contract_status": reference.status.value,
                    "reasons": list(reference.reasons),
                    "source": asdict(reference.source),
                    "source_sha256": sha256(reference.source.text.encode("utf-8")).hexdigest(),
                    "verified_identity": dict(reference.identity),
                    "evidence": _heading_payload(reference.evidence) if reference.evidence else None,
                })
            items.append({
                "row_ordinal": item.row_ordinal,
                "source": asdict(item.source),
                "references": references,
            })
        return {
            "schema": "fatwa.reference-diagnostics.v1",
            "kind": KIND,
            "source_config_id": c.SOURCE_CONFIG_ID,
            "input_sha256": self.payload_sha256,
            "synthetic_only": True,
            "archive_inspected": False,
            "scholarly_verified": False,
            "verification_scope": "asserted_fixed_synthetic_toc_snapshot_only",
            "trusted_binding": {
                "edition": asdict(self.trusted_binding.edition),
                "headings": [asdict(mapping) for mapping in self.trusted_binding.headings],
            },
            "asserted_catalog": [_heading_payload(row) for row in self.catalog_rows],
            "summary": summary,
            "items": items,
            "gates": {"B": "NOT_PASSED", "C": "HOLD", "D": "HOLD", "E": "HOLD"},
            "phase01": "BLOCKED",
            "scope_status": "SCOPE_DEVIATION_HOLD",
            "deployment_status": "NOT_DEPLOYED/GATES_HOLD",
        }

    def json_bytes(self) -> bytes:
        """Stable UTF-8 JSON with one final newline; writes no file or stream."""
        return (json.dumps(self.to_payload(), ensure_ascii=False, sort_keys=True,
                           separators=(",", ":"), allow_nan=False) + "\n").encode("utf-8")


def build_reference_diagnostics(
    raw: bytes, *, synthetic_fixtures_only: bool = False,
    catalog_rows: tuple[Heading, ...] = (),
) -> ReferenceDiagnosticReport:
    """Require explicit synthetic acknowledgement and a caller-asserted snapshot.

    Absent evidence remains unresolved; no adapter, lookup callback, source map,
    database or archive path is accepted. Decisions come unchanged from the
    existing fixed synthetic contract. Citation text is deliberately not exposed.
    Optional legacy evidence pins remain absent rather than being filled in.
    """
    items = plan_reference_verification(
        raw, synthetic_fixtures_only=synthetic_fixtures_only, catalog_rows=catalog_rows,
    )
    _require_immutable_fields(catalog_rows)
    return ReferenceDiagnosticReport(
        sha256(raw).hexdigest(), fixtures.trusted_bridge_config(), catalog_rows, items,
    )
