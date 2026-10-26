# Synthetic editorial duplicate candidates

The service finds equal original question text and conservative normalized-text
matches across the existing fixed editorial cases and prepared batches. It reuses
`apps.editorial_queue.services.build_queue_catalog()` and its authoritative
workbench adapters. Rejected intake rows remain eligible when they contain text;
this does not create a draft or change their rejection status. Malformed batches
remain visible as failed coverage with zero invented cases.

Run offline from the repository root:

```text
python -B -m tools.editorial_duplicate_candidates --synthetic-fixtures-only
```

The CLI reads only built-in invented fixtures and emits deterministic UTF-8 JSON.
It does not accept a file or network source. The public pure API is:

```python
from apps.editorial_duplicate_candidates.services import (
    build_duplicate_report,
    detect_candidates,
    normalize_text,
)

report = build_duplicate_report(synthetic_fixtures_only=True)
payload = report.json_bytes()
# For in-memory synthetic test/adaptor rows with the existing QueueRow contract:
report = detect_candidates(rows, synthetic_fixtures_only=True)
```

Every entry preserves its canonical workbench case key. External IDs are only
source metadata: equal IDs neither join cases nor establish candidates without
equal text. Every unordered matching pair appears once, including cross-batch
pairs. Exact original text takes precedence over normalized matching. The output
is ordered by canonical keys and is independent of input order. It contains no
timestamps, scores, clusters, winners, inferred aliases, or record merges.

The normalization contract `nfc-arabic-vowels-whitespace-v1` applies these steps:

1. Unicode NFC, retaining canonical composed/decomposed equivalence.
2. Remove only U+064B through U+0652 (Arabic vowel marks, shadda and sukun).
3. Collapse Unicode whitespace to one ASCII space and trim, including CRLF.

Hamza and madda are preserved, including when NFC composes them with a letter.
Dagger alef, tatweel, letter distinctions, punctuation, Latin case, joiners and
other marks are preserved. There is no NFKC, transliteration, fuzzy similarity,
word reordering, stemming, or scholarly judgement. Removing Arabic marks can
change meaning; a normalized candidate requires human comparison. Each case
lists its actual transformation codes and exact/normalized text SHA-256. The
candidate reason records exact equality or conservative equality and the
transformations involved. Empty/mark-only and non-alphanumeric-only text are
explicit exclusions, not matches; missing or invalid source text is also
reported as excluded.

Source identity includes canonical key, batch ID, source row ordinal, external
ID, payload SHA-256, source-text SHA-256, field (`question` or the authoritative
prepared `title` fallback), original byte offsets when available, and CSV excess
cells. Fixed intake text uses original UTF-8 slices. The history source is the
existing serialized intake envelope. Prepared source text is serialization of
parsed fields, **not original file bytes**; its offsets stay null. CSV excess
cells are retained separately because the authoritative row serialization omits
them. The original input-file hash plus row ordinal binds that provenance.

The core rejects duplicate canonical keys/source locations, mismatched row
hashes, source/question or external-ID disagreement, invalid UTF-8, inconsistent
prepared batch hashes, duplicate JSON fields, non-JSON numeric constants, and
unsupported fixed key conventions. It bounds 1,000
rows, 65,536 UTF-8 bytes per text, 2,097,152 bytes of source/text/metadata in total,
and 10,000 candidate pairs. Exceeding a bound raises `DuplicateCandidateError`;
there is no truncation presented as complete. Candidate count is checked before
pair materialization. Raw text is bounded before parsing. Report objects and
their data are immutable; `to_dict()` creates detached structures.

For caller-supplied rows, the payload digest is an asserted identity: the pure
core cannot verify a complete file it was not given. The built-in adapter obtains
its provenance from the authoritative source-validating services and additionally
checks prepared source hashes, row coverage and batch identity. Synthetic
acknowledgement is required but cannot prove that arbitrary caller data is
synthetic; do not supply real or private records. Neither API verifies owner ZIPs
or PostgreSQL acceptance.

The stock FAST6 catalog has 20 cases across the original collection and four
prepared inputs (one malformed). At implementation smoke check, 17 cases were
eligible, 3 excluded, and 11 exact pairs were found; there are no normalized-only
pairs in these unchanged stock fixtures. Focused regression fixtures exercise
normalized-only matching without modifying the authoritative fixtures.

No models, migrations, persistence, HTTP routes, permissions, scientific
approvals, publication, media retrieval or deployment are added. No data
migration is needed; reverting this feature removes only its new files.

Gate B NOT_PASSED; C/D/E HOLD; Phase01 BLOCKED; NOT_DEPLOYED / GATES_HOLD.
