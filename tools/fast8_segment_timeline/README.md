# Synthetic manual segment timing

Offline adapter for `apps.transcript_pipeline`, with no Django setup, database,
browser, network, media processing or new dependency. The existing pipeline
already rejects invalid intervals and pairs. This adapter adds actionable
diagnostics for each record, coverage gaps (including nested overlap handling),
duplicate spans, declared duration bounds and optional MANUAL cutter cues.

From the repository root, using Python 3.13:

```powershell
python -B -m tools.fast8_segment_timeline tools/fast8_segment_timeline/examples/fabricated.json --synthetic-fixtures-only
python -B -m tools.fast8_segment_timeline tools/fast8_segment_timeline/examples/fabricated.json --synthetic-fixtures-only --durations tools/fast8_segment_timeline/examples/durations.json --export cues-json
python -B -m tools.fast8_segment_timeline tools/fast8_segment_timeline/examples/fabricated.json --synthetic-fixtures-only --export cues-csv
python -B -m unittest discover -s tests/fast8_segment_timeline -v
```

Output is UTF-8 on stdout; redirect with a byte-preserving host or capture
`subprocess.run(..., capture_output=True).stdout` and `Path.write_bytes()`.
Older PowerShell text redirection can re-encode output. Inputs are opened as
bytes and never rewritten. No URLs, UNC/device paths, directory inputs or
symlink/junction paths are accepted by the CLI. Only explicitly fabricated
development fixtures may be supplied; the acknowledgement is not a detector
of private data.

Input is the existing exact `fatwa.synthetic-transcript.v1` JSON envelope,
array, JSONL or CSV contract. Each row supplies `source_id`, `segment_id`,
`pair_id`, `kind` (`question` or `answer`), `start_ms`, `end_ms`, `text`,
`provenance`, `fabricated: true` (CSV: literal `true`). All existing limits
apply: 1 MB, 1,000 records, 20,000 text characters, integer timestamps through
86,400,000 ms. Floats, booleans, exponent notation and strings in JSON are
not milliseconds. CSV uses canonical decimal integers. No rounding occurs.

Optional `--durations` takes an exact source-ID-to-integer-ms JSON object.
These are caller-declared bounds, not measured media metadata. Unknown IDs,
noninteger durations and values outside 1..86,400,000 fail closed. Missing
durations are `NOT_SUPPLIED`; real media is `NOT_CONNECTED`.

Report row numbers are one-based input records (not physical CSV lines).
Error findings block every cue export. Row validation reports the upstream
field/code; malformed envelopes, nonfabricated markers or invalid duration
contracts fail before export. When any row fails, source-level checks/hashes
are `NOT_RUN` rather than describing a partial source as complete. For fully
validated rows, findings cover duplicate IDs/spans, source-scoped pair errors,
overlaps and duration violations. A coverage-frontier overlap cites one
earlier covering record, not an exhaustive quadratic list of all pairs.
Gaps and reordered input are warnings; missing answers are informational.
Gaps never imply missing questions or generate boundaries. Every successful
cue batch also passes the original `segment_file` service.

Cues use supplied intervals, sorted by source/start/end/segment identity.
`question_label` is the exact question `text` of that source/pair for both
question and answer cues; no numbered, shortened or inferred label replaces
it. `HH:MM:SS.mmm` uses integer arithmetic. JSON has a final LF; CSV records
use CRLF, preserve CRLF inside quoted labels, and contain `mode=MANUAL`.
CSV is an exact interchange file: import label/identity columns as text,
not spreadsheet formulas. JSON is available for consumers that cannot do so.

`input_sha256` hashes exact input bytes. `source_sha256` matches the existing
pipeline's sorted original-row canonical JSON, including its final LF.
`segment_sha256` uses that same encoding over one original validated row;
there was no upstream per-segment digest to replace. Neither is a recording
hash. Text, Unicode normalization, whitespace, provenance and original IDs
are preserved. CSV/JSON/JSONL presentations can share row/source hashes while
retaining distinct input-file hashes. A changed line ending inside a label
changes its segment and source hashes.

Exit 0: valid technical timeline (warnings may remain). Exit 1: diagnostics
contain errors, invalid input, or blocked cue export. Exit 2: CLI arguments
or missing synthetic acknowledgement. Diagnostics report emits JSON even on
timing errors; blocked cues emit no stdout. CLI error text does not echo
submitted paths or values.

This is a local manual editing aid, not an automated cutter, player,
transcriber, question detector or publishing interface. There is no media
download, crop/edit, scholarly approval, role grant, production write or
migration. Owner archive acceptance is NOT_RUN / NOT_SUPPLIED.

Gate B NOT_PASSED; C/D/E HOLD; Phase01 BLOCKED; SCOPE_DEVIATION_HOLD;
NOT_DEPLOYED; U03/U10 OWNER_APPROVAL_PENDING.
