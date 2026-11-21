"""Native, browser-bound authored judgments, actual runs and independent decisions."""

import re
import uuid

from django.shortcuts import render

from apps.canonical_search import governance
from apps.casework import services as cases
from apps.casework_web.guard import private
from apps.casework_web.views import InvalidForm
from apps.delivery_queue.services import synthetic_queue_atomic

from . import benchmark
from . import benchmark_policy as policy

QUERY_FIELDS = {f"q_{i}_{field}" for i in range(8) for field in ("query", "expected", "rationale")}
REVIEW_FIELDS = {f"r_{i}_{field}" for i in range(8) for field in ("verdict", "note")}
FIELDS = {
    "cs_benchmark_open": set(),
    "cs_benchmark_propose": {"state", "note"} | QUERY_FIELDS,
    "cs_benchmark_judge": {"state", "decision", "note", "confirm"} | REVIEW_FIELDS,
    "cs_benchmark_run": {"state", "note"},
    "cs_benchmark_read": {"state"},
    "cs_benchmark_review": {"state", "decision", "note", "confirm"},
}
STATE_KEYS = {"binding", "case_ref", "purpose", "request_key"}


def _state(request, base, desk, purpose, **values):
    from apps.canonical_search import views

    return views._state(
        request,
        base,
        {
            "case_ref": desk["case_ref"],
            "purpose": purpose,
            "request_key": str(uuid.uuid4()),
            **values,
        },
    )


def _read(request, base, fields, purpose, extra):
    from apps.canonical_search import views

    state = views._read_state(request, base, fields)
    if set(state) != STATE_KEYS | set(extra) or state["purpose"] != purpose:
        raise InvalidForm("benchmark_state_invalid")
    return state


def _allowed(context, action):
    try:
        context.permit(action)
    except cases.CaseConflict as exc:
        if str(exc) == "canonical_benchmark_action_denied":
            return False
        raise
    return True


def page(request, base, *, run_id=None, message=""):
    from apps.canonical_search import views

    with policy.boundary(**base, action="READ") as context:
        desk = benchmark.desk_in_context(context)
        capabilities = {
            action: _allowed(context, action) for action in ("PROPOSE", "JUDGE", "RUN", "REVIEW")
        }
        current = desk["current"]
        records = desk["corpus"]["records"]
        positions = {row["id"]: index + 1 for index, row in enumerate(records)}
        for index, row in enumerate(records, 1):
            row["position"] = index
            row["state"] = views._state(
                request,
                base,
                {
                    "case_ref": desk["case_ref"],
                    "generation_id": desk["corpus"]["source_pin"]["generation_id"],
                    "document_id": row["id"],
                },
            )
        old_queries = current["judgements"] if current and current["current"] else []
        editing = []
        for index in range(8):
            item = (
                old_queries[index]
                if index < len(old_queries)
                else {"query": "", "expected": [], "rationale": ""}
            )
            editing.append(
                {
                    "number": index,
                    **item,
                    "expected_positions": ", ".join(
                        str(positions[value]) for value in item["expected"]
                    ),
                }
            )
        proposal = _state(
            request,
            base,
            desk,
            "PROPOSE",
            number=desk["current_number"],
            corpus_sha256=desk["corpus_sha256"],
        )
        judgement_state = None
        review_rows = []
        if current and current["current"]:
            judgement_state = _state(
                request,
                base,
                desk,
                "JUDGE",
                revision_id=current["id"],
                corpus_sha256=current["corpus_sha256"],
                judgements_sha256=current["judgements_sha256"],
                query_ids=[item["id"] for item in current["judgements"]],
            )
            for index in range(8):
                if index < len(current["judgements"]):
                    item = current["judgements"][index]
                    review_rows.append(
                        {
                            "number": index,
                            **item,
                            "expected_positions": ", ".join(
                                str(positions[value]) for value in item["expected"]
                            ),
                        }
                    )
                else:
                    review_rows.append({"number": index, "unused": True})
        dictionaries = []
        if capabilities["RUN"] and current and current["current"] and current["state"] == "APPROVE":
            for dictionary in governance.desk_in_context(context.search, case_id=context.case.pk)[
                "dictionaries"
            ]:
                if dictionary["state"] == "APPROVE":
                    dictionary["state_token"] = _state(
                        request,
                        base,
                        desk,
                        "RUN",
                        revision_id=current["id"],
                        corpus_sha256=current["corpus_sha256"],
                        judgements_sha256=current["judgements_sha256"],
                        dictionary_id=dictionary["id"],
                        dictionary_digest=dictionary["digest"],
                    )
                    dictionaries.append(dictionary)
        for row in desk["runs"]:
            row["state"] = _state(request, base, desk, "READ", run_id=row["id"])
        result = benchmark.read_in_context(context, run_id=run_id) if run_id else None
        if result:
            result["state"] = _state(
                request, base, desk, "REVIEW", run_id=result["id"], digest=result["digest"]
            )
            for row in result["metrics"]["queries"]:
                for key in ("expected", "baseline", "candidate"):
                    row[f"{key}_positions"] = ", ".join(str(positions[value]) for value in row[key])
        return private(
            render(
                request,
                "arabic_search_eval/benchmark.html",
                {
                    "desk": desk,
                    "current": current,
                    "editing": editing,
                    "review_rows": review_rows,
                    "proposal_state": proposal,
                    "judgement_state": judgement_state,
                    "dictionaries": dictionaries,
                    "capabilities": capabilities,
                    "result": result,
                    "message": message,
                },
            )
        )


def _queries(fields, records):
    result = []
    for index in range(8):
        value, expected, rationale = [
            fields[f"q_{index}_{field}"] for field in ("query", "expected", "rationale")
        ]
        if not any((value, expected, rationale)):
            continue
        positions = [piece.strip() for piece in re.split(r"[,،]", expected) if piece.strip()]
        if expected.strip() and not positions:
            raise InvalidForm("benchmark_positions_invalid")
        if any(
            not p.isascii() or not p.isdigit() or not 1 <= int(p) <= len(records) for p in positions
        ):
            raise InvalidForm("benchmark_positions_invalid")
        result.append(
            {
                "id": f"q-{index + 1}",
                "query": value,
                "expected": [records[int(p) - 1]["id"] for p in positions],
                "rationale": rationale,
            }
        )
    return result


def handle(request, base, action, fields):
    if action == "cs_benchmark_open":
        return page(request, base)
    if action == "cs_benchmark_read":
        state = _read(request, base, fields, "READ", {"run_id"})
        return page(request, base, run_id=state["run_id"])
    # Mutation and final current-trust rendering are one atomic operation.
    with synthetic_queue_atomic():
        if action == "cs_benchmark_propose":
            state = _read(request, base, fields, "PROPOSE", {"number", "corpus_sha256"})
            desk = benchmark.desk(**base)
            if state["corpus_sha256"] != desk["corpus_sha256"]:
                raise cases.CaseConflict("canonical_benchmark_corpus_stale")
            benchmark.propose(
                **base,
                expected_number=state["number"],
                expected_corpus_sha256=state["corpus_sha256"],
                judgements=_queries(fields, desk["corpus"]["records"]),
                note=fields["note"],
            )
            return page(request, base, message="حُفظ إصدار أحكام جديد ينتظر مراجعة مستقلة.")
        if action == "cs_benchmark_judge":
            state = _read(
                request,
                base,
                fields,
                "JUDGE",
                {"revision_id", "corpus_sha256", "judgements_sha256", "query_ids"},
            )
            reviews = []
            for index in range(8):
                verdict, note = fields[f"r_{index}_verdict"], fields[f"r_{index}_note"]
                if index < len(state["query_ids"]):
                    reviews.append(
                        {"id": state["query_ids"][index], "verdict": verdict, "note": note}
                    )
                elif verdict or note:
                    raise InvalidForm("benchmark_unused_review_invalid")
            benchmark.judge(
                **base,
                revision_id=state["revision_id"],
                corpus_sha256=state["corpus_sha256"],
                judgements_sha256=state["judgements_sha256"],
                action=fields["decision"],
                confirmed=fields["confirm"] == "yes",
                reviews=reviews,
                note=fields["note"],
            )
            return page(request, base, message="سُجل قرار مراجعة الأحكام للإصدار المحدد.")
        if action == "cs_benchmark_run":
            state = _read(
                request,
                base,
                fields,
                "RUN",
                {
                    "revision_id",
                    "corpus_sha256",
                    "judgements_sha256",
                    "dictionary_id",
                    "dictionary_digest",
                },
            )
            result = benchmark.run(
                **base,
                revision_id=state["revision_id"],
                dictionary_id=state["dictionary_id"],
                expected_corpus_sha256=state["corpus_sha256"],
                expected_judgements_sha256=state["judgements_sha256"],
                expected_dictionary_digest=state["dictionary_digest"],
                request_key=state["request_key"],
                note=fields["note"],
            )
            return page(
                request,
                base,
                run_id=result["id"],
                message="نُفذت المقارنة الفعلية وسُجلت نتائجها؛ إعداد البحث العام باقٍ كما هو.",
            )
        if action == "cs_benchmark_review":
            state = _read(request, base, fields, "REVIEW", {"run_id", "digest"})
            result = benchmark.decide(
                **base,
                run_id=state["run_id"],
                expected_digest=state["digest"],
                action=fields["decision"],
                confirmed=fields["confirm"] == "yes",
                note=fields["note"],
                request_key=state["request_key"],
            )
            return page(
                request,
                base,
                run_id=result["id"],
                message="سُجل قرار المراجعة المستقلة لهذه التجربة فقط.",
            )
    raise InvalidForm("benchmark_action_invalid")
