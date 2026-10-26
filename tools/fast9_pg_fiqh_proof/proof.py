"""Literal synthetic fixture pins and machine-readable evidence (no owner data)."""

import json
import subprocess

from tools.fiqh_reading_trail.fixtures import FIXTURE_ID, fixture_sha256, synthetic_fixture

CHECKSUM = "5349fd891831a0e2d0d831aede0a3353c5dff8bdf931c70e8645856f93c04c45"
FIXTURE_SHA256 = "b1abc9c56a6173f8c7c2f573af746aaee6140aaea58df26b6ffebd7803e12d98"


def checked_fixture():
    prepared, headings = synthetic_fixture()
    if fixture_sha256() != FIXTURE_SHA256 or prepared.checksum != CHECKSUM:
        raise RuntimeError("Pinned synthetic fixture changed; acceptance refused")
    return prepared, headings


def emit(event, **facts):
    print("FAST9_PROOF " + json.dumps({"event": event, **facts}, sort_keys=True))


def revision_evidence():
    sha = subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip()
    dirty = bool(subprocess.check_output(["git", "status", "--porcelain"], text=True))
    emit(
        "revision",
        sha=sha,
        dirty=dirty,
        fixture_id=FIXTURE_ID,
        fixture_sha256=FIXTURE_SHA256,
        catalog_checksum=CHECKSUM,
        source_owner_acceptance="NOT_CONNECTED",
        policy_acceptance="NOT_CONNECTED",
        production_acceptance="NOT_CONNECTED",
        gates="NOT_DEPLOYED / GATES_HOLD",
    )
