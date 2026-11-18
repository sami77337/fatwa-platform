# V13 P1-C — Arabic title search evaluation

Synthetic development only. **Human review PENDING**. No semantic search,
scientific answer generation, invented quotation, automatic citation, acceptance,
or new completion estimate. Gate B NOT_PASSED; C/D/E HOLD; Phase01 BLOCKED;
NOT_DEPLOYED. Book 622 remains a TOC, not a searchable full book/fatwa corpus.

Base: PR #231, `5ec6373f5eaf3cd5ea2b14d7b3e7119826ceb4c8`, independently
confirmed with `git ls-remote origin refs/heads/codex/20261117-v12-integration`.
Branch: `codex/20261118-v13-arabic-search`. Only this directory is owned/changed.
No app registration, shared settings, routes, persisted normalization, existing
research UI, catalog, or library files are changed.

## What is implemented

- `ranking.tokens`: reuse `apps.reference.normalization.normalize_title`; fold
  Arabic-Indic and Persian digits in a temporary search copy. Original strings
  and provenance remain unchanged. Existing alef/maqsura/mark/tatweel behavior is
  retained; ة/ه, ؤ/و, ئ/ي and ء stay distinct. No stemming or synonym expansion.
- `ranking.rank_titles(query, candidates, limit=20)`: whole words with repeated
  word counts; whole decimal tokens (12 differs from 112, 012 and 12.5).
  Exact literal title precedes normalized title, contiguous phrase, all words.
  Ties retain incoming source order. Reasons are inspectable, not relevance
  probabilities. All-word matching intentionally permits reordered words.
- `fixture.json`: 28 entirely invented metadata titles and 42 explicit proposed
  query judgements: 29 positive, 7 negative, 6 invalid. Includes diacritics,
  hamzas, both digit scripts, phrase order, preserved letter distinctions,
  different scopes/editions, denied and expired permission fixtures. Expected
  IDs/orders and rationales were written explicitly, not derived from ranker
  output. Every judgement is AUTHOR_PROPOSED_REVIEW_PENDING.
- `evaluation.py`: deterministic baseline/improved report, fixture/code digests,
  per-query result/error details, and a fixture-bound human review worksheet and
  completeness validator. There is no reviewed gold benchmark yet.

## Integrator contract

The pure ranker accepts **already-authorized metadata only**; it cannot authorize
retrieval. Candidate objects contain an identifier and original title; returned
hits contain identifier/tier/reason. Maximum 40 candidates, 20 default results,
80 query characters, 10 query tokens. Empty, marks-only, punctuation-only,
control/surrogate and oversized queries fail with ValueError. Duplicate IDs and
oversized candidate windows fail rather than silently inflating metrics.

For a canonical case-scoped, strict-ledger adapter use:

```python
from apps.arabic_search_eval.services import search_reference_titles

result = search_reference_titles(
    case_id=case_id,
    subject_id=subject_id,
    provider=identity_provider,
    query="رقم ١٢",
    edition_id=edition_id,
    printed_part="",
    printed_page=None,
    synthetic_fixtures_only=True,
)
```

Requires existing research feature, source-rights app/ledger and identity/rights
policy, `FATWA_SOURCE_RIGHTS_ENFORCED=True`, plus explicitly set
`FATWA_ARABIC_SEARCH_EVAL_ENABLED=True` (otherwise disabled). Existing synthetic
database, production-off and maintenance-admission guards remain mandatory.
No new identity, permission, ledger, index or storage is created.

The adapter calls existing `research_workspace.services.search` with empty query,
REFERENCE kind and exact edition/location, then ranks that service's **first 20
authorized candidate titles**. Its empty internal browse is never an accepted
empty caller query. Metadata read/open checks surround ranking, DISCOVER is
rechecked before returning selected rows, identity is rechecked, and the existing
projection-expiry guard covers the entire response (including zero-hit reads).
Canonical case locks and maintenance admission remain held through composition.

Output preserves existing result `resource`, `source`, `title`, `label`, `kind`
and adds `ranking: {tier, reason}`. Envelope includes public_ref, revision,
evidence_version, ranking_version, material=TOC_METADATA_ONLY,
human_review=PENDING, coverage=BOUNDED_CANDIDATE_WINDOW, candidate_pool_limit=20.
There is no total corpus count or claim of exhaustive recall. Use exact unchanged
`Resource(**row['resource'])` with existing `workspace.open_resource`; further
citation actions must use existing current-rights/versioned services. READ does
not grant CITE, PREVIEW_METADATA, full book text or public publication.

**Coordinator wiring remains opt-in and pending**: show the bounded-window
label, original title/edition/location and deterministic reason; preserve the
existing open/return state. Do not replace the global search or infer no corpus
match from an empty window. This module adds no UI or public route, so no browser
claim is made. Full-corpus paging/indexing, transcript/library integration and
human-approved ranking changes require separate owned integration work.

## Measured evidence and limits

`metrics.json` is reproducible on the pinned fixture and source digests:

| Measure | Baseline | Improved |
|---|---:|---:|
| Macro positive-query truncated precision@5 | 0.853448 | 1.000000 |
| Macro positive-query recall@5 | 0.896552 | 1.000000 |
| MRR@5 on positive queries | 0.879310 | 1.000000 |
| Exact proposed ordering (36 valid queries) | 21/36 | 36/36 |
| Negative queries with false-positive results | 1/7 | 0/7 |

Precision divides relevant returned items by **returned items up to 5**, not
always by 5; an empty positive result scores zero. Recall divides by explicit
expected-set size. MRR uses first relevant result among the first 5. Six invalid
queries are excluded from retrieval means and exact-order counts; improved query
validation rejects all six. Expected ordering is evaluated separately from set
relevance. Both systems have zero forbidden fixture hits because the identical
synthetic eligibility filter runs before either search. **This synthetic filter
is not evidence of real authorization**; the PostgreSQL tests below are.

Baseline faithfully replicates citation search's shared normalization + each
token's substring predicate + source order/20-result cap on these same small
pools. Oversized/control query rejection models upstream validation. It does not
claim a SQL timing comparison. The real PostgreSQL adapter test additionally
checks existing search returns zero for Arabic `١٢` against ASCII 12, and returns
12/112/12.5 for ASCII `12`, while the new adapter returns only exact 12.

The small authored fixture intentionally exercises known failure classes. Its
perfect improved scores are **not an independent held-out result**, not a
human-reviewed benchmark, not product-wide recall, and not specialist acceptance.
Prefix/fuzzy matches are intentionally absent; stem/affix variants and decimal
punctuation equivalence are not supported. These tradeoffs need human review.

2026-11-18 focused execution:

- Pure suite: **7/7 passed** (0.018 s latest run).
- Fresh owned **PostgreSQL 17.11**: **6/6 passed** (4.254 s latest run), system
  check clean. No PG18 or browser execution claimed for this lane.
- Real adapter sample: 4 authorized candidates, 1 result, **558 SQL statements,
  0.4695 s** in this local synthetic run. Expensive repeated provenance/rights
  checks are inherited/composed; this is not a performance improvement or SLO.
  Do not enable broadly without profiling the larger authorized window.
- Ruff lint passed; formatting applied only inside this directory.
- First PG run failed three tests because nested test settings restored the old
  workspace policy. Test setup now explicitly configures current policy/identity;
  expiry/revocation tests assert ranking was actually reached. No product bypass
  was added. The focused corrected run passed; historical failure is retained here.

PG checks cover real baseline comparison, unchanged originals, exact open pins,
unregistered/expired/revoked sources, wrong edition/location/identity/case,
synthetic acknowledgement, expiry during ranking including empty results,
mid-ranking DISCOVER revocation, disabled flag/strict mode, and invalid queries
rejected before retrieval. They do not rerun unrelated V6–V12 suites.

```bash
.venv/bin/python -m unittest apps.arabic_search_eval.test_ranking -v
.venv/bin/python infra/dev/with_casework_postgres.py \
  --pg-bin /path/to/postgresql/17/bin --major 17 \
  --settings config.settings.campaign_review -- \
  .venv/bin/python manage.py test apps.arabic_search_eval.test_services --noinput
.venv/bin/python -m apps.arabic_search_eval.evaluation > /tmp/arabic-metrics.json
.venv/bin/ruff check apps/arabic_search_eval
```

## Pending human review

```bash
.venv/bin/python -m apps.arabic_search_eval.evaluation \
  --review-template > /tmp/arabic-review.json
# A real authorized reviewer examines fixture titles and each expected list,
# records identity, evidence_reference, AGREE/DISAGREE and explanatory notes.
.venv/bin/python -m apps.arabic_search_eval.evaluation \
  --validate-review /tmp/arabic-review.json
```

The generated template is PENDING and deliberately fails completed-review
validation. Validator checks fixture digest, complete unique query IDs, unchanged
expected sets, per-query verdicts/notes and identity/evidence fields. It cannot
authenticate a reviewer or substantiate the referenced evidence; success returns
RECORDED_REVIEW_REQUIRES_INDEPENDENT_IDENTITY_VERIFICATION, never ACCEPTED.
Disagreements require a separately reviewed fixture revision and new digest/run;
do not erase previous results. No human review has actually been recorded.

Scope alignment (not completion): original search/access requirements 216,
218–221 and benchmark requirements 242–246; D-020 literal source preservation,
D-023 specialist benchmark pending, D-045 non-AI baseline, D-069 TOC boundary.
Unresolved approvals, rights policy and gate restrictions remain unchanged.
