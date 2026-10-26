# FAST8 segment-timeline validation

Reviewed base: `92fa517ecdefe3f1a92a1ab145ff55943474df44` (Draft PR #134).
Target: `codex/20261026-fast7-ci-integration-pc1`.
Runtime: Windows, Python 3.13.15; existing dependencies; no installations.

Focused local execution:

- `python -B -m unittest discover -s tests/fast8_segment_timeline -v`:
  32 passed, zero failures/skips (22 service, 10 CLI tests).
- `python -B -m unittest discover -s tests/transcript_pipeline -v`:
  23 passed, zero failures/skips; directly reused contract and CLI.
- Ruff check and format check over all three owned directories: passed.
- No database, browser or real-source acceptance is required for this offline
  adapter. No such local acceptance is claimed. Shared CI workflows are
  unchanged; they do not automatically register the new lane's test directory.
  The integration coordinator must run the explicit focused command above.

The test worker found a real `TypeError` when malformed unhashable source IDs
were supplied alongside duration bounds. Source membership now considers
string identities only; both service and process-level regressions pass.
No negative assertion was weakened.

All input is explicitly fabricated. Fixture identities (exact committed LF
JSON bytes; embedded question text includes escaped CRLF):

- `examples/fabricated.json` SHA256:
  `e0c594cbed6b0af7c1fd03afe75cdc596994eb3d00643ef2559cd9834c1ac461`
- `examples/durations.json` SHA256:
  `5aa2a999571be637a1b34b361228c86536745f430718a6b4a3964930f42ec8a7`

An actual CLI smoke run of those fixtures with the declared durations emitted
the exact gaps `[1001,1003)` and `[2007,2010)`, with upstream contract PASS.
Both JSON and CSV cue exports exited 0 and retained the supplied boundaries.
Focused tests independently cover CRLF, Unicode separators, exact Arabic,
integer precision, nested overlaps, source/pair isolation, malformed inputs,
duration limits, blocked exports, input immutability and source digest parity.

One independent final review completed without actionable findings: the
reviewer ran the 32 focused tests and 99 malformed-field probes, with no
unexpected exception or invalid cue export. Both delegated tasks are complete.

Final delivery SHA, remote identity and actual
B6/C6/D6 statuses are recorded in the Draft PR rather than self-referencing
this document. No automatic CI result is presented as official gate approval.

NOT_DEPLOYED / GATES_HOLD / SCOPE_DEVIATION_HOLD.
Gate B NOT_PASSED; C/D/E HOLD; Phase01 BLOCKED;
U03/U10 OWNER_APPROVAL_PENDING. Owner-source archives NOT_SUPPLIED;
real media NOT_CONNECTED; owner-source acceptance NOT_RUN.
