# V13 P0-B independent delta review

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
