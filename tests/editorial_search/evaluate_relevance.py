"""Offline P245 measurements on fixed synthetic editorial questions and revisions."""

import json
from dataclasses import dataclass
from statistics import mean

from apps.editorial_queue.services import QueueCatalog, build_queue_catalog
from apps.editorial_search.services import PAGE_SIZE, search_catalog

type Identity = tuple[str, int | None]
K = 3


@dataclass(frozen=True)
class Judgment:
    id: str
    query: str
    source: str
    relevant: tuple[Identity, ...]


# Fixture identities are judged in advance, independently of the ranking code.
# Each question identity is a distinct source row, even for identical text.
CASES = (
    Judgment("exact-question", "سُؤَالٌ اصطناعي", "question", (("intake-3", None),)),
    Judgment(
        "marked-duplicates", "بعلاماته وسطره", "question", (("intake-1", None), ("intake-7", None))
    ),
    Judgment(
        "cross-batch-copies",
        "للتجربة",
        "question",
        (
            ("batch-synthetic-csv-3", None),
            ("batch-synthetic-csv-4", None),
            ("batch-synthetic-json-2", None),
            ("batch-synthetic-json-3", None),
            ("batch-synthetic-jsonl-3", None),
        ),
    ),
    Judgment("gapped-revisions", "منقح", "draft", tuple(("history", n) for n in (2, 4, 7, 9, 11))),
    # The source question uses "بلا مقطع"; this paraphrase measures a lexical limitation.
    Judgment("no-clip-paraphrase", "بدون مقطع", "question", (("intake-2", None),)),
    Judgment("no-match-control", "عبارة تجريبية غير مسجلة", "question", ()),
)


def score(ranked: tuple[Identity, ...], relevant: tuple[Identity, ...]) -> dict:
    top = ranked[:K]
    if len(set(top)) != len(top) or len(set(relevant)) != len(relevant):
        raise ValueError("duplicate result or judgment identity")
    positions = [rank for rank, identity in enumerate(top, 1) if identity in relevant]
    reciprocal_rank = 1 / positions[0] if positions else 0.0
    return {
        "returned_at_k": top,
        "relevant_ids": relevant,
        "true_positives": len(positions),
        "precision_at_k": len(positions) / K if relevant else None,
        "recall_at_k": len(positions) / len(relevant) if relevant else None,
        "reciprocal_rank_at_k": reciprocal_rank if relevant else None,
        "correct_empty": None if relevant else not top,
    }


def evaluate(catalog: QueueCatalog) -> dict:
    if not 1 <= K <= PAGE_SIZE:
        raise ValueError("cutoff must fit on the retrieved page")
    available = {
        ("question", (row.case.key, None)) for row in catalog.rows if row.case.question
    } | {
        ("draft", (row.case.key, entry.revision.number))
        for row in catalog.rows
        for entry in row.history
    }
    results = []
    for case in CASES:
        if any((case.source, identity) not in available for identity in case.relevant):
            raise ValueError(f"unknown judgment identity in {case.id}")
        page = search_catalog(catalog, q=case.query, source=case.source)
        row = score(tuple((hit.case_key, hit.revision) for hit in page.hits), case.relevant)
        results.append({"id": case.id, "query": case.query, "source": case.source, **row})
    positives = [r for r in results if r["relevant_ids"]]
    controls = [r for r in results if not r["relevant_ids"]]
    return {
        "scope": "synthetic_editorial_search_only",
        "cutoff": K,
        "queries": results,
        "macro": {
            field: mean(r[field] for r in positives)
            for field in ("precision_at_k", "recall_at_k", "reciprocal_rank_at_k")
        },
        "query_coverage_at_k": sum(r["true_positives"] > 0 for r in positives) / len(positives),
        "empty_controls": {
            "correct": sum(r["correct_empty"] for r in controls),
            "total": len(controls),
        },
    }


if __name__ == "__main__":
    print(json.dumps(evaluate(build_queue_catalog()), ensure_ascii=False, indent=2))
