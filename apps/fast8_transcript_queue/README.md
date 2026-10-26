# FAST8 synthetic transcript-to-intake queue

Development-only, offline, **EPHEMERAL**. This adapter connects existing domain
services rather than adding ingestion, persistence, a public route or a fatwa.
Base: `92fa517ecdefe3f1a92a1ab145ff55943474df44` (FAST7 CI Draft PR #134).

## Working flow

1. `apps.transcript_pipeline.segment_file` validates explicitly fabricated,
   manually segmented JSON/JSONL/CSV: exact fields, source/pair/segment identities,
   integer milliseconds, per-source non-overlap and one question per pair.
2. Its unchanged question-only export enters `apps.prepared_pipeline.prepare_batch`.
   No media or scholarly reference is invented. Missing media means editor review;
   references remain unverified and **no DraftRecord is created**.
3. `build_transcript_queue` binds the two actual outputs, rejecting missing or
   ambiguous source/segment/pair references and mismatched prepared identities.
   Answers stay in source evidence. An unsupplied answer is `NOT_SUPPLIED`.
4. A separate immutable snapshot supplies real `editorial_queue.QueueRow` objects
   and delegates navigation/filtering to `editorial_queue.select_queue`. It never
   calls the legacy catalog builder or adds links to its fixed 20 cases.

## Pure Python API

```python
from apps.fast8_transcript_queue import build_transcript_queue

queue = build_transcript_queue(raw_bytes, ".json", synthetic_fixtures_only=True)
entry = queue.entries[0]
same_entry = queue.resolve(entry.source_id, entry.pair_id, entry.source_sha256)
selection = queue.select(key=entry.queue_key, status="review-without-draft", refs="missing")
report_bytes = queue.json_bytes()
question_only_bytes = queue.prepared_bytes()
```

`resolve` requires the complete exact source revision/pair identity. Missing or
wrong revisions raise `ValidationError`; it never joins by a bare pair ID. Queue
selection follows the existing service: unknown case keys yield no selection.
Different sources may reuse a pair/segment ID without collision. Records have
no global cache and expire when the caller releases the snapshot.

Bounds are inherited from both source services: at most 1,000 segments, 1,000,000
input bytes, 20,000 characters per text, and timestamps within 86,400,000 ms.
The prepared export is also bounded to 1,000,000 bytes. One question per pair
means at most 1,000 queue entries; no output repeats an unbounded input stream.

## Identity and evidence

- `input_sha256`: SHA256 of exact supplied bytes (including BOM/newlines).
- `source_sha256`: existing transcript service's canonical digest of all validated
  segments for that source revision; **not a digest of an unavailable recording**.
- `external_id`: unchanged transcript service identity, binding source/revision/pair.
- `prepared_payload_sha256`: SHA256 of unchanged prepared-export bytes.
- Question/answer segment digests: canonical sorted compact UTF-8 JSON plus LF.
  Segment text retains exact Arabic Unicode, spaces, CR/LF and millisecond values.
- Queue `payload_sha256` identifies the input file. Queue `source_sha256` identifies
  the canonical question segment serialization; source revision is on the entry.
  Byte offsets are `None`, because canonical serialization is not an input slice.

Queue keys use a distinct `transcript-origin-` namespace. Batch IDs also bind the
exact input payload. Reordering equivalent source rows preserves external/source
identities but changes the input digest; changing answer evidence changes the
source revision and therefore the external and queue identities.

## Deterministic offline CLI

```powershell
python -B -m tools.fast8_transcript_queue tests/fast8_transcript_queue/fixtures/fabricated_spans.json --synthetic-fixtures-only
python -B -m tools.fast8_transcript_queue tests/fast8_transcript_queue/fixtures/fabricated_spans.json --synthetic-fixtures-only --export prepared
```

The committed fixture is explicitly fabricated test text, not owner content.
The CLI reads a bounded local regular file after explicit acknowledgement and
writes UTF-8 JSON to stdout only. It refuses network/device paths, relative-drive
paths and known symlink/junction components. It is a developer tool, not a
filesystem sandbox against concurrent path replacement. Errors use fixed codes
on stderr with no input text/path and no partial output. Exit codes: 0 success,
1 invalid/unreadable input, 2 missing acknowledgement/invalid arguments.

Synthetic markers are caller attestations, not private-data detection. Supply
only fabricated fixtures. There are no recordings, external fetches, AI, database
writes, migrations, role operations, scholarly answers, approval or publishing.

## Validation and gates

See `VALIDATION.md` for commands, fixture digest, measured results and limitations.
No UI route is added, so lane browser acceptance is `NOT_RUN` (no browser surface).
PostgreSQL is `NOT_RUN` (no database path). Owner archives are `NOT_SUPPLIED`.
Shared CI does not automatically discover this lane's new suite; the coordinator
must wire its explicit command when integrating. Existing B6/C6/D6 runs are
reported separately and do not constitute acceptance of the new tests.

Gate B **NOT_PASSED**; C/D/E **HOLD**; Phase01 **BLOCKED**;
**SCOPE_DEVIATION_HOLD**; **NOT_DEPLOYED**;
U03/U10 **OWNER_APPROVAL_PENDING**. No merge or deployment is authorized.
