# Actual canonical search evaluation and independent review

Status: development implementation, disabled by default. **NOT_DEPLOYED. Gate B NOT_PASSED; Gates C/D/E HOLD; Phase01 BLOCKED.** This change does not create a real Arabic specialist GoldBenchmark or promote any search configuration.

## Original scope and limits

The immutable owner inventory is `docs/product/v14_scope_evidence/matrix.json`; the exact texts and source locators are retained in the additive audit `../audit_research_215_374.json`.

| Original ID | Exact original text | What this implementation establishes |
| --- | --- | --- |
| 242 | لا نقيس البحث بالانطباع فقط. | A durable actual PostgreSQL comparison, with authored expectations, source and code pins, measured results, metrics, and independent review. |
| 243 | ننشئ Gold Benchmark عربي حقيقي. | **Still pending.** Synthetic development sources and test identities are not real Arabic gold material or specialist acceptance. |
| 244 | يحدد متخصصون النتائج الصحيحة للاستعلامات المرجعية. | A native workflow for an explicitly authorized author and independent reviewer, bound to actual current source versions. A specialist's real judgments are not supplied or claimed. |
| 245 | نقيس Recall وPrecision وجودة Ranking وCoverage. | The existing scorer measures actual query results; the report states every denominator and keeps positive and negative controls separate. |
| 246 | تغييرات كبيرة في Ranking أو Embeddings أو Normalization تمر باختبارات Regression. | Explicit per-query regression rules and immutable review for a dictionary candidate on the existing FTS profile. This does not implement embeddings or a runner for arbitrary ranking/normalization engines. |

All five points map to SPEC-U05-027 and D-023, with reverse mappings SPEC-U15-009/SPEC-U16-023. This document adds **zero whole-point credit**. An integrated protected browser result and the aggregate encrypted restore must be recorded against the actual integrated head before any new completed-unit claim. Even then, the real-corpus/specialist and arbitrary-engine limits remain.

## Preserving the existing evaluation

`EvaluationRevision` and `EvaluationDecision` remain the shared authored-expectation and independent-review models. A new explicit `engine` distinguishes:

- `TITLE_WORDS`: the default for every existing record; the original synthetic title corpus schema, fixture file, expectation meaning, ranker identity, and `PENDING`/`APPROVE`/`REJECT` states remain unchanged.
- `CANONICAL_FTS`: actual current canonical document IDs and hashes, the exact generation/source/allowed-document fingerprints, and one to eight authored queries. Expected document order and the author's relevance rationale are saved without deriving expected answers from the retrieval algorithm.

Version numbers and current-revision checks are independent per `(case, engine)`. The old title-review services filter their own engine and cannot approve canonical judgments. The original `fixture.json`, `evaluation.py`, `ranking.py`, and old metrics files are unchanged.

Only two new tables are added:

1. `arabic_search_eval_canonicalbenchmarkrun`: an immutable run linking the exact approved judgment decision, chosen dictionary revision and independent dictionary approval, current source pin, code/profile/scorer fingerprints, actual shadow-comparison IDs/digests, results/metrics, workload, regression reasons, actor identity, case versions, and idempotency key.
2. `arabic_search_eval_canonicalbenchmarkdecision`: one immutable independent `ACCEPT` or `HOLD` decision for the exact run digest. An author or executor cannot review their own run. `ACCEPT` is unavailable when any regression rule requires `HOLD`.

PostgreSQL guards reject mutation, wrong case/head, out-of-corpus expected IDs, duplicate/missing judgments, incomplete or self review, stale revision/approval/generation, forged comparison references, and noncanonical row payloads. Run reads independently recompute the metrics from the immutable actual comparisons using the existing scorer; they do not trust stored aggregate numbers alone.

## Actual execution and measurements

`canonical_search.governance.run_shadow_in_context` extracts the existing shadow body into a composable current-source boundary. It executes the identical existing baseline FTS and explicit dictionary candidate SQL paths. The original `run_shadow` service remains the wrapper for ordinary dictionary comparisons. Candidate SQL failure retains the real baseline and produces an explicit error receipt; permission/source changes reject the whole operation.

The benchmark executes each authored query exactly as recorded against one current source generation. It stores both actual ordered result windows and their complete source pins through `ShadowComparison`. It does not replace or rewrite any canonical question, answer, or transcript. Ordinary FTS and literal search remain unchanged unless a user explicitly chooses a dictionary in the separate governed search workflow.

The existing `arabic_search_eval.evaluation.score` remains the metric implementation:

| Measurement | Defined denominator/window |
| --- | --- |
| Precision within the first five returned results | Relevant returned documents divided by the **number actually returned within the first five**, preserving the existing scorer's definition. An empty result has precision zero. |
| Recall within five | Relevant documents retrieved within five divided by the authored expected relevant-document count. No-relevant-result controls have undefined recall and are reported separately. |
| Reciprocal rank | The reciprocal of the first relevant result's position within five; zero when absent. The report averages positive queries. |
| Judged-query hit coverage | Fraction of positive judged queries with at least one relevant result within five. This is not coverage of the whole repository or real fatwa corpus. |
| Negative controls | Queries with any returned document, and returned document count, recorded separately from positive averages. |
| Exact expected order | The full observed window versus the authored ordered expectations, retained as an explicit diagnostic. |
| Latency | Actual elapsed milliseconds around each baseline/candidate service execution inside the shadow operation, including its current-source checks. It is not an end-to-end public latency SLA or production percentile. |
| Workload/cost observation | Actual database statement and SELECT counts during query-pair shadow execution and its source checks. No external AI is called. Database monetary cost is explicitly **unmeasured**, not represented as free or estimated currency. |

Regression status is `HOLD` for any per-query loss in precision, recall, or reciprocal rank; increased false positives on a negative query; a candidate error; or total candidate latency exceeding the larger of 50 ms and five times the measured baseline total. Aggregate improvement cannot hide a per-query regression. `CLEAR` means these explicitly recorded development rules did not find a regression on these authored queries; it is not a quality claim about real material.

The bounds are eight queries, 64 currently readable source documents per corpus, 64 suite versions per case/engine, and 64 runs per case. The existing shadow limit of 128 comparisons per case also applies: a three-query benchmark consumes three actual comparison receipts. No silent truncation of an oversized benchmark corpus occurs. The retrieval observation window remains 20 and the metric window five.

## Current trust and independent review

The single added feature flag is `FATWA_CANONICAL_BENCHMARK_ENABLED=False`. It requires an explicit `CanonicalBenchmarkAuthority` configured as `FATWA_CANONICAL_BENCHMARK_AUTHORITY`, with separate case-scoped `READ`, `PROPOSE`, `JUDGE`, `RUN`, and `REVIEW` decisions and a current policy epoch. No role implies a grant. The currently configured identity provider must match the actor/provider or the request-bound wrapper.

Canonical source/search permissions remain mandatory. Actual run and read also consume the existing `SHADOW`, `SHADOW_READ`, and `DICTIONARY_USE` permissions as appropriate. Native dictionary selection requires `DICTIONARY_READ`. Dictionary expiry/withdrawal, revoked source availability, new source generations, newer canonical judgments, changed execution code, replaced authority/identity, or a final callback revocation prevent stale use. A newer `TITLE_WORDS` version does not invalidate an unrelated canonical suite.

All benchmark permissions are rechecked before the canonical boundary's final callbacks, followed by pure benchmark configuration/code/history checks before the outer transaction commits. Native mutation plus final rendering is atomic. Failure while rendering the response rolls back the run **and all its newly created comparison receipts**. Stale source judgments are not exposed in the desk response; the desk retains only minimal revision metadata until the user authors a new current suite.

## Native workflow

All operations reuse `/casework/staff/` and the existing canonical action dispatcher. No new API or URL is added.

- Open the benchmark from the existing canonical search desk and inspect/open the current original source positions.
- Enter up to eight queries, expected source-position numbers in authored order, and the relevance rationale. Empty expected results define a negative control.
- An independent, explicitly authorized actor agrees/disagrees with every judgment and approves or rejects the exact suite hashes.
- Choose an explicitly approved dictionary version and execute the actual baseline/candidate query pairs.
- Read per-query ordered results, scores, metrics, measured workload and regression reasons. A second independent decision records `ACCEPT` or `HOLD` for that run only.
- A new judgment version starts pending, does not inherit approval, and invalidates current use of prior runs. Source, dictionary and reader revocation likewise prevent stale disclosures.

Forms are native, CSRF-protected, strictly bounded, and bound to the current browser identity, case, action and exact version hashes. Existing original-source forms retain exact HTTP response bytes; CRLF is normalized only by the browser DOM's HTML parsing.

## Verification and integration contract

Local execution evidence and exact log digests are in `local_validation.json`. The protected browser journey is authored at:

`apps.arabic_search_eval.browser_benchmark.CanonicalBenchmarkBrowserTests.test_native_authored_judgments_actual_metrics_independent_decisions_and_current_denials`

Its expected output location is `.local/qa/functional-continuation/search-benchmark-browser/result.json`, with two protected traces and 320/1280 screenshots. It enters real native staff sessions, opens the original source, authors the judgments through forms, rejects self review twice, performs independent judgment/run review, executes actual query pairs, checks nontrivial metrics, creates an unreviewed newer suite, rejects its old run, and rejects a revoked current reader. It launches Chromium with `chromium_sandbox=True`; no local sandbox bypass or synthetic browser PASS is permitted.

The fresh read-only recovery adapter is `apps.arabic_search_eval.benchmark_recovery_support`. Its `TABLES`, `FUNCTIONS`, and `TRIGGERS` define the registry. It populates all four evaluation tables (two existing + two new), actual comparisons, independent judgments/run review, and a separate pending legacy title suite. `verify_restored` reopens the actual stored run with newly configured current identities and permissions, recomputes metrics, and executes **12 negative reads** across missing benchmark authority, missing current identity provider, disabled feature, missing source/search authority, revoked READ action, and revoked current actor. It performs no inserts, updates, deletes, or reindexing.

The root integrator owns the default-off campaign setting, aggregate recovery/table/function/trigger registry, protected hosted browser invocation, and integrated receipts. No production migration, deployment, merge, real source import, specialist approval, or release promotion is part of this change.
