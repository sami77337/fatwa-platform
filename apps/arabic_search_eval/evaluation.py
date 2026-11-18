"""Reproducible synthetic comparison, not corpus acceptance or real rights proof."""

import hashlib
import json
from datetime import datetime
from pathlib import Path

from apps.reference.normalization import normalize_title

from .ranking import VERSION, Candidate, rank_titles

ROOT = Path(__file__).parent
BASE_SHA = "5ec6373f5eaf3cd5ea2b14d7b3e7119826ceb4c8"


def load_fixture(path=ROOT / "fixture.json"):
    raw = Path(path).read_bytes()
    fixture = json.loads(raw)
    if fixture["synthetic_only"] is not True:
        raise ValueError("synthetic_fixture_required")
    ids = [r["id"] for r in fixture["records"]]
    query_ids = [q["id"] for q in fixture["queries"]]
    if len(ids) != len(set(ids)) or len(query_ids) != len(set(query_ids)):
        raise ValueError("duplicate_fixture_id")
    for q in fixture["queries"]:
        if len(q["expected"]) != len(set(q["expected"])) or set(q["expected"]) - set(ids):
            raise ValueError("invalid_expected_ids")
        if set(q["expected"]) - {r["id"] for r in authorized(fixture, q)}:
            raise ValueError("expected_result_outside_scope")
    return fixture, hashlib.sha256(raw).hexdigest()


def authorized(fixture, query):
    """Synthetic evaluation oracle only; production authorization is elsewhere."""
    now = datetime.fromisoformat(fixture["clock"])
    return [
        r
        for r in fixture["records"]
        if r["scope"] == query["scope"]
        and r["edition"] == query["edition"]
        and r["read"] is True
        and datetime.fromisoformat(r["expires"]) > now
    ]


def baseline(query, records):
    """Existing citation search predicate + source order on the same small pool.

    Faithful title_normalized__contains for each normalize_title(query).split()
    token, capped at 20. This is a Python predicate replica, not a SQL timing test.
    """
    words = normalize_title(query).split()
    return [r["id"] for r in records if all(word in normalize_title(r["title"]) for word in words)][
        :20
    ]


def score(expected, returned, *, k=5):
    if len(returned) != len(set(returned)):
        raise ValueError("duplicate_result_id")
    top = returned[:k]
    relevant = set(expected)
    true_positive = len(relevant.intersection(top))
    return {
        "precision_at_5": true_positive / len(top) if top else 0.0,
        "recall_at_5": true_positive / len(relevant) if relevant else None,
        "reciprocal_rank": next((1 / i for i, r in enumerate(top, 1) if r in relevant), 0.0),
        "exact_order": returned == expected,
    }


def evaluate():
    fixture, digest = load_fixture()
    rows = []
    for q in fixture["queries"]:
        candidates = authorized(fixture, q)
        before = baseline(q["query"], candidates)
        error = None
        try:
            after = [
                h.identifier
                for h in rank_titles(
                    q["query"], [Candidate(r["id"], r["title"]) for r in candidates]
                )
            ]
        except ValueError as exc:
            after, error = [], str(exc)
        invalid = "expected_error" in q
        # Baseline service accepts blank/punctuation queries; oversized/control
        # inputs are rejected upstream. Do not credit the replica with that gap.
        baseline_error = None
        if len(q["query"]) > 80 or any(ord(c) < 32 for c in q["query"]):
            before, baseline_error = [], "invalid_search_query"
        rows.append(
            {
                "id": q["id"],
                "expected": q["expected"],
                "invalid_query": invalid,
                "baseline": before,
                "improved": after,
                "error": error,
                "baseline_error": baseline_error,
                "error_matches": error == q.get("expected_error"),
                "baseline_score": score(q["expected"], before),
                "improved_score": score(q["expected"], after),
                "forbidden_hits": len(set(after + before) - {r["id"] for r in candidates}),
            }
        )
    summary = {}
    positives = [r for r in rows if r["expected"]]
    negatives = [r for r in rows if not r["expected"] and not r["invalid_query"]]
    for system in ("baseline", "improved"):
        summary[system] = {
            name: sum(r[f"{system}_score"][name] for r in positives) / len(positives)
            for name in ("precision_at_5", "recall_at_5", "reciprocal_rank")
        }
        summary[system].update(
            exact_order_queries=sum(
                r[f"{system}_score"]["exact_order"] for r in rows if not r["invalid_query"]
            ),
            negative_false_positive_queries=sum(bool(r[system]) for r in negatives),
        )
    return {
        "schema_version": 1,
        "baseline_sha": BASE_SHA,
        "fixture_sha256": digest,
        "ranking_version": VERSION,
        "human_review": "PENDING",
        "code_sha256": {
            p.name: hashlib.sha256(p.read_bytes()).hexdigest()
            for p in [ROOT / "ranking.py", ROOT / "evaluation.py", ROOT / "services.py"]
        },
        "counts": {
            "records": len(fixture["records"]),
            "queries": len(rows),
            "positive": len(positives),
            "negative": len(negatives),
            "invalid": sum(r["invalid_query"] for r in rows),
        },
        "summary": summary,
        "queries": rows,
    }


def review_template():
    fixture, digest = load_fixture()
    return {
        "fixture_sha256": digest,
        "status": "PENDING",
        "reviewer": "",
        "evidence_reference": "",
        "queries": [
            {
                "id": q["id"],
                "query": q["query"],
                "expected": q["expected"],
                "rationale": q["rationale"],
                "verdict": "PENDING",
                "note": "",
            }
            for q in fixture["queries"]
        ],
    }


def validate_review(review):
    """Checks completeness/binding only. Cannot authenticate a human's identity."""
    fixture, digest = load_fixture()
    if (
        review.get("fixture_sha256") != digest
        or not review.get("reviewer", "").strip()
        or not review.get("evidence_reference", "").strip()
    ):
        raise ValueError("review_identity_evidence_or_fixture_missing")
    expected = {q["id"]: q["expected"] for q in fixture["queries"]}
    entries = review.get("queries", [])
    if len(entries) != len(expected) or {q["id"] for q in entries} != set(expected):
        raise ValueError("review_queries_incomplete")
    for q in entries:
        if (
            q.get("expected") != expected[q["id"]]
            or q.get("verdict") not in {"AGREE", "DISAGREE"}
            or not q.get("note", "").strip()
        ):
            raise ValueError("review_judgement_incomplete")
    return "RECORDED_REVIEW_REQUIRES_INDEPENDENT_IDENTITY_VERIFICATION"


def main():
    import argparse

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--review-template", action="store_true")
    parser.add_argument("--validate-review", type=Path)
    args = parser.parse_args()
    if args.validate_review:
        result = {"status": validate_review(json.loads(args.validate_review.read_text()))}
    else:
        result = review_template() if args.review_template else evaluate()
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
