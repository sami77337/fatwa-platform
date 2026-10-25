"""Compose FAST3 read services without creating records or deciding workflow state."""

from collections import Counter
from dataclasses import dataclass
from urllib.parse import urlencode

from django.urls import reverse
from django.utils.html import escape
from django.utils.safestring import mark_safe

from apps.editorial_queue.services import ORIGINAL_BATCH, STATUSES, build_queue_catalog
from apps.editorial_workbench.batch_fixtures import synthetic_inputs
from apps.editorial_workbench.batches import PreparedCase
from apps.editorial_workbench.services import WorkbenchDataError
from apps.intake_workflow.fixtures import trusted_reference_map
from apps.prepared_pipeline.diagnostics import diagnose_batches
from apps.reference_triage.services import STATUSES as REFERENCE_STATUSES
from apps.reference_triage.services import build_investigation, summarize


class UnknownBatch(ValueError):
    """The requested batch is not in the fixed synthetic catalog."""


@dataclass(frozen=True, slots=True)
class Dashboard:
    total_rows: int
    questions: int
    prepared_records: int
    attention_count: int
    reference_total: int
    statuses: tuple[dict, ...]
    references: tuple[dict, ...]
    source_diagnostics: tuple[dict, ...]
    batches: tuple[dict, ...]
    rows: tuple[dict, ...]


def _url(name: str, key: str | None = None, **params: str) -> str:
    path = reverse(name, args=[key] if key is not None else None)
    query = urlencode({name: value for name, value in params.items() if value})
    return path + ("?" + query if query else "")


def _require(condition: bool) -> None:
    if not condition:
        raise WorkbenchDataError("dashboard: inconsistent_service_identity")


def build_dashboard(batch_id: str = "") -> Dashboard:
    catalog = build_queue_catalog()
    if batch_id and batch_id not in {batch.batch_id for batch in catalog.batches}:
        raise UnknownBatch
    investigation = build_investigation()
    triage = {row.case.key: row for row in investigation.cases}
    _require(len(triage) == len(investigation.cases) == len(catalog.rows))
    for row in catalog.rows:
        _require(row.case.key in triage and triage[row.case.key].case == row.case)

    # Inventory comes from the fixed trusted fixture map, never incoming pointers.
    # This only declares synthetic source availability; it grants no reference trust.
    inventory = sorted({pointer.source_id for pointer in trusted_reference_map()})
    diagnostics = diagnose_batches(
        synthetic_inputs(), synthetic_fixtures_only=True, available_source_ids=inventory
    ).report
    sources = {item["batch_id"]: item for item in diagnostics["inputs"]}
    prepared_batches = [batch for batch in catalog.batches if batch.source is not None]
    _require(len(sources) == len(diagnostics["inputs"]) == len(prepared_batches))
    for batch in prepared_batches:
        _require(
            batch.batch_id in sources
            and sources[batch.batch_id]["input_sha256"] == batch.source.input_sha256
            and sources[batch.batch_id]["error_code"] == batch.source.error_code
        )
    diagnostic_rows = {(item["batch_id"], item["row"]): item for item in diagnostics["rows"]}
    prepared = [row for row in catalog.rows if isinstance(row.case, PreparedCase)]
    _require(len(diagnostic_rows) == len(diagnostics["rows"]) == len(prepared))
    for row in prepared:
        item = diagnostic_rows.get((row.batch_id, row.case.row_ordinal))
        _require(
            item is not None
            and item["provenance"]["input_sha256"] == row.case.payload_sha256
            and item["preparation"]["original"] == row.case.original
        )

    selected = tuple(row for row in catalog.rows if not batch_id or row.batch_id == batch_id)
    refs = summarize(tuple(triage[row.case.key] for row in selected))
    rows = []
    for row in selected:
        case = row.case
        findings = (
            tuple(diagnostic_rows[(row.batch_id, case.row_ordinal)]["diagnostics"])
            if isinstance(case, PreparedCase)
            else ()
        )
        # Escaping precedes CR preservation; code child prevents initial LF loss in pre.
        question = "لم يرد نص سؤال" if case.question is None else case.question
        exact = mark_safe(str(escape(question)).replace("\r", "&#13;"))
        rows.append(
            dict(
                row=row,
                question_html=exact,
                needs_attention=case.status != "ready" or row.reference_status != "verified",
                queue_url=_url("editorial_queue:detail", case.key, batch=row.batch_id),
                workbench_url=_url("editorial_workbench:detail", case.key),
                investigation_url=_url("reference_triage:detail", case.key),
                packet_url=_url("editorial_workbench:detail", case.key, packet="html"),
                diagnostics=findings,
            )
        )
    counts = Counter(issue["code"] for row in rows for issue in row["diagnostics"])
    return Dashboard(
        total_rows=len(selected),
        questions=sum(bool(row.case.question and row.case.question.strip()) for row in selected),
        prepared_records=sum(row.case.record is not None for row in selected),
        attention_count=sum(row["needs_attention"] for row in rows),
        reference_total=refs.references,
        statuses=tuple(
            dict(
                code=code,
                label=label,
                count=sum(row.case.status == code for row in selected),
                url=_url("editorial_queue:index", batch=batch_id, status=code),
            )
            for code, label in STATUSES
        ),
        references=tuple(
            dict(
                code=code,
                label=label,
                count=getattr(refs, code),
                # Original is a queue union, not a triage filter. Exact case links below
                # retain access without presenting a broader result as a matching total.
                url=None
                if batch_id == ORIGINAL_BATCH
                else _url("reference_triage:index", batch=batch_id, status=code),
            )
            for code, label in REFERENCE_STATUSES
        ),
        source_diagnostics=tuple(
            dict(code=code, label=label, count=counts[code])
            for code, label in (
                ("missing_source", "إحالات إلى مصدر غير موجود في الجرد الاصطناعي"),
                ("source_pointer_missing", "صفوف دون مؤشر مصدر صالح"),
                ("source_inventory_not_supplied", "إحالات دون جرد مصادر مقدم"),
            )
        ),
        batches=tuple(
            dict(
                batch=batch,
                prepared_records=sum(
                    row.case.record is not None
                    for row in catalog.rows
                    if row.batch_id == batch.batch_id
                ),
                queue_url=_url("editorial_queue:index", batch=batch.batch_id),
                workbench_url=_url("editorial_workbench:index", batch=batch.batch_id)
                if batch.source is not None
                else None,
            )
            for batch in catalog.batches
        ),
        rows=tuple(rows),
    )
