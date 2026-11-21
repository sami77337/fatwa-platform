# Opening the exact matching source passage

Original owner point **233** says the reader can move to the matching passage in
the question or answer. `SPEC-U05-014` also requires retaining the source version
and location and forbids claiming an unavailable location. This additive change
implements the missing question/answer passage projection in the existing
canonical search. It does not claim the whole wider specification complete.

## Native behavior

The ordinary canonical-search result now signs its exact case, generation,
document, query, matching mode and initial position. Opening it renders the
currently allowed original with escaped `<mark>` elements around matching
passages. The first passage and the native previous/next forms use the static
`#canonical-active-match` fragment. Each movement is an authenticated CSRF-checked
POST through the existing `/casework/staff/` dispatcher; there is no private GET
URL, added JavaScript, client-computed source offset, or shared route change.

Every movement rechecks **both OPEN and SEARCH**, current identity and case scope,
current source rights, current source/index versions and membership of the exact
document in the actual selected PostgreSQL query. Existing final-render checks
reject a source or authority change before any highlighted response is returned.
The signed state is bound to the existing browser session, provider, principal,
authorization epoch and case and expires after the existing 15-minute limit.

The original text and all stored rows are unchanged. Character ranges and markup
are transient projections. Joining the displayed text fragments yields the exact
original string, including Arabic diacritics, tatweel, whitespace and CRLF; HTML
parsing's normal CRLF-to-LF conversion does not alter the response or stored bytes.
Source content is escaped by Django, including apparent HTML/script fragments.

## Exactness and limits

- **Literal:** highlight actual original substring occurrences, preserving case
  and diacritic distinctions.
- **FTS:** highlight whole normalized query-token occurrences mapped back to
  their original character clusters. The existing normalization profile remains
  unchanged. Combining marks and compatibility/casefold expansions retain their
  original ranges; the mapped whole string must equal that profile before any
  range is used.
- **Fuzzy:** an approximate result is explicitly labeled. Only any exact
  normalized query-token occurrences are highlighted. A typo-only similarity
  result opens its full documented source without inventing a literal range.
- If a rare Unicode composition cannot be mapped exactly, the page says no safe
  exact passage is available and retains the full original and its version/hash.
- Existing query limits remain 120 characters and eight distinct terms, with
  source text bounded by the existing 16,000-character contract. At most 200
  passages are navigable per opening; additional matches produce an explicit
  request to narrow the phrase. Invalid, boolean or out-of-range positions fail.

Offsets are Unicode character positions in Python source strings, not byte
offsets or browser UTF-16 offsets. They are used only by server slicing. The
client never treats a numeric offset as authorization or as a writable citation.

Existing dictionary/shadow result tokens keep their prior exact-source opening
contract. This change does not infer a dictionary expansion's matching phrase or
expand the current task into semantic search, classification filters, FT lookup,
publication, or final visual design.

## Integration contract

No settings, routes, migrations, persistent tables, source-byte owners or new
authority actions are required. `cs_source` remains the only opening action and
accepts the original source-state shape or the newly signed matching-state shape.

Service:

```python
matches.open_match(
    **base,
    generation_id=...,
    document_id=...,
    value=...,
    mode="FTS",
    index=0,
)
```

The response retains the ordinary exact source projection and adds `navigation`
with original ranges, escaped-template fragments and bounded previous/next state.
`matches.open_in_context` composes the same operation under an existing search
boundary; callers must keep rendering inside that boundary.

### Required tests and exact evidence identities

Service/native labels:

- `apps.canonical_search.test_matches`
- `apps.canonical_search.test_match_http`
- `apps.canonical_search.test_match_recovery`

The existing canonical search, HTTP, source-rights, recording and governance
regressions remain required. The source-rights suite additionally withdraws an
independently reviewed transcript READ grant after a valid passage open.

Protected browser identity:

`apps.canonical_search.browser_matches.SearchMatchBrowserTests.test_native_exact_question_answer_matches_previous_next_and_current_denials`

Success-only proof:
`.local/qa/functional-continuation/search-match-browser/result.json`, with
320/1280 screenshots and `trace.zip`. Required flags are
`exact_question_match`, `exact_answer_match`, `native_previous_and_next`,
`native_fragment_navigation`, `original_text_bytes_preserved`,
`html_source_escaped`, `stale_source_denied`, `current_access_revocation` and
`no_navigation_writes`. It measures native fragment visibility **before** any
screenshot scrolling. `page_errors` and `external_requests` must both be zero.
The browser remains sandboxed. The module imports existing test modules as module
aliases, so their TestCase classes are not accidentally rediscovered as new tests.

Fresh-process helper: `apps.canonical_search.match_recovery_support`, exposing
`populate()` and `verify_restored(pins)`. It adds **zero tables** and uses existing
casework/canonical-search owners. It seeds actual question and answer originals,
then reopens first/next/last/previous positions after restoration and proves all
source/index/event snapshots unchanged. It performs exactly six denials:
`disabled_search`, `missing_authority`, `missing_identity`, `revoked_open`,
`revoked_search`, `revoked_case_scope`, followed by positive reads under restored
explicit fixture authority. Persisted source rows never constitute current grants.

The aggregate coordinator must add this exact browser identity and helper to its
explicit registries. Local service/native/helper passes are not a hosted browser
or encrypted-restoration receipt, and do not alter release gates or owner policy
acceptance.

## Local execution retained

The 78 selected service, HTTP, source-rights, recording, governance and recovery
helper tests passed against fresh owned PostgreSQL 17.11 and 18.7 clusters
(66.797 s and 68.520 s respectively). Logs retained by the coordinator are
`search-match-final-pg17.log` and `search-match-final2-pg18.log`. PostgreSQL 18
requires its extracted runtime library directory in `LD_LIBRARY_PATH`; an earlier
launch without it failed before tests because `liburing.so.2` was unavailable.

The local protected browser attempt failed before opening any page: Chromium
reported `socket() failed: Operation not permitted`, followed by ptrace denial.
The browser sandbox was kept enabled. `search-match-browser-pg17.log` retains
that blocked attempt. A hosted protected run on the final integrated commit is
still required; no local browser success is claimed.
