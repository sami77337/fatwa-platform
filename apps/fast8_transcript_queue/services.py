"""Compose existing transcript, prepared intake and editorial queue contracts.

Only raw, explicitly fabricated manual spans enter this API. Reports/pair maps
from callers are not accepted as authority. Nothing is persisted or published.
"""

import json
from dataclasses import asdict, dataclass
from hashlib import sha256

from apps.editorial_queue.services import QueueRow, QueueSelection, select_queue
from apps.editorial_workbench.services import WorkbenchCase
from apps.fatwa_drafts.intake import ValidationError
from apps.prepared_pipeline import prepare_batch
from apps.transcript_pipeline import segment_file


def _encoded(value: object) -> bytes:
    return (
        json.dumps(
            value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False
        )
        + "\n"
    ).encode("utf-8")


def _require(condition: bool, code: str) -> None:
    if not condition:
        raise ValidationError(f"transcript_queue: {code}")


@dataclass(frozen=True, slots=True)
class SegmentEvidence:
    """Exact validated strings/milliseconds, with a canonical segment digest.

    Canonical JSON is explicitly a serialization, not a byte slice of the input.
    The enclosing entry's input_sha256 identifies the original file bytes.
    """

    source_id: str
    segment_id: str
    pair_id: str
    kind: str
    start_ms: int
    end_ms: int
    text: str
    provenance: str
    fabricated: bool

    def json_bytes(self) -> bytes:
        return _encoded(asdict(self))

    @property
    def sha256(self) -> str:
        return sha256(self.json_bytes()).hexdigest()


@dataclass(frozen=True, slots=True)
class TranscriptEntry:
    source_id: str
    pair_id: str
    source_sha256: str
    input_sha256: str
    prepared_payload_sha256: str
    external_id: str
    queue_key: str
    question: SegmentEvidence
    answer: SegmentEvidence | None
    prepared_statuses: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class TranscriptQueue:
    """Independent EPHEMERAL snapshot; no legacy case associations or mutation API."""

    entries: tuple[TranscriptEntry, ...]
    rows: tuple[QueueRow, ...]
    _report_bytes: bytes
    _prepared_bytes: bytes

    def json_bytes(self) -> bytes:
        return self._report_bytes

    def prepared_bytes(self) -> bytes:
        """Unchanged question-only export supplied by transcript_pipeline."""
        return self._prepared_bytes

    def select(
        self,
        *,
        q: str = "",
        status: str = "",
        refs: str = "",
        batch: str = "",
        key: str | None = None,
    ) -> QueueSelection:
        """Use the real queue's stable filters, detail selection and neighbors."""
        return select_queue(self.rows, q=q, status=status, refs=refs, batch=batch, key=key)

    def resolve(self, source_id: str, pair_id: str, source_sha256: str) -> TranscriptEntry:
        """Resolve only a complete exact source revision/pair reference; never guess."""
        matches = tuple(
            entry
            for entry in self.entries
            if (entry.source_id, entry.pair_id, entry.source_sha256)
            == (source_id, pair_id, source_sha256)
        )
        _require(len(matches) == 1, "absent_or_ambiguous_origin_reference")
        return matches[0]


def build_transcript_queue(
    raw: bytes,
    suffix: str,
    *,
    synthetic_fixtures_only: bool = False,
) -> TranscriptQueue:
    """Bounded all-or-nothing adapter over <=1 MB/1000 manual transcript spans.

    The acknowledgement is an attestation, not a private-data detector. Existing
    segment_file owns parsing, exact identities, overlap and ambiguous-pair checks.
    prepare_batch owns question validation/findings. Missing answers are explicit;
    missing segment references or mismatched preparation fail closed. No media or
    citation is invented to make a scholarly DraftRecord eligible for creation.
    """
    transcript = segment_file(raw, suffix, synthetic_fixtures_only=synthetic_fixtures_only)
    source_report = json.loads(transcript.json_bytes())
    prepared_raw = transcript.prepared_bytes()
    prepared = prepare_batch(prepared_raw, synthetic_fixtures_only=True)
    payload_sha = sha256(raw).hexdigest()
    prepared_sha = sha256(prepared_raw).hexdigest()
    _require(source_report["input_sha256"] == payload_sha, "input_digest_mismatch")
    _require(
        source_report["preparation"]["export_sha256"] == prepared_sha
        and prepared.report["input_sha256"] == prepared_sha,
        "prepared_digest_mismatch",
    )
    _require(not prepared.drafts, "unexpected_draft")
    pairs, reports = source_report["pairs"], prepared.report["items"]
    _require(len(pairs) == len(reports), "prepared_count_mismatch")
    sources = {source["source_id"]: source["source_sha256"] for source in source_report["sources"]}
    _require(len(sources) == len(source_report["sources"]), "ambiguous_source_identity")
    segments = {
        (segment["source_id"], segment["segment_id"]): SegmentEvidence(**segment)
        for segment in source_report["segments"]
    }
    _require(len(segments) == len(source_report["segments"]), "ambiguous_segment_identity")
    seen_pairs, seen_external_ids, used_segments = set(), set(), set()
    entries, rows, serialized = [], [], []
    batch_id = "transcript-origin-" + payload_sha
    for ordinal, (pair, report) in enumerate(zip(pairs, reports, strict=True), 1):
        source_id, pair_id = pair["source_id"], pair["pair_id"]
        pair_key = (source_id, pair_id)
        external_id = pair["external_id"]
        _require(
            pair_key not in seen_pairs and external_id not in seen_external_ids,
            "ambiguous_pair_identity",
        )
        seen_pairs.add(pair_key)
        seen_external_ids.add(external_id)
        _require(sources.get(source_id) == pair["source_sha256"], "absent_or_mismatched_source")

        def evidence(kind: str) -> SegmentEvidence | None:
            segment_id = pair[f"{kind}_segment_id"]
            if kind == "answer" and segment_id is None:
                return None
            key = (source_id, segment_id)
            segment = segments.get(key)
            _require(segment is not None, "absent_segment_reference")
            _require(
                segment.pair_id == pair_id and segment.kind == kind, "segment_identity_mismatch"
            )
            _require(key not in used_segments, "ambiguous_segment_reference")
            used_segments.add(key)
            return segment

        question, answer = evidence("question"), evidence("answer")
        expected = dict(
            external_id=external_id,
            question=question.text,
            prepared_clip_url="",
            staff_notes="",
            reference_links=[],
        )
        _require(
            report["row"] == ordinal and report["original"] == expected,
            "prepared_identity_mismatch",
        )
        _require(report["draft"] is None and not report["references"], "unexpected_enrichment")
        _require("blocked-invalid" not in report["statuses"], "prepared_question_rejected")
        queue_key = "transcript-origin-" + external_id
        entry = TranscriptEntry(
            source_id,
            pair_id,
            pair["source_sha256"],
            payload_sha,
            prepared_sha,
            external_id,
            queue_key,
            question,
            answer,
            tuple(report["statuses"]),
        )
        entries.append(entry)
        case = WorkbenchCase(
            key=queue_key,
            external_id=external_id,
            question=question.text,
            prepared_clip_url="",
            raw_source=question.json_bytes().decode("utf-8"),
            source_start=None,
            source_end=None,
            payload_sha256=payload_sha,
            fixture_label="مقاطع يدوية مختلقة؛ تسلسل دليل مصدر اصطناعي؛ EPHEMERAL",
            status="review",
            status_label="استلام تفريغ اصطناعي يحتاج مراجعة بشرية",
            issues=tuple(f"{issue['field']}: {issue['code']}" for issue in report["findings"]),
            record=None,
            references=(),
        )
        rows.append(QueueRow(case, batch_id, (), 0, 0, question.sha256))
        serialized.append(
            dict(
                asdict(entry),
                question_segment_sha256=question.sha256,
                answer_segment_sha256=answer.sha256 if answer else None,
                answer_status="SOURCE_EVIDENCE_ONLY" if answer else "NOT_SUPPLIED",
            )
        )
    _require(used_segments == set(segments), "unreferenced_segment")
    report = dict(
        schema="fatwa.fast8-transcript-queue.v1",
        origin="transcript",
        storage="EPHEMERAL",
        synthetic_only=True,
        segmentation="manual",
        human_editing_performed=False,
        publication_allowed=False,
        answer_role="SOURCE_EVIDENCE_ONLY",
        input_sha256=payload_sha,
        input_format=source_report["input_format"],
        prepared_payload_sha256=prepared_sha,
        batch_id=batch_id,
        gates=dict(source_report["gates"], **{"U03/U10": "OWNER_APPROVAL_PENDING"}),
        entries=serialized,
        prepared=prepared.report,
        summary=dict(record_count=len(entries), draft_count=0, review_count=len(entries)),
    )
    return TranscriptQueue(tuple(entries), tuple(rows), _encoded(report), prepared_raw)
