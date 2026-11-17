# Local transcript review workbench

Built on `e000cdc22c1a0dfd1e0e38eb8fd7cfbfc392487e` (#209), after checking the latest GitHub work on 17 November 2026. The existing transcript parser, timeline diagnostics and ephemeral queue are reused. This adds a usable Arabic browser journey, not another parser or case store.

## Run

With Python 3.13 and the repository requirements installed:

```sh
FATWA_PRODUCTION=0 python -m apps.fast8_transcript_queue.workbench --port 8016
```

Open `http://127.0.0.1:8016/transcripts/`. Download the supplied synthetic example, upload it with the explicit fabricated-data acknowledgement, choose a segment, manually correct its times or replace its text, then download the ZIP. The server listens only on loopback. Its signing key is generated per start; restarting invalidates unsaved page state. Downloaded review/checkpoint ZIPs can be restored after restarting. The standalone settings profile is disabled unless explicitly enabled by the launcher. No shared settings, URLs, casework models or migrations are changed.

## Working behavior

- Import the existing JSON/CSV/JSONL contract: maximum 1,000,000 bytes and 1,000 spans. Structural/row errors reject the file; timeline and answer-pair errors remain visible for manual repair. Duplicate segment/question identities or completely absent question spans still require correction in the original file and reimport.
- Arabic RTL page, keyboard forms, segment selection, exact source/provenance and question/answer distinction. Overlaps block export; uncovered intervals remain warnings, not inferred missing text.
- Explicit text replacement prevents browser textarea line-ending normalization from silently changing text during timing-only edits. Original bytes are always retained. Edits preserve source/segment identities, roles, provenance and fabricated markers. Changed source content obtains new source hashes and external IDs through the existing services.
- Select an answer span to manually link it to one unambiguous question from the same source. The UI previews full question text and times and identifies occupied/current pairs. It refuses a target already containing another answer; no automatic replacement, cross-source linking or role change. This repairs orphan answers or multiple answers accidentally sharing one pair without editing the file externally. Linking never changes text/timestamps; invalid chronology still blocks final export and must be corrected manually.
- The portable deterministic ZIP includes original and reviewed input, the existing question-only prepared contract, full queue/source-answer evidence, timeline and cues JSON, and a file-size/SHA-256 manifest. ZIP member names are fixed, never derived from user filenames or source IDs. Hashes identify bytes, not scholarly approval or authenticated origin.
- Download **حفظ مراجعة للاستكمال لاحقًا** even when overlaps still block final export. This checkpoint contains only original/current input and its manifest; it cannot masquerade as prepared questions. Restore either this ZIP or a completed review ZIP through the same upload form, keeping the original bytes, latest edits and revision counter. A fresh browser or a restarted server can resume the downloaded file.
- The selected segment displays its original/current text and timestamps when changed, plus the number of changed segments. Timing-only edits still preserve CRLF and literal Unicode. Restoring `reviewed.*` alone intentionally starts a **new** review; use the full ZIP to retain original lineage.
- There is no hidden browser/server persistence, cloud transfer, automatic transcription, media cutting or generated answer.

The browser carries signed, CSRF-bound review state (30-minute inactivity window, 100 revisions, at most 4 MB review-action body). It is not encrypted; only fabricated data is permitted. State is rejected in another browser or after expiry. Explicitly downloaded ZIPs are portable unsigned artifacts, not browser credentials. Exports are POST/CSRF actions; all responses are no-store/noindex with CSP. Host, query, method, file-count and body-size boundaries are checked. No DB, disk upload storage or production adapters are used.

ZIP imports are bounded to 16,000,000 bytes (multipart request cap 16,100,000), with exactly three checkpoint members or seven final-review members. Only the application's fixed filenames and uncompressed `ZIP_STORED` format are accepted: no extraction, paths, symlinks, duplicate entries, encryption or compressed members. Original/current inputs remain limited to 1 MB each. Restoring reparses synthetic markers and immutable source/segment/question-pair identities, regenerates every report/manifest from the validated source, and requires exact file equality. Updating hashes on a counterfeit prepared report cannot make it authoritative. These checks establish internal consistency only: a fully rebuilt unsigned bundle cannot prove its author or independently authenticate its claimed original/revision counter.

This resume/compare increment builds on #211 (`a540777bfc0b719d870eb2deef7e5e36a8fb3526`), after checking the campaign integration head `48f9fe3f93664e0060b1d75f1358b27bce7a1471`; no newer transcript implementation was present there. Both increments stay isolated to this media package and its tests.

The manual-pairing increment builds on #215 (`59fdb5e361ed28cfd955d8448a4a6d8241ab501a`), after checking campaign head `f6cb8766310fb339872cdffb20613cc0de7dd1a1`. It does not change shared integration files.

### Pair provenance and bundle compatibility

Only answer `pair_id` may be relinked; a question's pair identity stays immutable. When an answer's current pair differs from its original pair, the bundle/checkpoint uses schema **v2** and its change entry records `original_pair_id` and `reviewed_pair_id` alongside the source/segment identity. The comparison UI displays both. Bundles without pair changes retain byte-compatible v1 semantics. Restore supports v1 and v2 and reconstructs the applicable schema, so a relinked artifact cannot be mislabeled v1. Original bytes and original pair remain available; current queue/prepared external IDs bind the actual reviewed source revision. No source-answer relationship is authenticated by these unsigned artifacts.

## Integration handoff

Per the coordinator's isolation direction, durable case binding is deliberately **NOT_CONNECTED**. The `apps.casework*` packages and shared templates/config remain untouched. The future integrator can consume `prepared-questions.json` through the existing prepared intake contract and use `queue.json`'s exact `(source_id, source_sha256, pair_id, external_id)` plus the manifest's original/reviewed byte digests for provenance. An imported source answer must stay `SOURCE_EVIDENCE_ONLY`; this work grants no approval, requester access, delivery proof or publication.

Do not call the existing WEBSITE-only case intake as if a transcript came from a website requester. A future adapter needs an explicit source-channel/evidence binding and scoped authorization in the durable case model. The unsigned bundle and its hashes cannot supply that authority.

## Focused checks

```sh
FATWA_PRODUCTION=0 FATWA_TRANSCRIPT_SECRET=synthetic-test-only python manage.py test \
  tests.fast8_transcript_queue.test_workbench \
  tests.fast8_transcript_queue.test_workbench_http \
  tests.fast8_transcript_queue.test_resume \
  tests.fast8_transcript_queue.test_pairing \
  --settings=apps.fast8_transcript_queue.workbench.settings
```

Real Chromium smoke (install optional `playwright==1.65.2`; requires `chromium` on PATH or `CHROME_BIN`):

```sh
python -m tests.fast8_transcript_queue.browser_workbench
```

This exercises upload with orphan answer and overlap → unfinished timing edit → checkpoint download → restore in a fresh browser → compare with original → explicitly pair answer to question → repair timing → final v2 export at 320×780 and 1280×900. It verifies original bytes, corrected timestamps, current pair identity, literal CRLF text, RTL, no overflow, zero page errors and zero requests outside the local origin. Results/screenshots stay under ignored `.local/qa/transcript-workbench/`.

Resume increment evidence: **22/22** focused checks passed (8 new resume cases plus 14 affected workbench cases); Chromium **154.0.8037.57** passed the above journey at both viewports with zero page errors/external requests. These are local results, not a CI or production acceptance claim.

Pairing increment evidence: **29/29** focused checks passed (7 new pairing cases plus the 22 affected review/resume cases). The expanded Chromium journey passed with explicit orphan-answer repair and final v2 export at both viewports, zero page errors/external requests. Ruff, formatting and diff checks passed. No database or shared-case integration test is claimed for this isolated media slice.

**NOT_DEPLOYED / GATES_HOLD / ACCEPTANCE_HOLD.** No main merge, no live data, no acceptance percentage. PostgreSQL tests are not applicable to this stateless slice and are not claimed.
