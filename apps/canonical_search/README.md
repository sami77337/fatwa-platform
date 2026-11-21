# Canonical Arabic text retrieval — development only

This opt-in unit adds actual PostgreSQL full-text and trigram retrieval to the
existing canonical case records. It does not replace the older title/substring
search, change any source text, publish a case, approve an answer, or grant source
rights. `NOT_DEPLOYED / GATES_HOLD`; originals and the 556-point inventory are
unchanged. Owner acceptance remains independent of implementation evidence.

## Delivered behavior

An authenticated, currently scoped Mufti opens a case, explicitly builds a derived
generation, and chooses one of three search modes. `LITERAL` searches the unchanged
source string. `FTS` runs PostgreSQL `@@`, `plainto_tsquery('simple', ...)` and
`ts_rank_cd` against persisted `tsvector` rows. `FUZZY` is an explicit separate path
using `pg_trgm` word-similarity operators and SQL ranking. GIN indexes cover both
the vector and `gin_trgm_ops` text. Search opens the exact original version after
checking the source and rights again.

The index includes original questions, ordinary requester follow-ups, the latest
answer only while bound to current evidence, and actually available transcript
segments. A transcript's question copied into `CaseEvidence` is **excluded** from
ordinary follow-up indexing. Its independent DISCOVER, SEARCH_TEXT, READ_TEXT,
KnowledgeAuthority and enforced source-ledger predicates remain mandatory.
Missing or unversioned optional transcript policies exclude transcript text.

The separate `RECORDING_TRANSCRIPT` adapter consumes independently reviewed
`public_answer_media` revisions bound to an actual canonical AUDIO answer part.
Each hit retains the transcript digest/version, exact audio-part ID/hash and
reviewed segment text hash/time interval. Its native link opens that exact segment
through the current-authorized recording reader. A portable `TranscriptLink` is
never relabeled as a recording. A new recording-text version has no inherited
review and requires an explicit index rebuild before becoming searchable.

Current author/reviewer scope, independent recording/media grants and expiry,
actual original bytes, source rows and settings are checked through rendering.
A preexisting denial, withdrawal, missing file or unusable optional recording
policy omits its recording rows while keeping independently allowed question and
answer results. A change during the combined projection rejects the whole response.
All consumed file reads finish before the final pure multi-case snapshot checks.

Rebuilds append complete immutable generations. Canonical changes make the old
generation stale; a signed native command rebuilds it explicitly. Repeated equal
requests reuse the same generation, including a concurrent exact replay. Sources
and approvals remain canonical in their existing apps. The final renderer runs
inside the same authorization/transaction boundary as the response.

## Development limits

- At most 32 explicitly scoped cases, 512 eligible text documents per case,
  128 immutable generations per case, 120 query characters/eight terms,
  and 160 returned matches in pages of 20. Capacity failures are explicit.
- Fuzzy terms need at least three characters. The development threshold is 0.35;
  it is installed with SET LOCAL for that query and the previous setting is
  restored. Runtime statement/lock timeouts are unchanged.
- Profile `ar-simple-trigram-dev-v1` uses NFKC, case folding, removal of combining
  marks/tatweel, the explicit alef variants and alif-maqsura mapping, and whitespace
  collapse on derived copies. Original strings remain byte-preserved.
- `simple` tokenization does **not** claim Arabic morphological stemming or
  segmentation of attached conjunctions/articles. No approved synonym dictionary,
  semantic search, scientific-quality score, final ranking weights, final
  normalization policy, or reviewed gold benchmark is claimed.
- Existing `TranscriptLink` bundles supply text/time pins but do not themselves
  prove a recording binding. Those results make no playback claim.

## Original requirement accounting

| Original point | New behavior and scope |
| --- | --- |
| 219 — Full-Text Arabic Search | Real PostgreSQL retrieval of existing authorized Arabic text on a versioned derived copy. Full linguistic/gold-quality acceptance remains open under U05-027. |
| 220 — Fuzzy Search and spelling errors | Explicit pg_trgm path, separate from literal matching; development threshold remains subject to evaluation. |
| 449 — PostgreSQL FTS and pg_trgm in the baseline | Real migration, operators, persisted vector and GIN indexes; no production capacity or latency claim. |

Related originals/specifications: SPEC-U05-006/007/027, SPEC-U16-005,
D-014/D-018/D-039/D-044/D-045. These three points describe one functional search
unit, not three independent delivered products. Existing substring search is not
counted again. Original **234** (SPEC-U05-015) is a separate composition: a matching
reviewed recording transcript opens its actual pinned audio timestamp. It has
service and native HTTP tests plus its own protected-browser journey and receipt;
browser acceptance remains pending until that real journey passes on the exact
integrated head. It is not credited by the older portable transcript timestamps.

## Integration and verification

See `CONTRACT.md` for default-off settings and dispatch. The combined **30-test**
gate passed on real PostgreSQL 17 (10.236 s) and 18 (10.439 s), with actual
`config.campaign_urls` shared dispatch and the native case tab:

| Module | Tests | Meaning |
| --- | ---: | --- |
| `apps.canonical_search.tests` | 18 | Real SQL, GIN eligibility, exact source opening, concurrent idempotence, stale generations, SQL provenance and late policy changes |
| `apps.canonical_search.test_http` | 6 | Real login/CSRF/forms, browser-bound selections, original text and transactional final render |
| `apps.canonical_search.test_rights` | 5 | Independent strict ledger READ, revocation/expiry and final typed-gate checks |
| `apps.canonical_search.test_recovery` | 1 | Nonempty real-service recovery adapter and actual missing-authority/inactive-identity denials |

`apps.canonical_search.test_recordings` adds 13 focused recording-composition tests:
real segment source/time pins, independent/static denial, missing original bytes,
new-version review isolation and stale index, SQL rejection of forged timing,
late cross-policy/identity revocation, final filesystem callback revocation,
actual campaign search→segment→audio HTTP, and rollback of a render-time withdrawal.
The combined **43/43 tests passed** on PostgreSQL 17 (19.007 s) and 18 (19.326 s)
through `config.campaign_urls`, including all earlier 30 regressions. Logs are
`.local/qa/search-recording-final-pg17.log` and `search-recording-final-pg18.log`.

Logs: `.local/qa/search-final-pg17.log` and `search-final-pg18.log`. The protected
browser test is
`apps.canonical_search.browser_tests.CanonicalSearchBrowserTests`; its success-only
receipt is `.local/qa/functional-continuation/canonical-search-browser/result.json`,
with 320/1280 screenshots and a trace. The actual local Chromium attempt was
blocked before any page by `socket() failed: Operation not permitted` and a ptrace
denial. Sandbox remained enabled; there is **no local browser PASS**. Hosted
protected-browser and integrated fresh-process encrypted-restore evidence remain
separate required gates.

The additional protected class is
`apps.canonical_search.browser_recordings.RecordingSearchBrowserTests`, with a
separate success-only receipt at
`.local/qa/functional-continuation/search-recording-browser/result.json`.
It builds/searches through native forms, activates the actual result link, checks
the real player's start time and keyboard playback without modifying its clock,
compares the delivered original bytes, and proves current revocation blocks both
the segment and audio endpoints. It retains 320/1280 screenshots and `trace.zip`.
No local browser pass is claimed for either journey.

The index-eligibility test explicitly disables sequential scans only in its own
EXPLAIN transaction. Runtime search does not force planner choices. Executed SQL
and index eligibility are evidence of implementation, not a performance benchmark.

Implementation references: [Django 5.2 PostgreSQL search](https://docs.djangoproject.com/en/5.2/ref/contrib/postgres/search/)
and [PostgreSQL 18 pg_trgm](https://www.postgresql.org/docs/18/pgtrgm.html).

## Exact source passage navigation

The additive owner-233 implementation opens ordinary results at exact original
character ranges, with signed query/mode/position and native previous/next forms.
Every movement rechecks current OPEN/SEARCH and source rights without rewriting
source text. See `MATCH_NAVIGATION.md` for exactness limits, the new protected
browser identity, six-denial fresh-process helper and pending hosted evidence.
