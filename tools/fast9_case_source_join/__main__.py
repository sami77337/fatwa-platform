"""Deterministic fixed synthetic evidence only; no file, network or DB input."""

import argparse
import json
from contextlib import contextmanager

from apps.editorial_workbench.packets import CaseReviewPacket, build_packet
from apps.editorial_workbench.services import WorkbenchCase, build_prepared_workbench
from apps.fast8_fiqh_navigation.services import CatalogSnapshot
from apps.fast9_case_source_join.services import JoinRequest, join_case_source
from apps.reference_links.resolution import SnapshotCatalog
from apps.reference_triage.services import build_investigation

from .fixtures import EDITION_ID, FIXTURE_ID, fixture_sha256, synthetic_fixture


class SyntheticReader:
    @contextmanager
    def snapshot(self, edition_id):
        prepared, headings = synthetic_fixture()
        yield CatalogSnapshot(EDITION_ID, prepared, SnapshotCatalog(headings))


def fixture_request(case_key):
    """Build demo pins from the existing fixed case, never rewrite that case."""
    prepared, _ = synthetic_fixture()
    cases = tuple(c for c in build_investigation().cases if c.case.key == case_key)
    if len(cases) != 1:
        return JoinRequest(
            case_key,
            "0" * 64,
            "0" * 64,
            1,
            "0" * 64,
            prepared.checksum,
            EDITION_ID,
            1,
            "wave7-title-1",
        ), CaseReviewPacket(b"")
    case = cases[0]
    batch = None
    if type(case.case) is not WorkbenchCase:
        batch = next(b for b in build_prepared_workbench().batches if b.batch_id == case.batch_id)
    packet = build_packet(case.case, batch)
    reference = case.references[0] if case.references else None
    identity = json.loads(reference.verified_identity) if reference else {}
    return JoinRequest(
        case_key,
        packet.sha256,
        case.source_sha256,
        1,
        reference.source_sha256 if reference else "0" * 64,
        prepared.checksum,
        identity.get("edition_id", EDITION_ID),
        identity.get("source_row_id", 1),
        identity.get("source_id", "wave7-title-1"),
    ), packet


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, allow_abbrev=False)
    parser.add_argument("--synthetic-fixtures-only", action="store_true", required=True)
    parser.add_argument("--catalog", choices=("none", "synthetic"), default="none")
    parser.add_argument("--case-key", default="intake-1")
    args = parser.parse_args(argv)
    request, packet = fixture_request(args.case_key)
    result = join_case_source(
        request,
        packet,
        prepared=synthetic_fixture()[0],
        synthetic_fixtures_only=True,
        reader=SyntheticReader() if args.catalog == "synthetic" else None,
    ).payload()
    print(
        json.dumps(
            {
                "fixture_id": FIXTURE_ID,
                "fixture_sha256": fixture_sha256(),
                "database_catalog": "NOT_RUN",
                "result": result,
            },
            ensure_ascii=True,
            sort_keys=True,
            separators=(",", ":"),
        )
    )
    return 0 if result["status"] == "VERIFIED_TECHNICAL" else 2


if __name__ == "__main__":
    raise SystemExit(main())
