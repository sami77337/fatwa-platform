# Independent related-material side panel — original point 492

This development unit implements the separate side panel described by
SPEC-U02-020. It uses actual currently authorized canonical search results while
the answer editor remains mounted beside it. The new credit is the functioning
side panel. Earlier composer draft preservation, the existing search indexes,
and the mere presence of source links are inherited capabilities.

## Native contract

`FATWA_ANSWER_RELATED_ENABLED` is literal-True opt-in and defaults to False.
Answer media and canonical search must also be enabled; the explicit current
SearchAuthority and versioned scoped identity remain independently required.
No source policy, publishing permission, or scholarly approval is inferred.

The actual `/casework/staff/` campaign dispatcher accepts:

- `answer_media_related_search`: query, explicit FTS/LITERAL/FUZZY mode, and
  current case or current authorized case scope;
- `answer_media_related_open`: exact signed generation/document/source case;
- `answer_media_related_back`: rerun the previous selection under current rights.

All commands use strict POST schemas and CSRF. Signed state binds the current
authenticated session, identity epoch, editor case, case revision and evidence
version. Each source open revalidates the exact source/index version. A newer
answer, stale index, withdrawn source, changed identity or changed authority
rejects the old panel. Permission and source callbacks finish before the final
pure editor checks, while the outer transaction remains open through rendering.

The same-origin module `/casework/staff/answer-media/related.mjs` replaces only
the separate marked `aside`. It never serializes the answer textarea, chosen
file, or authored YouTube fields. Search and preview neither save an answer nor
insert a source. On denied refresh it clears prior source text while preserving
the author controls. Buttons start disabled when JavaScript cannot run.
The successful marked HTML opts into only `script-src 'self'` and
`connect-src 'self'`; there is no inline script, eval, external request or embed.

Sources are the canonical source kinds already supported and currently usable:
question, ordinary follow-up, evidence-bound answer and independently authorized
transcript text. The panel exposes source type/version and original text. A
recording segment, when present, opens its independently guarded original route
in a separate tab. Results remain reference material, not an attributed ruling
or a claim of scholarly similarity. No absent book/hadith/lesson corpus is
invented; U10 remains deferred. A missing/stale index requires the existing
explicit rebuild in the search tab. Twenty displayed results are bounded and
the user is asked to narrow the query when more matches exist.

## Evidence and recovery

`apps.answer_media.test_related.RelatedMaterialHTTPTests` has seven actual
campaign HTTP tests: search/open/back and unchanged canonical answer; explicit
literal/fuzzy and scoped isolation; CSRF and copied-session/case/input rejection;
stale editor/source pins; real late edit rollback through rendering; late
identity/feature revocation; and default-off/script method boundaries.

These seven plus the two existing native YouTube regressions passed on
PostgreSQL 17 (9 tests, 2.417 seconds) and PostgreSQL 18 (9 tests, 2.570 seconds).
These are service/native HTTP results, not browser acceptance.

Protected browser class:
`apps.answer_media.browser_related.RelatedMaterialBrowserTests`.
Its actual native journey searches, opens and returns while checking the same
textarea/file DOM nodes, exact draft/link values and the selected file SHA-256;
then withdraws search access, verifies old source text disappears, and explicitly
saves the exact three answer parts once. It checks separate desktop columns and
320/1280 widths. Receipt:
`.local/qa/functional-continuation/answer-related-browser/result.json`, with
screenshots and `trace.zip`. Browser PASS requires actual hosted execution with
Chromium sandbox retained; local launch remains blocked by the known container
OS restriction and is not claimed as a pass.

No new table, trigger, function, media copy, or durable panel state is created.
Canonical source/index recovery and answer-media recovery remain responsible
for their existing records. This unit adds no recovery owner or corpus data.
Production remains disabled; the existing project acceptance gates are unchanged.
