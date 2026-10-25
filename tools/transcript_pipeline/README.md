# Offline synthetic transcript fixtures

This development command validates **manually supplied** question and answer
segments from fabricated transcripts. It has no audio input, speech recognition,
automatic boundary detection, network access, AI integration, database writes,
HTTP endpoints, publishing or approval actions. Do not supply real or private
records. `--synthetic-fixtures-only` and each row's `fabricated` declaration are
caller attestations; they cannot establish whether text was actually fabricated.

From the repository root, with Python 3.13:

```console
python -m tools.transcript_pipeline tools/transcript_pipeline/examples/synthetic-manual.json --synthetic-fixtures-only
python -m tools.transcript_pipeline tools/transcript_pipeline/examples/synthetic-manual.json --synthetic-fixtures-only --export prepared
python -m unittest tests.transcript_pipeline.test_cli -v
```

The default `--export report` preserves question and answer text, timestamps,
source identities, and provenance. Both exports produce deterministic UTF-8 JSON
on stdout after complete validation. There is no output-file option; the command
does not change the input or create output files. A caller can capture stdout.

## Input contract

Accepts local regular UTF-8 `.csv`, `.json`, or `.jsonl` files. UNC/network path
syntax, Windows device names, drive-relative paths, and direct symlink/junction
inputs are rejected. Use a trusted local directory; this command is not a
filesystem sandbox for paths through mounted drives or ancestor links.
JSON accepts an array or
`{"schema":"fatwa.synthetic-transcript.v1","items":[...]}`. JSONL has one segment
object per physical line. CSV has the exact column names below. CSV text containing
commas, quotes or line breaks must use CSV quoting. JSON strings must escape line
breaks. Unknown/missing fields and malformed input are rejected.

| Field | Meaning |
|---|---|
| `source_id` | Fabricated source identity; not a media URL or catalog reference |
| `segment_id` | Unique segment identity within its source |
| `pair_id` | Explicit question/answer pair identity within its source |
| `kind` | Exactly `question` or `answer` |
| `start_ms`, `end_ms` | Integer milliseconds, `0 <= start_ms < end_ms <= 86400000` |
| `text` | Original fabricated segment text, retained without trimming or normalization |
| `provenance` | Explicit fabricated origin description supplied by the caller |
| `fabricated` | JSON boolean `true`; CSV literal `true` |

The file is limited to 1,000,000 bytes; the CLI reads at most 1,000,001 bytes so it
can reject oversized input without reading the whole file. There must be 1–1000
rows. IDs are at most 100 characters, text at most 20,000, and provenance at most
500; these fields must be nonblank. IDs cannot have surrounding whitespace or
Unicode control/format characters. Timestamps cannot be
booleans, floats, negative values, or zero-length intervals. Per-source intervals
are half-open `[start_ms, end_ms)`: an interval ending at 1000 may touch another
starting at 1000, but intersections are rejected even across different pairs.
Intervals in different sources are independent.

Each source/pair requires one question and at most one answer. An answer must
follow its question in time. A question without an answer is allowed; the command
does not invent an answer, pair association, timing, or segment boundary. Every
row is validated before either export becomes available; a late invalid row
prevents all output.

## Source identity and hashes

The report's input SHA256 covers the exact file bytes, including encoding marks,
whitespace and line endings. Each source hash covers its validated rows sorted
by `(start_ms, end_ms, segment_id)`. The sorted array is serialized as UTF-8 JSON
with `ensure_ascii=False`, `sort_keys=True`, `separators=(",", ":")`,
`allow_nan=False`, and one trailing LF, then hashed with SHA256. CSV timestamps
are integers and `fabricated` is boolean `true` in these canonical rows. All
fields, including exact text and provenance, contribute to that hash.

Thus equivalent source rows in different input formats have the same source
hash even when their raw file hashes differ. These hashes identify supplied
fixture content, not an audio recording or verified scholarly source.
Prepared IDs are `transcript-` followed by the SHA256 of
`[source_id, source_sha256, pair_id]` serialized by the same JSON rules. A content
change within a source therefore changes its source hash and prepared IDs.

## Export and downstream review

`--export prepared` emits `fatwa.prepared-intake.v1` question records for the
existing `apps.prepared_pipeline.prepare_batch` consumer. Question text remains
exact. Clip URL, references and staff notes remain empty because the input does
not supply those fields. The prepared contract has no answer field, so exact
answer text stays in the report. Retain the report alongside the prepared export
when reviewing pairs or their provenance.

Empty clip metadata requires editor review in the existing prepared pipeline;
empty references remain unverified, and no draft is created. This export does not
establish readiness, scholarly correctness, reference support, or human approval.

## Diagnostics and gates

Successful exports exit 0. Failures leave stdout empty and put only a fixed code
on stderr, without echoing the path, input text or malformed argument values:

| Code | Exit status |
|---|---|
| `ARGUMENTS_INVALID` | 2 |
| `SYNTHETIC_FIXTURES_REQUIRED` | 2 |
| `LOCAL_FILE_READ_FAILED` | 1 |
| `TRANSCRIPT_VALIDATION_FAILED` | 1 |

Gate B **NOT_PASSED**; Gates C/D/E **HOLD**; Phase01 **BLOCKED**;
**SCOPE_DEVIATION_HOLD / NOT_DEPLOYED**. U03/U10 owner policy acceptance remains
pending. This module grants no permissions and enables no private-user operations.
The example is a newly fabricated test fixture, not an owner-supplied corpus or
evidence of original-source acceptance.
