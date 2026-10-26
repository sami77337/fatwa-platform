# Source-preserving Arabic text quality

Pure, read-only diagnostics for **fabricated development questions and revisions**.
These findings do not establish editorial intent, scholarly correctness, permissions,
approval, or eligibility for publication. **NOT_DEPLOYED / GATES_HOLD**. Gate B remains
NOT_PASSED; Gates C/D/E HOLD; Phase01 BLOCKED; U03/U10 owner acceptance remains pending.

```python
from apps.arabic_text_quality import inspect_text, compare_texts, inspect_revision

report = inspect_text("سؤال تجريبي\u202e", synthetic_only=True)
comparison = compare_texts("سؤال\r\nتجريبي", "سؤال\nتجريبي", synthetic_only=True)
print(report.to_json())
# inspect_revision(revision, previous=older_revision, synthetic_only=True)
```

`synthetic_only` must be the literal `True`; it is a caller assertion, not a private-data
classifier. APIs accept `kind="question"` or `kind="revision"`. The revision adapter
uses the authoritative `Revision` model and `revision_core.compare_revisions` validator
and lossless comparison. It inspects `title`, `answer` and `reviewer_notes`; it does not
inspect metadata, modify references, change workflow state, or grant anything. Text
comparison also reuses that service through immutable synthetic snapshots. Search
normalization is intentionally unsuitable for preserving source and is never invoked.

Each input is limited to the existing revision-core maximum of **10,000 Unicode code
points**. Invalid Unicode surrogates and non-string values are rejected before inspection.
The existing exact comparison uses `SequenceMatcher(autojunk=False)` and can take
quadratic work on repetitive text; this tool does not promise linear comparison time.
Single-text inspection performs linear scans plus sorting of findings. No database,
Django configuration, source archive, network call, persistence or migration is needed.

## Report contract

Reports and their nested records are frozen. `to_dict()` produces fresh JSON-compatible
containers; `to_json()` is deterministically sorted ASCII JSON without timestamps, paths,
random IDs, or platform line-ending conversion. Escaping preserves invisible characters
and avoids emitting active terminal controls or bidi controls. Original source strings
and their exact UTF-8 SHA-256 digests remain in `sources`. No rewritten or normalized text
is returned in their place. Consumers must still escape decoded text for their own UI.
`unicode_version` records Python's actual Unicode database version; determinism is for
identical inputs and that version, not an assertion that all Python versions agree.

Every diagnostic includes `code`, `severity`, a stable English explanation, `location`,
and optionally `related_location`. Locations contain zero-based, half-open **code-point**
`start`/`end`, one-based `line`/`column` and end coordinates, exact `original`, and `U+XXXX`
`codepoints` (longer for astral characters). They are logical positions, not UTF-8 bytes,
UTF-16 units, graphemes, or visually reordered columns. CRLF is one line boundary; the LF
itself has the next code-point column on the preceding line. CR, LF, NEL, LS and PS also
start new logical lines. Tabs count as one column. Empty edit spans identify an exact
insertion/deletion boundary and have empty original/codepoints.

Single text uses side `source`; comparison uses `before` and `after`. The revision
adapter adds `.title`, `.answer`, or `.reviewer_notes` to the side. Paired edit findings
use the before span as `location` and after span as `related_location`. Diagnostic order
is source order, starting offset, ending offset and stable code, with related start as
the final tie-breaker. No severity implies that a source may be automatically changed.

## Findings and limitations

- Control (`Cc`) and invisible format (`Cf`) characters are flagged conservatively;
  CR/LF/tab/NEL have dedicated whitespace or line-ending treatment. ZWJ/ZWNJ are `info`
  because they can be intentional Arabic shaping or emoji composition.
- Explicit bidi controls are visible as findings. Overrides are warnings; unmatched
  PDF/PDI and scopes left open at paragraph boundaries/end are errors. Structural scopes
  reset on Unicode bidi class B. PDF cannot close an isolate; PDI closes its isolate and
  any nested embedding. This is a structural diagnostic, **not a full UAX #9 renderer**:
  it does not resolve visual order or implement the algorithm's directional level limits.
- Mixed line-ending styles, lone CR/NEL/LS/PS, leading/trailing/repeated whitespace,
  and nonordinary whitespace are reported with exact spans. Normal CRLF or LF on its own
  is accepted. Comparison reports changed whitespace and line boundaries even when the
  edit also includes substantive characters. These are potential unintended changes,
  not an assertion of intent. Ambiguous repeated text follows the existing comparison's
  deterministic edit alignment.
- NFC/NFKC differences are computed on the **complete source**, so combining-mark
  reordering and Hangul composition are retained. Each form reports the smallest
  contiguous original enclosure after trimming common prefix and suffix; the enclosure
  can include unchanged characters between disjoint differences. It is not a per-grapheme
  explanation. Canonically or compatibility-equivalent revisions additionally receive
  `normalization_only_change`. Compatibility equivalence is never a claim of meaning
  equivalence, and neither normalization is applied to source text.

Unicode references: [UAX #9](https://www.unicode.org/reports/tr9/) and
[UAX #15](https://www.unicode.org/reports/tr15/). The Python runtime database governs
character classification and normalization used in each report.
