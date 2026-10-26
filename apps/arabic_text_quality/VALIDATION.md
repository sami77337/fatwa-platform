# FAST7C Arabic quality validation

Base: FAST6 PR #121, `667fd70217d794169c23569ce2df0396dcd27f7c`.
Isolated branch: `codex/20261026-fast7c-arabic-quality-pc1`.
Environment: Windows, Python 3.13.15, Unicode database 15.1.0.
Only new files under apps/, tools/, tests/arabic_text_quality are included.

## Executed checks

| Command | Result |
| --- | --- |
| `python -B -m unittest discover -s tests/arabic_text_quality` | 51 passed |
| `python -B -m unittest discover -s tests/revision_core` | 37 passed |
| `python -B -m unittest discover -s tests/fatwa_drafts` | 38 passed |
| `python -m ruff check --no-force-exclude apps/arabic_text_quality tools/arabic_text_quality tests/arabic_text_quality` | passed |
| `python -m ruff format --check --no-force-exclude apps/arabic_text_quality tools/arabic_text_quality tests/arabic_text_quality` | passed |
| `python -m mypy --explicit-package-bases --follow-imports=silent apps/arabic_text_quality tools/arabic_text_quality` | passed, 5 source files |

126 tests passed without skips. The new tests cover exact Unicode source/hash
preservation, astral offsets and CRLF coordinates, controls, isolate/PDF boundaries,
paragraph scope, normalization ordering/Hangul/Arabic compatibility forms, paired
whitespace and line-ending changes, immutable revisions and authoritative comparator
reuse, strict synthetic guards, bounded input, UTF-8 errors, CLI bytes and exit codes.
A fresh subprocess proves service invocation without Django, database libraries,
editorial UI, filesystem calls, or sockets.

One focused independent final review covered the full service, CLI, contracts and
tests, including the final isolate-index implementation and canonical LF output.
No unresolved blocking findings. During development, checks exposed and corrected
JSON tuple/list consistency and falsey prior-revision validation. A normalization
test expectation was corrected to the documented minimal differing enclosure.
The initial mypy invocation needed `--explicit-package-bases` for this repository's
namespace packages; remaining annotation errors were fixed. Initial Ruff formatting
was fixed. These failed intermediate checks are not counted as successful runs.

## Fabricated input identities

Committed LF is pinned by `tools/arabic_text_quality/.gitattributes`.

| File under tools/arabic_text_quality/fixtures | SHA-256 of exact UTF-8 bytes |
| --- | --- |
| `question.txt` | `c404e1516245241183bed451b59dc5b813c6ed56f53b9b0acd3254c18683e206` |
| `revision.txt` | `4bdeae2ff8fff21127bf3452afdc9f5a6e4f3824e6bc85fec651b1a395f3f54c` |

```powershell
python -B -m tools.arabic_text_quality --synthetic-only --before tools/arabic_text_quality/fixtures/question.txt --input tools/arabic_text_quality/fixtures/revision.txt --kind revision
```

Exit 0; four diagnostics; ASCII JSON plus one LF: 2,387 bytes, SHA-256
`085561d066b9391805b61f33ea83615092cad9c1e37ec0702a55756f1277d795`.
This identity assumes the stated Unicode database. No owner ZIPs or private case data
were read. This is synthetic acceptance evidence only.

No migrations, dependency changes, settings, routes, existing modules or shared
workflows changed. Django/PostgreSQL/browser acceptance is NOT_RUN for this pure
offline change; no result for those systems is inferred. Existing comparison can
perform quadratic work on repetitive text within its 10,000-code-point bound.
Normalization findings use exact contiguous enclosures, not grapheme segmentation.
The synthetic flag is caller attestation, not automatic data classification.

NOT_DEPLOYED / GATES_HOLD. Gate B NOT_PASSED; C/D/E HOLD; Phase01 BLOCKED;
U03/U10 OWNER_APPROVAL_PENDING. No grants, approvals, publication, production work,
main merge or changes to other FAST7/FAST7B modules.
