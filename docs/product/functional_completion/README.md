# Functional completion: connected case, research and knowledge workflows

The baseline for new requirement credit is `review/20261120-mufti-priority-queue`
at `4825f025b3f95eacd08fa315a062d6850e896b69`. The first five groups were delivered
at `da920d3a206e8a0776e64f801093e3a05d06f2c7` in draft PR241. The subsequent
`review/20261120-knowledge-completion` branch adds the final four groups and an
additive, conservative point audit. Existing source and historical acceptance
matrices are preserved. All work uses the current native case/research/requester
composition and explicitly synthetic, opt-in development capabilities.

## Delivered behavior and evidence targets

| Functional group | Reviewable outcome | Primary verification |
|---|---|---|
| Case responsibility and workload | Claim/release/transfer, primary/contributor/reviewer history, my/shared/new-facts/draft/review/approved queues | `apps.case_assignments.tests`, `apps.case_assignments.review_tests`, native assignment browser |
| Case organization | Independent metadata version, tags, multiple question types, internal notes, explicit authorized search | `apps.case_organization.tests`, connected browser |
| Private research workspace | Named collections, exact-source selections, private notes, reorder/archive/restore, saved searches and two/three-material comparison | `apps.research_workspace.test_collections`, connected browser |
| Content reporting | Report a currently authorized exact content version, private requester receipt, human triage/verification/reopening/duplicate links | `apps.content_reports.tests` and independent revocation regressions, connected browser |
| Continuous audio recording | Pause/resume the same sample buffer, listen before selecting, preserve the total recording bound and server verification | real worklet tests and protected audio browser test |
| Lessons and manual relations | Independent lesson categories, series/versions/order, multiple exact lesson links, four human-reviewed directed relation kinds and native filters | `apps.scholarly_links.tests`, protected scholarly browser |
| Public knowledge and reviewed translations | Reviewed public scholar fields, separately released exact related-fatwa/lesson metadata, immutable human translations, original-language fallback, breadcrumbs, structured data and sitemap | `apps.public_knowledge.tests`, `apps.public_knowledge.test_scholarly`, protected public browser |
| Selected exports | Real JSON/CSV/JSONL ZIP packages, manifest/checksums, independent export grants, native preview, durable jobs/retry/cancel/expiry and current authorized download | `apps.selected_exports.tests`, `test_durability`, protected real-download browser |
| Data quality | Current scoped required-record/file/attribution/reference diagnostics, separate human-report state and native refresh without rewriting originals | `apps.data_quality.tests`, protected lost-file/restore browser |

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

### Conservative additive audit

`scope_plan.json` preserves the exact original wording and direct specification
IDs for57 whole-point candidates:8 assignment,10 organization,3 private research,
2 content reporting,1 recording,12 scholarly relationships/lessons,12 public
knowledge/translation/navigation,7 export and2 quality points. Those57 points
describe **nine connected functional groups**; two original points sharing a
feature do not become two independent functional units.57/556 is10.2518% of the
original point inventory, conditional on actual aggregate execution.

The plan alone never certifies that percentage. `functional_scope_receipt.py`
checks the unchanged inventory hash, exact original text, duplicate/excluded IDs,
required executed test families, the clean tested commit, all stage exits and
fresh protected-browser proofs. It emits `scope-audit.json` alongside each
PostgreSQL execution receipt. Local runs without protected browser evidence
remain `PENDING_PROTECTED_BROWSER` and credit zero completed points for that
execution; only a successful complete run emits the reviewed57-point result.

The exclusions are deliberate.338 describes authorized private research usage,
not an independent researcher administrative role.339 and471 remain partial
because all promised content types, including the absent hadith corpus, are not
available.281/283/284/285 remain partial: public scholar pages show granted fatwas
and separately released lessons, while all general-material types and cross-case
topic-hub aggregation are unfinished. Topics in this batch remain scoped to
their authorized owning case.364 implements the documented format-by-purpose
choice through JSON/CSV/JSONL; XLSX/Parquet and video are explicitly unsupported.
Bulk import/reimport, production role policy and corpus completeness receive no
credit. Existing follow-ups and already-implemented nonblocking enrichment rules
are regression evidence only. The dedicated drafts inbox is delivered, but point59
is conservatively excluded from new credit because current saved drafts were
already listed for review in the baseline. Public breadcrumbs are extended to new
fatwa/topic paths, but point459 is also excluded because native public catalog
breadcrumbs already existed and were tested in the baseline.

## Reproducible verification tied to a commit

`infra/dev/functional_verify.py` refuses a changed tracked working tree or a
checkout differing from `EXPECTED_SHA`. On a freshly owned PostgreSQL17 or18
instance it runs Django configuration/migration checks, worklet tests, the
affected existing/new service and native-HTTP tests, then the encrypted recovery
drill. `--browser` additionally requires protected-browser opt-in and runs the
connected journey, assignment journey and pause/resume scenario.
It also runs the native lessons/relations, public curation/translation, selected
ZIP download and data-quality refresh journeys through the shared campaign.

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

The encrypted recovery drill populates all22 new durable tables, freezes the
source, backs it up through the existing encrypted recovery service and restores
to a new database. It compares the full database inventory (including rows and
sequences), verifies the original remains unchanged and frozen, then starts a
fresh process to read the new workflows. Restored immutable rows reject deletion,
and removing the synthetic identity closes all new readers. No durable plaintext
database dump is left behind.
The restored process uses the restored private-file root, reopens exact lesson
originals, replays reviewed public curation and re-downloads the identical export
artifact under fresh explicit synthetic authority. It does not deserialize or
invent real identity/grant state. Source inventory and frozen state are checked
again after the fresh-process readers. Data-quality diagnostics add no table.

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
