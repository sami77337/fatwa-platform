# V14 focused evidence and boundaries

Date: 2026-11-18. Base: PR #232,
`1f08cbb7166f70ec340c495da33ccfc1eda9534e`. Branch:
`codex/20261118-v14-pdf-citations`. Only `apps/pdf_citations/**` and
`apps/timed_citations/**` changed. No shared integration or CI changes.

Environment: Python 3.13.5, Django 5.2.18, pypdf 7.1.0. PostgreSQL 17.12
(Debian 17.12-0+deb13u1) and PostgreSQL 18.7 used fresh owned loopback clusters
through `infra/dev/with_casework_postgres.py --settings apps.pdf_citations.settings`.
Fixtures are generated blank three-page/two-page PDFs, the existing generated
0.1-second WAV, synthetic cases/identities and explicit short-lived exact grants.
No real manuscript, quoted text, printed-page evidence, requester data or keys
were used. Printed-label tests exercise a synthetic human assertion contract,
not verification of any real publication.

## Passing evidence

**19 distinct focused non-browser tests have passing evidence on each major**
across the following batches; this is not a claim of a single 19-test run:

| Check | PG17 | PG18 |
|---|---|---|
| First 11 PDF tests + 2 audio-context tests + affected existing timed HTTP test | 14/14 PASS, 13.525s | Included in 17/17 PASS, 16.052s |
| Added concurrent PDF correction, final-byte expiry, SQL rollback/reapply | 3/3 PASS in browser batch (PDF browser separately failed there) | Included in 17/17 PASS |
| Persisted-row/app-disabled/restored-schema guard and recorded approver epoch | 1/1 PASS in PDF-browser diagnostic batch (browser separately failed) | 1/1 PASS, 1.446s |
| Current-answer guard added: affected exact-page and correction tests | 2/2 PASS with final PDF browser; batch 3/3, 9.096s | 3/3 PASS including approval adapter, 3.747s |
| Separate READ_MEDIA/CITE expiry and earliest deadline | 1/1 PASS, 0.832s | 1/1 PASS, 1.000s |
| `makemigrations pdf_citations timed_citations --check --dry-run` | No changes | No changes |
| Django system check / fresh migrations | PASS | PASS |

Focused labels are `apps.pdf_citations.tests` (16),
`apps.timed_citations.test_preview_context` (2), and
`apps.timed_citations.tests.TimedTests.test_native_http_csrf_scope_player_and_private_bytes`
(1). Commands are documented in README; affected follow-ups selected only the
new/changed methods. Unaffected historical suites were not rerun.

Covered: verified physical bounds, boolean/nonfinite/noninteger rejection,
forged source version/hash/count, explicit printed mapping, confirmed/proposed
separation, exact old-file selection with no implicit move, stale-answer denial,
append-only lineage/actions, one concurrent successor, cross-case database
binding, scoped identities/epoch changes during reads, READ_MEDIA vs CITE,
missing policy/parser proof/configuration, expiry during composition and at byte
return, revoked permission in a later authority callback, redaction of source,
printed label and predecessor notes, withdrawal after approval without deletion,
CSRF/signed pins, anonymous/forwarded/nonloopback/query denial, HEAD recheck,
private/no-store/sandbox original bytes. The approval adapter is exercised
explicitly; canonical automatic call-site wiring remains for integration.

Ruff check, Ruff format check and `git diff --check`: PASS over both owned apps.

## Browser evidence and retained failures

Chromium **154.0.8037.57**, 360px RTL, actual loopback server + PostgreSQL17:

- Audio context journey: PASS in the initial local browser batch. It selects
  one second of context, observes native duration 0.1s and fragment `#t=0,0.1`,
  confirms and opens identical authorized bytes, withdraws to 404, and checks
  that the stored 10–90ms locator did not change. Keyboard focus, no horizontal
  overflow, no page errors and no external requests were asserted.
- PDF journey: PASS in final 3/3 batch with the two affected service tests. Native
  form proposal → review document → **keyboard confirmation** → authorized
  original → withdrawal404. Physical locator2/3 and empty printed label retained.
  GET bytes equal the generated original, server headers retain sandbox/no-store,
  RTL/keyboard/no horizontal overflow and absence of external HTTP(S)/WebSocket
  requests/page errors are asserted. Chrome's built-in PDF extension resources
  are local browser resources, not counted as external network traffic.
- These functional runs explicitly used `FATWA_TEST_BROWSER_NO_SANDBOX=1` plus
  temporary XDG cache/config paths. **They are not protected Chrome acceptance.**
  The default protected browser attempt failed before either journey because
  this environment's SUID sandbox helper is not configured (both launch errors,
  with an accompanying crashpad configuration error). Protected execution is
  still required on the combined branch. No host sandbox, application CSP,
  permission check or Django async-safety guard was relaxed.

Other historical local harness failures are retained here: the first PDF browser
assertion expected sandbox in Playwright's PDF-navigation response, which exposed
only `frame-ancestors 'self'`. An independent authenticated byte request and the
native HTTP test both showed the actual server header
`sandbox; default-src 'none'; frame-ancestors 'self'`. The harness now asserts
server headers on that byte request, without changing the response policy.
Two diagnostic runs timed out waiting for the next button after pointer-based
confirmation; another timed out awaiting navigation. The final test exercises
native keyboard confirmation explicitly. One later run completed the journey
but incorrectly treated built-in `chrome-extension://`/internal resources as
external requests; its assertion now checks actual network schemes. A proposed
string-based diagnostic edit did not match the formatted source, so one of the
pointer failures was repeated before the explicit patch landed.

Neither loading `#page=2` nor successful original-byte delivery proves that
Chrome's PDF engine visually rendered page2. The test deliberately reports
`plugin-rendering=NOT_ASSERTED`. Native PDF rendering, printed-label correctness
and pointer focus around the embedded viewer require independent visual/protected
browser review; a private original link remains available. Previously delivered
V13 evidence is preserved in `apps/timed_citations/README.md`.

## Remaining integration work

Follow CONTRACT.md before enabling: register migrations/default-closed flag,
connect staff actions and exact private routes, then call
`integration.require_for_answer` at canonical approval **and every downstream
use**, accumulating its expiry to the final use boundary. Retained annotations
must not disappear when the app/flag is removed after restore. Verify recovery
of both new tables and the complete synthetic journey. These shared areas were
not edited under exclusive ownership; no approval/use integration pass is
claimed by this branch. Source rights adapters must supply explicit exact media
grants and current deadlines; none are invented here.

Gate B NOT_PASSED; C/D/E HOLD; Phase01 BLOCKED; NOT_DEPLOYED. No main merge,
production/real-data operation, external send, unapproved U03, automatic fatwa
approval, GitHub setting change, completion estimate or formal acceptance.
