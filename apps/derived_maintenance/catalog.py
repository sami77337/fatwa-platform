"""Closed payload owners, immutable headers and metadata-only deletion records."""

from dataclasses import dataclass

from apps.data_privacy.services import PrivacyDenied
from apps.record_suppression.catalog import (
    ZERO,
    canonical,
    digest,
    parse_stamp,
    sha,
    stamp,
    text_hash,
    uuid_text,
)

__all__ = ("ZERO", "canonical", "digest", "parse_stamp", "sha", "stamp", "text_hash", "uuid_text")
KINDS = {"SEARCH_INDEX", "AI_CANDIDATES"}
ROLES = {"MUFTI", "ORGANIZER_ADMIN"}
LIMIT = 4096
FIELDS = {
    "id",
    "ledger_id",
    "sequence",
    "previous_digest",
    "kind",
    "target_id",
    "header_digest",
    "case_id",
    "payload",
    "provider_id",
    "subject_id",
    "role",
    "auth_epoch",
    "reason_sha256",
    "occurred_at",
}


class DerivedDenied(PrivacyDenied):
    pass


def body(value):
    if type(value) is not dict or set(value) != FIELDS:
        raise DerivedDenied("derived_clearance_shape_invalid")
    for name in ("id", "ledger_id", "target_id", "case_id"):
        uuid_text(value[name])
    for name in ("previous_digest", "header_digest", "reason_sha256"):
        sha(value[name])
    if type(value["sequence"]) is not int or not 1 <= value["sequence"] <= LIMIT:
        raise DerivedDenied("derived_clearance_sequence_invalid")
    if type(value["kind"]) is not str or value["kind"] not in KINDS:
        raise DerivedDenied("derived_payload_owner_invalid")
    if type(value["role"]) is not str or value["role"] not in ROLES:
        raise DerivedDenied("derived_administrative_role_required")
    for name in ("provider_id", "subject_id", "auth_epoch"):
        if (
            type(value[name]) is not str
            or not 1 <= len(value[name]) <= 128
            or not value[name].strip()
            or "\x00" in value[name]
            or any(0xD800 <= ord(char) <= 0xDFFF for char in value[name])
        ):
            raise DerivedDenied("derived_identity_invalid")
    payload = value["payload"]
    if type(payload) is not list or not 1 <= len(payload) <= 512:
        raise DerivedDenied("derived_payload_manifest_invalid")
    identifiers = set()
    for item in payload:
        if type(item) is not dict or set(item) != {"id", "digest"}:
            raise DerivedDenied("derived_payload_manifest_invalid")
        uuid_text(item["id"])
        sha(item["digest"])
        if item["id"] in identifiers:
            raise DerivedDenied("derived_payload_manifest_invalid")
        identifiers.add(item["id"])
    if payload != sorted(payload, key=lambda row: row["id"]):
        raise DerivedDenied("derived_payload_manifest_invalid")
    if value["kind"] == "AI_CANDIDATES" and len(payload) != 1:
        raise DerivedDenied("derived_payload_manifest_invalid")
    parse_stamp(value["occurred_at"])
    return value


def events(values, ledger_id):
    if type(values) is not list or len(values) > LIMIT:
        raise DerivedDenied("derived_journal_bound")
    previous, targets, identifiers = ZERO, set(), set()
    for number, value in enumerate(values, 1):
        body(value)
        target = value["kind"], value["target_id"]
        if (
            value["ledger_id"] != ledger_id
            or value["sequence"] != number
            or value["previous_digest"] != previous
            or target in targets
            or value["id"] in identifiers
        ):
            raise DerivedDenied("derived_journal_chain_invalid")
        previous = digest(value)
        targets.add(target)
        identifiers.add(value["id"])


@dataclass(frozen=True)
class Target:
    kind: str
    identifier: str
    header_digest: str
    case_id: str
    case_ref: str
    payload: tuple

    def manifest(self):
        return [dict(id=identifier, digest=seal) for identifier, seal in self.payload]


def target(kind, identifier):
    uuid_text(identifier)
    if kind == "SEARCH_INDEX":
        from apps.canonical_search.models import SearchDocument, SearchGeneration
        from apps.canonical_search.services import _verify

        header = SearchGeneration.objects.filter(pk=identifier).select_related("case").first()
        if header is None:
            raise DerivedDenied("derived_header_unavailable")
        _verify(header)
        payload = list(SearchDocument.objects.filter(generation=header).order_by("pk"))
        for row in payload:
            _verify(row)
        case, seal = header.case, header.digest
    elif kind == "AI_CANDIDATES":
        from apps.ai_gateway.models import CandidateBatch, GatewayOutcome, GatewayRun
        from apps.precise_citations.boundary import verify

        header = GatewayRun.objects.filter(pk=identifier).select_related("case").first()
        outcome = GatewayOutcome.objects.filter(run=header).first() if header else None
        if header is None or outcome is None or outcome.status != "SUCCEEDED":
            raise DerivedDenied("derived_header_unavailable")
        verify(header)
        verify(outcome)
        payload = list(CandidateBatch.objects.filter(run=header))
        for row in payload:
            verify(row)
            if digest(row.entries) != outcome.output_digest:
                raise DerivedDenied("derived_payload_changed")
        case, seal = header.case, header.digest
    else:
        raise DerivedDenied("derived_payload_owner_invalid")
    return Target(
        kind,
        identifier,
        seal,
        str(case.pk),
        case.public_ref,
        tuple(sorted((str(row.pk), row.digest) for row in payload)),
    )
