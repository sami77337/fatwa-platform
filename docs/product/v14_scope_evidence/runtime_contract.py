"""Validate future bounded V14 receipts; this module credits no requirement itself.

Receipt excerpts must be obtained from actual log reads. Schema validation checks
attribution/consistency, not GitHub authenticity or independent reviewer quality.
"""

import hashlib
import json
import re

SHA = re.compile(r"[0-9a-f]{40}")
DIGEST = re.compile(r"[0-9a-f]{64}")
REPO = "https://github.com/sami77337/fatwa-platform"
BLOCKED_SEARCH = {"e5c504bb51157a67865ed2547d7fb67a38842117"}


def fingerprint(raw):
    return hashlib.sha256(raw).hexdigest()


def reference(value, *, head, read_pinned):
    assert SHA.fullmatch(head) and value["sha"] == head
    path = value["path"]
    assert not path.startswith("/") and ".." not in path.split("/")
    raw = read_pinned(head, path)
    assert DIGEST.fullmatch(value["file_sha256"])
    assert fingerprint(raw) == value["file_sha256"], "pinned file bytes differ"
    return raw


def test_observed(ref, lines):
    assert ref["path"].endswith(".py")
    symbol = ref["symbol"]
    assert re.fullmatch(r"[A-Za-z_][\w]*(?:\.[A-Za-z_][\w]*)+", symbol)
    module = ref["path"][:-3].replace("/", ".")
    method = symbol.rsplit(".", 1)[1]
    assert any(
        f"{method} ({module}.{symbol})" in line and line.rstrip().endswith(" ... ok")
        for line in lines
    ), "missing named executed test PASS"


def receipt(value, *, head, major, positive, negative, read_pinned):
    assert value["tested_sha"] == head and SHA.fullmatch(head)
    assert value["postgres_major"] == major and major in (17, 18)
    assert value["status"] == "completed" and value["conclusion"] == "success"
    assert type(value["run_id"]) is int and value["run_id"] > 0
    assert type(value["job_id"]) is int and value["job_id"] > 0
    assert value["url"] == f"{REPO}/actions/runs/{value['run_id']}/job/{value['job_id']}"
    assert value["attribution"] == "HOSTED_JOB_LOG_READ"
    lines = value["lines"]
    assert lines and all(isinstance(line, str) for line in lines)
    assert "TESTED_SHA=" + head in lines
    assert any(
        re.fullmatch(rf"SYNTHETIC_POSTGRES=postgres \(PostgreSQL\) {major}\.\d+", line)
        for line in lines
    ), "actual server version missing"
    assert positive and negative, "positive and negative checks required"
    for ref in [*positive, *negative]:
        reference(ref, head=head, read_pinned=read_pinned)
        test_observed(ref, lines)
    return lines


def browser(lines, *, head):
    matches = [
        line.removeprefix("V14_BROWSER_PROOF=")
        for line in lines
        if line.startswith("V14_BROWSER_PROOF=")
    ]
    assert len(matches) == 1, "one exact protected journey proof required"
    value = json.loads(matches[0])
    assert value["tested_sha"] == head and value["sandbox"] is True
    assert set(value["widths"]) == {320, 1280}
    assert value["external_requests"] == 0 and value["page_errors"] == 0
    assert value["browser"] and value["canonical"]["cases"] == 1
    # These are the V14 additions; an inherited V13 subset cannot stand in.
    for key, minimum in {
        "evaluation_revisions": 2,
        "evaluation_decisions": 1,
        "pdf_citations": 2,
        "pdf_confirmations": 2,
        "editorial_bindings": 1,
        "publications": 2,
        "publication_approvals": 2,
    }.items():
        assert value["canonical"][key] >= minimum, key
    recovery = value["recovery"]
    assert recovery["state"] == "READY" and recovery["target_http"] == "PASS"
    for key in (
        "encrypted_only",
        "separate_key",
        "independent_target_postgres_server",
        "source_unchanged",
        "source_left_frozen",
        "partial_delivery_preserved",
    ):
        assert recovery[key] is True, key
    assert recovery["wrong_key_and_hash_before_target"] == "DENIED"
    assert DIGEST.fullmatch(recovery["ciphertext_sha256"])
    assert recovery["pdf_plugin_selected_page"] == "NOT_VERIFIED"
    return value


def security(review, *, head, read_pinned):
    assert review["verdict"] == "PASS_BOUNDED"
    assert review["reviewed_sha"] == head, "review must match product head, not inherited CI"
    assert review["independent"] is True
    assert review["scope"] and review["remaining"]
    assert {row["postgres_major"] for row in review["executions"]} == {17, 18}
    assert len(review["executions"]) == 2
    report = review["report"]
    assert SHA.fullmatch(report["sha"])
    raw = reference(report, head=report["sha"], read_pinned=read_pinned)
    assert head.encode() in raw and b"SEC14-01B" in raw, (
        "report does not name reviewed head/blocker"
    )
    for execution in review["executions"]:
        assert execution["tested_sha"] == head and execution["result"] == "PASS"
        assert type(execution["passed"]) is int and execution["passed"] > 0
        assert execution["original_reproducers_unchanged"] is True
        assert execution["attribution"] in {"INDEPENDENT_REVIEWER_RECEIPT", "INDEPENDENT_LOG_READ"}
    assert "SEC14-01B" in review["closed_blockers"]
    assert "e5c504bb51157a67865ed2547d7fb67a38842117" in review["preserved_blocked_heads"]


def group(value, *, read_pinned):
    assert value["state"] == "VERIFIED_BOUNDED"
    head = value["product_sha"]
    assert SHA.fullmatch(head) and head not in BLOCKED_SEARCH
    assert value["bounded_claim"] and value["remaining"]
    assert value["status_upgrades"] == 0 and value["acceptance"] == "HOLD"
    assert value["new_percentage"] is None
    assert value["credited_owner_points"] and len(set(value["credited_owner_points"])) == len(
        value["credited_owner_points"]
    )
    assert all(type(point) is int and 1 <= point <= 556 for point in value["credited_owner_points"])
    assert value["code"]
    for ref in value["code"]:
        reference(ref, head=head, read_pinned=read_pinned)
    receipts = value["receipts"]
    assert len(receipts) == 2 and {item["postgres_major"] for item in receipts} == {17, 18}
    for item in receipts:
        lines = receipt(
            item,
            head=head,
            major=item["postgres_major"],
            positive=value["positive_tests"],
            negative=value["negative_tests"],
            read_pinned=read_pinned,
        )
        browser(lines, head=head)
    security(value["security_review"], head=head, read_pinned=read_pinned)
