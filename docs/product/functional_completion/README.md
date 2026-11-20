# Functional completion: case, research and requester workflows

This branch extends `review/20261120-mufti-priority-queue` at
`4825f025b3f95eacd08fa315a062d6850e896b69`. It preserves the existing source and
historical requirement matrices. Development execution is synthetic and opt-in;
the five feature groups below are integrated into the current staff/requester
journey rather than independent demonstration pages.

## Delivered behavior and evidence targets

| Functional group | Reviewable outcome | Primary verification |
|---|---|---|
| Case responsibility and workload | Claim/release/transfer, primary/contributor/reviewer history, my/shared/new-facts/draft/review/approved queues | `apps.case_assignments.tests`, `apps.case_assignments.review_tests`, native assignment browser |
| Case organization | Independent metadata version, tags, multiple question types, internal notes, explicit authorized search | `apps.case_organization.tests`, connected browser |
| Private research workspace | Named collections, exact-source selections, private notes, reorder/archive/restore, saved searches and two/three-material comparison | `apps.research_workspace.test_collections`, connected browser |
| Content reporting | Report a currently authorized exact content version, private requester receipt, human triage/verification/reopening/duplicate links | `apps.content_reports.tests` and independent revocation regressions, connected browser |
| Continuous audio recording | Pause/resume the same sample buffer, listen before selecting, preserve the total recording bound and server verification | real worklet tests and protected audio browser test |

The legacy team filter regression is also repaired: omission of the newer sort
or inbox field remains compatible, while malformed, duplicate or unknown supplied
values are rejected. Existing V7 tests exercise that actual compatibility path.

Each app documents its bounded authority, schema and remaining scope. New
coordination data never becomes canonical requester evidence or an approved
answer. Saved source references retain exact original identity and are rechecked
at use; collections do not grant source rights. A report does not modify the
reported content. All source content and rights used in tests are synthetic.

## What counts as completion

The denominator is the **556 original owner points** in
`docs/product/v14_scope_evidence/matrix.json`. There are also479 detailed clauses
in the V12 specification inventory; those are a separate denominator. A target
of10–12% of556 requires56–66 whole owner points, with no double-counting of the
same point under several units. A touched point, a passing test, a code file or
a pull request is not itself a completed requirement.

This branch's trace links do not automatically close all associated owner
points. For example, saving available reference/transcript/knowledge sources
does not create a missing hadith corpus; reporting available publication and
transcript sources does not complete every content-type promise; a scoped Mufti
collection does not create an independent researcher role. Historical
`engineering_status` values are intentionally not rewritten. Current execution
evidence and a point-level scope audit must accompany any later completion claim.

Existing capabilities exercised by the combined tests are regression evidence,
not automatically new delivery attributed to this branch. Production acceptance
and deployment are separate from tested development functionality.

## Reproducible verification tied to a commit

`infra/dev/functional_verify.py` refuses a changed tracked working tree or a
checkout differing from `EXPECTED_SHA`. On a freshly owned PostgreSQL17 or18
instance it runs Django configuration/migration checks, worklet tests, the
affected existing/new service and native-HTTP tests, then the encrypted recovery
drill. `--browser` additionally requires protected-browser opt-in and runs the
connected journey, assignment journey and pause/resume scenario.

```sh
python infra/dev/with_casework_postgres.py \
  --pg-bin /path/to/postgresql/17/bin --major 17 \
  --settings config.settings.campaign_review -- \
  python infra/dev/functional_verify.py --pg-bin /path/to/postgresql/17/bin --browser
```

Set `FATWA_BROWSER_SANDBOX=1` and `FATWA_FASTBUILD_BROWSER` to an available protected
Chromium executable. Repeat with PostgreSQL18. The GitHub workflow
`.github/workflows/functional-completion.yml` supplies both supported majors,
Python3.13 and the pinned runtime/browser dependencies.

Receipts under `.local/qa/functional-completion/pg17/` and `pg18/` record the
tested SHA, actual runtimes, commands, exits and SHA256 of stage logs. A local run
without browser is explicitly `SERVICE_HTTP_RECOVERY_ONLY`, never `PASS` for
the complete journey. Protected browser artifacts include a trace and320/1280px
RTL screenshots; the scenario verifies no horizontal overflow, no unexpected
external request, no browser error and no failed HTTP action.

The encrypted recovery drill populates all eight new tables, freezes the
source, backs it up through the existing encrypted recovery service and restores
to a new database. It compares the full database inventory (including rows and
sequences), verifies the original remains unchanged and frozen, then starts a
fresh process to read the new workflows. Restored immutable rows reject deletion,
and removing the synthetic identity closes all new readers. No durable plaintext
database dump is left behind.

The integrated browser uses two separate browser contexts. Staff claim the
case, organize it and compare privately saved research. The requester reports
an actually released media part; staff start and resolve that report with a
verification note, and the requester sees only their receipt. The test verifies
that these new coordination workflows do not change the canonical case or its
event count and do not leak internal notes to the requester.

## Release boundary

All new flags default closed. No main merge, production migration, real data,
external message, role grant, scholarly approval automation or deployment is
performed. Gate B remains **NOT_PASSED**, C/D/E **HOLD**, Phase01 **BLOCKED** and
the work **NOT_DEPLOYED**. These are existing project boundaries, not a reason
to omit the authorized implementation and verification work.
