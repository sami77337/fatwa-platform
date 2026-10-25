# Offline synthetic transcript pipeline

User specification: FAST5 manually identified question/answer segments, bounded
CSV/JSON/JSONL, exact Arabic and timestamps, overlap validation, source hashes
and provenance. Existing FAST4 base: `262fa3d`.

## Design and implementation plan

Use a pure Python service and a local command line consumer. Reuse FAST4's strict
JSON parser, intake limits, text validation and prepared schema; do not duplicate
the preparation pipeline. A web upload route is unnecessary for offline use.

- [x] Write and run failing service tests for exact text, millisecond intervals,
  fabrication acknowledgement, shape/size limits, overlaps and explicit pairing.
- [x] Implement `segment_file(raw, suffix, *, synthetic_fixtures_only=False)` in
  `apps/transcript_pipeline/__init__.py` and immutable records. Validate every row
  before returning any export. Half-open intervals may touch, never overlap
  within one source. Pair identity is scoped by source; require one question and
  at most one answer, with the answer after the question. No inferred segments.
- [x] In parallel implement `tools/transcript_pipeline` CLI and its tests;
  read bounded local files, require acknowledgement, emit deterministic UTF-8.
- [x] Verify exported question records through the actual FAST4 `prepare_batch`.
  Its schema has no answer field: preserve answers in the transcript report.
  No invented media links, reference pointers, approvals or readiness claims.
- [x] Run new and directly affected suites and one independent final review.
  No blocking findings; see `VALIDATION_FAST5.md`.
- Delivery: commit/push this isolated branch and open one draft PR against
  `codex/20261025-fast4-integration-pc2`; the PR records the delivered commit.

## Review focus

Exact Arabic whitespace/diacritics and CR/LF must survive. Booleans/floats must
not become timestamps. Reject duplicate JSON keys/CSV headers, CSV ragged rows,
unknown fields, duplicate segment identities, ambiguous pairs, orphan answers,
nested overlaps, malformed Unicode and over-limit payloads. Never echo submitted
content in errors. Source hash covers canonical validated rows per source, not
unavailable media; original file SHA256 covers exact input bytes. Report always
retains original row order and timestamps, with deterministic canonical export
ordering and no clock/random fields. Synthetic declarations are caller
attestations, not proof that submitted text was fabricated.

Gate B NOT_PASSED; C/D/E HOLD; Phase01 BLOCKED; SCOPE_DEVIATION_HOLD;
NOT_DEPLOYED. No models, migrations, public routes or persistent editorial writes.
