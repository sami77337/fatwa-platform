"""Deterministic read-only packets over the fixed synthetic workbench adapters."""

import json
from dataclasses import asdict, dataclass
from hashlib import sha256

from apps.fatwa_drafts.revision_audit import build_revision_audit
from apps.intake_workflow import fixtures
from apps.revision_core.revision_comparison import compare_revisions
from apps.revision_core.revision_history import select_revisions

from .batches import BatchOverview, PreparedCase
from .services import WorkbenchCase, WorkbenchDataError

MAX_PACKET_BYTES = 524288
MAX_STRING_CHARS = 131072
MAX_NODES = 4096
MAX_DEPTH = 16


class PacketDataError(WorkbenchDataError):
    """Packet cannot preserve its complete bounded source representation safely."""


@dataclass(frozen=True, slots=True)
class CaseReviewPacket:
    json_bytes: bytes

    @property
    def sha256(self) -> str:
        return sha256(self.json_bytes).hexdigest()

    def payload(self) -> dict:
        """Each consumer receives its own tree; the canonical bytes stay immutable."""
        return json.loads(self.json_bytes)


def serialize_packet(payload: dict) -> bytes:
    """Strict UTF-8 JSON, sorted keys, no clock, normalization or truncation.

    Bound traversal before encoding, then enforce the total encoded byte ceiling.
    Reject floats and arbitrary objects rather than coercing or stringifying them.
    """
    remaining = MAX_NODES

    def validate(value, depth=0):
        nonlocal remaining
        remaining -= 1
        if depth > MAX_DEPTH or remaining < 0:
            raise PacketDataError("packet: structure_limit")
        if isinstance(value, str):
            if len(value) > MAX_STRING_CHARS:
                raise PacketDataError("packet: text_limit")
            value.encode("utf-8", errors="strict")
        elif value is None or type(value) is bool:
            return
        elif type(value) is int:
            if abs(value) > 2**63 - 1:
                raise PacketDataError("packet: integer_limit")
        elif type(value) is dict:
            for key, item in value.items():
                if type(key) is not str:
                    raise PacketDataError("packet: invalid_key")
                validate(key, depth + 1)
                validate(item, depth + 1)
        elif type(value) in (tuple, list):
            for item in value:
                validate(item, depth + 1)
        else:
            raise PacketDataError("packet: unsupported_value")

    try:
        if type(payload) is not dict:
            raise PacketDataError("packet: invalid_payload")
        validate(payload)
        raw = (
            json.dumps(
                payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False
            )
            + "\n"
        ).encode("utf-8", errors="strict")
    except UnicodeError as exc:
        raise PacketDataError("packet: invalid_utf8") from exc
    if len(raw) > MAX_PACKET_BYTES:
        raise PacketDataError("packet: byte_limit")
    return raw


def _source(case: WorkbenchCase, batch: BatchOverview | None) -> dict:
    if isinstance(case, PreparedCase):
        if batch is None or batch.batch_id != case.batch_id:
            raise PacketDataError("packet: missing_original_batch")
        input_text, kind = batch.raw_source, "parsed_row_serialization"
        if batch.input_sha256 != case.payload_sha256:
            raise PacketDataError("packet: batch_identity_mismatch")
    elif case.key == "history":
        input_text, kind = case.raw_source, "serialized_intake"
    else:
        input_text = fixtures.synthetic_payload().decode("utf-8")
        kind = "original_utf8_slice"
        if (
            type(case.source_start) is not int
            or type(case.source_end) is not int
            or not 0 <= case.source_start < case.source_end <= len(input_text.encode("utf-8"))
            or input_text.encode("utf-8")[case.source_start : case.source_end].decode("utf-8")
            != case.raw_source
        ):
            raise PacketDataError("packet: source_slice_mismatch")
    if sha256(input_text.encode("utf-8")).hexdigest() != case.payload_sha256:
        raise PacketDataError("packet: input_digest_mismatch")
    return {
        "kind": kind,
        "label_ar": case.fixture_label,
        "input_text": input_text,
        "input_sha256": case.payload_sha256,
        "text": case.raw_source,
        "text_sha256": sha256(case.raw_source.encode("utf-8")).hexdigest(),
        "start": case.source_start,
        "end": case.source_end,
        "offset_unit": "utf8_bytes_end_exclusive" if case.source_start is not None else None,
    }


def build_packet(
    case: WorkbenchCase,
    batch: BatchOverview | None = None,
    *,
    revision: str | None = None,
    before: str | None = None,
    after: str | None = None,
) -> CaseReviewPacket:
    """Compose one case only; never join by external ID or read persisted events.

    This adapter is called only with code-selected synthetic fixtures by the
    existing loopback-guarded workbench. It accepts no uploaded/path/network data.
    Existing history services retain authority over exact selection and bounds.
    """
    source = _source(case, batch)
    snapshots, observations = [], []
    selection = {"revision": None, "before": None, "after": None}
    comparison = None
    record = case.record
    if record is not None:
        if (
            record.intake.external_id != case.external_id
            or record.intake.question != case.question
            or record.intake.prepared_clip_url != case.prepared_clip_url
        ):
            raise PacketDataError("packet: intake_identity_mismatch")
        audit = build_revision_audit(record, synthetic_fixtures_only=True)
        history = tuple(entry.history_entry for entry in audit.entries)
        selected, _ = select_revisions(
            history,
            str(history[-1].revision.number) if revision is None else revision,
            str(history[-1].revision.number) if revision is None else revision,
        )
        first, last = select_revisions(
            history,
            str(history[0].revision.number) if before is None else before,
            str(history[-1].revision.number) if after is None else after,
        )
        selection = {"revision": selected.number, "before": first.number, "after": last.number}
        changes = compare_revisions(first, last)
        comparison = {
            **asdict(changes),
            "before": first.number,
            "after": last.number,
            "changed": changes.changed,
        }
        for entry in audit.entries:
            snapshots.append(asdict(entry.revision))
            observations.append(
                {
                    "revision": entry.revision.number,
                    "previous_revision": entry.history_entry.previous_number,
                    "changed_fields": entry.history_entry.changed_fields,
                    "references_added": entry.history_entry.references_added,
                    "references_removed": entry.history_entry.references_removed,
                    "reference_positions_changed": entry.history_entry.reference_positions_changed,
                    "changed_metadata": entry.changed_metadata,
                    "observed_state_change": entry.observed_state_change,
                }
            )
    elif any(value is not None for value in (revision, before, after)):
        raise PacketDataError("packet: no_draft_selection")
    errors = [asdict(reason) for reason in case.reasons] if isinstance(case, PreparedCase) else []
    questions = [
        {
            "kind": "intake_issue",
            "evidence_ar": issue,
            "action_ar": "راجع السبب في أصل العينة الاصطناعية وصححه خارج العرض ثم أعد التحضير؛ لا يتغير الأصل هنا.",
        }
        for issue in case.issues
    ]
    for reference in case.references:
        if reference["status"] != "verified":
            questions.append(
                {
                    "kind": "unresolved_reference",
                    "reference_ordinal": reference["reference_ordinal"],
                    "evidence_ar": reference["explanation_ar"],
                    "action_ar": "افحص هوية الإحالة وأسباب النتيجة في المصدر والربط الاصطناعي؛ لا تستنتج اعتمادًا علميًا.",
                }
            )
    payload = {
        "schema": "synthetic-case-review-packet.v1",
        "synthetic_only": True,
        "identity": {
            "case_key": case.key,
            "external_id": case.external_id,
            "input_sha256": case.payload_sha256,
            "batch_id": getattr(case, "batch_id", None),
            "row_ordinal": getattr(case, "row_ordinal", None),
            "source_start": case.source_start,
            "source_end": case.source_end,
        },
        "source": source,
        "intake": {
            "question": case.question,
            "prepared_clip_url": case.prepared_clip_url,
            "prepared": asdict(record.intake) if record else None,
            "original_fields": case.original
            if isinstance(case, PreparedCase)
            else json.loads(case.raw_source),
            "csv_extra_cells": case.csv_extra_cells if isinstance(case, PreparedCase) else (),
        },
        "receipt": {
            "status": case.status,
            "label_ar": case.status_label,
            "intake_state": getattr(case, "intake_state", None),
            "draft_available": record is not None,
            "current_revision": record.current.number if record else None,
            "current_state": record.current.state if record else None,
            "human_review_performed": False if isinstance(case, PreparedCase) else None,
        },
        "selection": selection,
        "snapshots": snapshots,
        "comparison": comparison,
        "snapshot_observations": observations,
        "reference_verification": {
            "scope": "latest_fixture_snapshot" if case.key == "history" else "original_intake",
            "revision": record.current.number if case.key == "history" and record else None,
            "results": case.references,
            "limit_ar": "مطابقة تقنية مع فهرس اصطناعي ثابت فقط؛ لا تثبت صحة علمية أو ملاءمة استشهاد أو فحص أرشيف.",
        },
        "preparation_errors": errors,
        "intake_issues": case.issues,
        "open_questions": questions,
        "persisted_review": {
            "status": "not_loaded",
            "events": None,
            "snapshot_link": "not_established",
            "explanation_ar": "لم تُحمَّل أحداث مراجعة محفوظة ولم يثبت ربطها بهذه اللقطات. اختلاف اللقطات ليس حدث عمل موثقًا، والمعرّف الخارجي وحده لا يثبت الربط.",
        },
        "review_conclusion": None,
        "scholarly_decision": None,
        "holds": [
            "Gate B NOT_PASSED",
            "C/D/E HOLD",
            "Phase01 BLOCKED",
            "SCOPE_DEVIATION_HOLD",
            "NOT_DEPLOYED",
        ],
    }
    return CaseReviewPacket(serialize_packet(payload))
