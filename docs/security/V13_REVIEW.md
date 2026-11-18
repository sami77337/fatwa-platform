# V13 external security review — BLOCKED on 38cd137

## Actual V13 product review (2026-11-18)

**BLOCKED** on `38cd137db50cc95ae53fa275b5d90b8274096e5d`, compared with
`5ec6373f5eaf3cd5ea2b14d7b3e7119826ceb4c8`. Both the remote integration branch
`codex/20261118-v13-integration` and Draft PR #232 head were checked and matched
that SHA before and after the focused executions. The older P0-B PASS below
reviewed V12's delta only; it is not clearance for this actual V13 delta.

**SEC13-01: recovery schema normalization equates different quoted data values.**
Reproduced with actual PostgreSQL17.12/18.7 pg_dump and with encrypted restoration
to newly created synthetic targets on both majors. The affected recovery path
must remain blocked until repair and independent verification. No product code
was edited by this reviewer. Other passing checks below do not close this finding.

### Reproduction and impact

`apps/platform_recovery/service.py:canonical_schema` applies its literal-array
regular expression to an entire partial-index line, including SQL quoted data.
It therefore rewrites the contents of a string constant as if it were an array
expression. These real PostgreSQL partial unique indexes have different behavior
but receive **the same canonical schema fingerprint**:

```sql
CREATE UNIQUE INDEX v13_review_literal_index
ON public.v13_review_literals(marker)
WHERE marker <> '(ARRAY[''::character varying])::text[]'::text;

CREATE UNIQUE INDEX v13_review_literal_index
ON public.v13_review_literals(marker)
WHERE marker <> 'ARRAY[(''::character varying)::text]'::text;
```

The two values are synthetic text, not executable expressions. The first index
allows two rows containing `(ARRAY['::character varying])::text[]`; the second
rejects those duplicates with IntegrityError. The independent regression verifies
that difference, dumps the real complete schema after each index definition, and
requires distinct fingerprints. It **fails on both majors**. Within PG17 both
fingerprints are `652720ede8f4c266a7388de618418f25c695569c84443016cf429352e8cd4805`;
within PG18 both are `f93ca1ea99860b209b7ed4d865a3beef5cbef19a5303873739a66c8cfe1b7909`.

A second independent test creates the first index on an empty synthetic table,
then uses the existing real encrypted/FROZEN recovery drill. At its supported
`schema_restored` fault-injection checkpoint, it changes only the target index to
the second definition. The target alteration is asserted to execute exactly once.
The unchanged positive drill returns **READY**, verifies restored private bytes
and leaves the source FROZEN. The review requires `restored_schema_mismatch` and
therefore **fails with `RecoveryError not raised` on both majors**. The altered
target was accepted rather than quarantined.

This proves a post-restore schema integrity verification gap. It does not claim
an encryption/signature bypass, unauthenticated remote SQL access, or a currently
deployed index with these values. The fault model is a changed restored target,
the same fault model already exercised by the integration schema-tamper test.
Unlike a change to UNIQUE/name/column, this semantic predicate change collapses
under the new partial-index normalization. CHECK-line handling shares the broad
regex pattern and should be inspected during repair; this reproduction specifically
tests the V13 partial-index extension.

Required repair: recognize SQL token/quoted-string boundaries so equivalence
normalization never edits data literals, identifiers or quoted function bodies.
Preserve all predicate values/order/uniqueness/names and the existing deparser
equivalence needed for valid restores. Do not omit schema checks or allow the
tamper test to pass by accepting READY. Rerun these two failing methods and the
affected positive restore/equivalence cases on both majors at the repaired head.

### Other review findings and evidence limits

- Timed citations: source/version/hash/metadata and duration bounds, explicit human
  confirmation, stale Evidence, staff private bytes and composite preparation
  denial are exercised independently. Expiry after a real confirmation INSERT
  rolls back the action while retaining the proposal. Reviewed canonical approval,
  release, publication and delivery hooks; no replacement queue or implicit grant.
- Classification: independent approval remains mandatory even when action authority
  permits the proposer. Expiry after an approval INSERT rolls it back. After source
  revocation the normal desk denies, audit omits label/reason/source/decision text,
  human withdrawal still works and canonical publication category is unchanged.
- Search: strict source rights enclose ranking and source opens. Independently
  advanced clock during ranking denies both a matching and a no-match response.
  Result contract stays `BOUNDED_CANDIDATE_WINDOW`, limit20, `TOC_METADATA_ONLY`,
  human review `PENDING`. This is not semantic search or complete corpus search.
  The recorded four-title/558-SQL sample in the app contract is retained as an
  existing cost observation, not a fresh benchmark or acceptable scale claim.
- Maintenance: all three new app service entrypoints tested reject FROZEN before
  reaching product authority/source code. Strict runtime settings and inherited
  admission remain in force; privileged SQL is outside that application perimeter.
- Internal fixes: read the complementary review and its original failure history;
  independently reran its five final-callback/identity/deadline probes on this exact
  head. All pass on both majors. Those are reused review regressions, distinguished
  from the newly authored tests in this lane.
- Recorder: static inspection confirms no getUserMedia on initialization, native
  input assignment only on acceptance, no JS upload API, bounded PCM, epoch checks
  for late permission, and cleanup on cancel/pagehide/visibility/device failure.
  Independent CSP test passes: recorder HTML has same-origin script/worklet and
  blob preview only; no unsafe-inline/eval/remote-code grant; existing original-byte
  sandbox policy is preserved. Non-recorder responses receive no microphone opt-in
  from this helper; an absent Permissions-Policy is not asserted to deny microphone
  by itself.

The new real-browser lifecycle test was attempted with `FATWA_BROWSER_SANDBOX=1`
on both PG runs, but Chromium aborted **before page creation** because the installed
SUID sandbox helper is incorrectly configured. A separate user-namespace check
also failed (`/proc/self/uid_map` read-only). No sandbox or system permission was
changed. Thus no new independent runtime microphone/lifecycle pass is claimed.
The delivered browser test remains to run in a properly sandboxed environment.

### Focused execution on exact 38cd137

All data, audio, keys, databases and restored targets are synthetic and isolated.
The detached worktree `/tmp/v13-final-review` held exact product code; only the four
new reviewer-owned test modules were copied into it. Python3.13.16; PostgreSQL17.12
and18.7 as in previous review evidence. No complete unrelated suite was rerun.

| Checks per major across focused runs | PG17 | PG18 |
| --- | --- | --- |
| Six newly authored app methods | 6 PASS | 6 PASS |
| New CSP method | PASS | PASS |
| Five retained internal-repair regression methods | 5 PASS | 5 PASS |
| New real pg_dump predicate comparison | FAIL, 0.232s | FAIL, 0.264s |
| New encrypted target-tamper rejection | FAIL | FAIL |
| New recorder browser method | ENVIRONMENT ERROR before browser page | ENVIRONMENT ERROR before browser page |

The initial app batch was10 PASS/1 fixture ERROR per major (4.934s/4.953s): the new
search fixture lost its temporary rights-policy override on bootstrap exit. The
fix explicitly installs that same synthetic policy after setup; only its affected
method was rerun, and it passed in each subsequent browser-attempt batch. The
initial CSP probe expected a default Permissions-Policy header from a helper that
does not set one; it errored before assertions about the opt-in policy. It now
tests the actual helper contract and passes, with no production change. Initial
schema failure printed a very large synthetic schema; the strengthened test checks
hashes plus actual uniqueness behavior, preserving the same expected denial.
An initial target-tamper failure was repeated only to add the explicit checkpoint-
executed assertion. Final restore+CSP batches:1 FAIL/1 PASS, 1.028s/0.964s.

Durable logs under `tests/v13_security_review/evidence/final_v13/` retain the app
fixture error, browser startup failures, schema collision and final restoration
failure. `sha256.json` identifies these artifacts. No xfail/skip disguises a product
failure. New modules import only fixture helpers; they do not discover unrelated
legacy TestCase classes. Ruff and whitespace checks pass for owned files.

Authenticated GitHub lookup independently confirms exact-head
[run44223655150](https://github.com/sami77337/fatwa-platform/actions/runs/44223655150)
success, including jobs134531427683(PG17) and134531428802(PG18) and the protected
Chrome verification step. The91-test/full-journey counts are the integrator's CI
evidence, not local executions by this reviewer. Green CI did not cover the new
quoted-value collision and does not override this BLOCKED verdict.

### Integration handoff

Commit only this lane's new tests/evidence and report. The branch remains
`codex/20261118-v13-security`, with V12 and P0-B history intact. Product fixes and
workflow wiring belong to the integrator. Run explicit module labels from the
new target checkout after applying the review commit (the old review branch base
itself does not contain the V13 product apps):

```sh
V12_PG_BIN="$TEST_PG_BIN" python infra/dev/with_casework_postgres.py \
  --pg-bin "$TEST_PG_BIN" --major 17 --settings config.settings.campaign_review -- \
  python manage.py test tests.v13_security_review.test_final_schema \
  tests.v13_security_review.test_final_apps tests.v13_security_review.test_final_csp \
  --verbosity 2
# Repeat with --major 18 and its matching binaries.
# In a sandbox-capable environment, separately run test_final_browser with
# FATWA_BROWSER_SANDBOX=1 and FATWA_FASTBUILD_BROWSER pointing to Chrome/Chromium.
```

No main merge, production, external send, real data/key, GitHub setting change,
new percentage or acceptance. Gate B NOT_PASSED; C/D/E HOLD; Phase01 BLOCKED;
NOT_DEPLOYED. The recovery integrity blocker and independent browser environment
limit must remain explicit in the campaign handoff.

## Historical V13 P0-B independent delta review

Date: 2026-11-18. **PASS for the bounded delta** from
`5aff9ba3cce35241b3ded27ed3428e0d4ecad768` to
`5ec6373f5eaf3cd5ea2b14d7b3e7119826ceb4c8` (PR #231).
No concrete security blocker was found in the reviewed delta. This does **not**
approve later V13 implementation or close the entire V13 campaign.

Remote integration branch and `refs/pull/231/head` were independently verified
at the latter SHA before and after testing. Branch
`codex/20261118-v13-security` starts from that exact head, not main; the V12 review
branch remains intact. Owned changes are only this report and
`tests/v13_security_review/**`. No product repair, shared configuration, GitHub
setting, production operation or external message was performed.

Gate B NOT_PASSED; C/D/E HOLD; Phase01 BLOCKED; NOT_DEPLOYED. No revised percentage,
formal acceptance, U03 authorization, automated scholarly approval or real-content
rights is inferred. Earlier V12 failures and review evidence remain unchanged.

## Review scope and findings

Read AGENTS.md (no repository `.agents/skills` exists), the P1 integration scope,
Mufti journey and rights-inspection contracts, the preserved P0 review, and scope
matrix README/open items/P1 evidence limits. Reviewed the product/service/view
delta and the encrypted source/target browser harness and workflow changes. This
is not a new verification of every row of the 556-item scope source or its original
spreadsheet bytes.

| Changed boundary | Independent finding |
| --- | --- |
| `experimental_publication.library_catalog` and metadata search | The common collection still holds case locks, rechecks exact current source rights and staff scope, removes expired items before counts/facets/pages, and fails closed on expiry during filtering. Two-case tests cover early expiry, source-heading search, PAGE_SIZE=1, empty second page and lost scope during later projection. |
| `source_rights.registry.inspect_source` | Case scope, VIEW and same-case registration remain separate requirements. Giving an actor access to both cases and allowing VIEW does not make a source registered only in one inspectable from the other. Historical selection does not grant current uses or restore publication. Private transcript identity is reviewable without exposing its text or granting READ. |
| Native empty-file answer edit | An empty optional file field does not bypass evidence/revision validation. A form opened before a requester followup is rejected with409; no answer/event/revision is added and the formerly released audio remains inaccessible. |
| Server-derived publication/knowledge frame | Conflicting server frame identities and duplicate browser case references fail closed even when the actor has both cases in scope. This is independent of the ordinary denial for an unauthorized second case. |
| New inspector/catalog entrypoints under maintenance | Both reject while FROZEN before the first product projection/enabled check; no unadmitted new read-composition entry was introduced. |
| Recovery and administrative perimeter | `apps/platform_recovery`, `apps/private_media`, `apps/intake_workflow/management` and shared `config` are byte-for-byte unchanged against the reviewed P0 head (git diff). New harnesses use encrypted capture/restore, explicit maintenance and isolated synthetic target checks; no new plaintext fallback was found. Unchanged backup, callback and administrative suites were not repeated locally. |

The registry's VIEW-authorized historical metadata is not a source READ/PUBLISH
grant. Its full-text/quotation/original-publication uses remain unsupported. The
catalog remains private scoped staff output; navigation fields cannot authorize
a case or publication. No Meta contract or production connector was added by this
delta. Tests intentionally use the existing canonical services, not a replacement
ledger, queue or permission model.

## Executed independent tests

Product tree under test: exact `5ec6373f5eaf3cd5ea2b14d7b3e7119826ceb4c8`, with
only this lane's new tests present. Fresh owned PostgreSQL clusters, synthetic
data, Python3.13.16; no CI result is substituted for these executions.

| Batch | PG17.12 | PG18.7 |
| --- | --- | --- |
| Initial seven independent methods | 6 PASS / 1 fixture ERROR, 3.083s | 6 PASS / 1 fixture ERROR, 3.186s |
| Corrected frame fixture only | 1 PASS, 0.200s | 1 PASS, 0.192s |

All **seven distinct methods have passing evidence on each major across the
focused runs**. This is not described as a single final seven-test clean run.
Initial failure was in the positive setup: `Directory.grant(other_ref)` replaces
the full scope set, so it inadvertently removed the first case. The corrected
fixture explicitly grants both refs. The implementation correctly denied the
initial request; no product assertion or permission was relaxed. Only that method
was rerun. The six unaffected successes were not repeated.

Durable logs in `tests/v13_security_review/evidence/`:

- `pg17_initial.txt`, `pg18_initial.txt` retain the original error and all successes.
- `pg17_frame_correction.txt`, `pg18_frame_correction.txt` contain the corrected pass.

Ruff check, Ruff format check and git diff whitespace check pass. No browser rerun
is claimed by this lane; the new independent checks exercise actual native HTTP
where evidence-version behavior matters and service composition elsewhere. No
original-source license, public rollout, privileged SQL boundary or production
backup RPO/RTO claim follows from these synthetic tests.

## Integration contract and later review

Cherry-pick this review branch's tests/report only. Add the explicit test label
`tests.v13_security_review.test_delta` to the integrator-owned affected V13 runner.
The test module imports fixture helpers as modules so discovery does not silently
rerun imported legacy TestCase classes. It defines seven new independent methods.
Registry fixture construction uses the existing historical setup, then enables
strict rights before every assertion. The maintenance test configures a real
synthetic FROZEN control with strict admission enabled.

Example command from the integrated checkout (set binaries to the local matching
installation; repeat with major18):

```sh
V12_PG_BIN=/tmp/v9-pg/usr/lib/postgresql/17/bin \
  .venv/bin/python infra/dev/with_casework_postgres.py \
  --pg-bin /tmp/v9-pg/usr/lib/postgresql/17/bin --major 17 \
  --settings config.settings.campaign_review -- \
  .venv/bin/python manage.py test tests.v13_security_review.test_delta --verbosity 2
```

Local PG18 used `/tmp/v12-pg18-built/bin`, the previously documented18.7 build;
this does not claim every binary-build feature matches CI. No new schema exists.
Future V13 changes require a new exact-head diff review and affected PG17/18 checks.
If a concrete vulnerability emerges, stop its affected path until the product owner
repairs it and independent verification passes; this lane does not repair product
files or transfer its bounded PASS to unreviewed commits.
