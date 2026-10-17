# Reviewed E4 internal patch and E5 local wiring

Coordinator authorization: apply the exact accepted internal E4 patch only to the
local integration branch, wire E5-owned flags/routes/labels, and wait for E2's
actual loader adaptation. No push, PR, metadata update, public/middleware change
or speculative E2 implementation is authorized for this increment.

## Byte verification and provenance

Both payloads were verified before `git apply --check` and application:

| Payload | Bytes | SHA-256 |
| --- | ---: | --- |
| gzip | 18,931 | `d490f46cf9b60d5dacecf9c0d51f2d0d29ce31e0816d8e7989336687e3d91712` |
| decompressed patch | 64,276 | `1810f47de64f4933e75f03d607966faf09a08963e5792f88ca86b0370dee6c3e` |

Source foundation is `34355f5173667c6167351cf379ad56957d7f35f3`. Application
parent is local E6-P2 integration head
`ca068301fa04eab74d3293f9a7c08939555ab82c`. The coordinator reports producer-local
`dd1c92e` and IndependentAstra ACCEPT for the exact patch: 55 pure, 49 no-DB,
62 Node and 68 plus eight extra scenarios on each PG major. These are coordinator
reports, not E5 execution counts or a remote commit ancestry claim. No E4 remote
branch is invented, fetched or published.

The patch has seven paths: `apps/reference/services.py`, `apps/reference/views.py`,
three E4-owned documents, `tests/integration/api/test_wave7_workflow_reads.py`,
and `tests/integration/ui/wave7_workflow_reads_db.py`. Their postimage blobs are
checked against the supplied patch and left unchanged. Product and test source
fixes are not guessed into the reviewed patch.

## Concrete E5 wiring

Only the separate Wave7 settings profile reads canonical
`FATWA_WAVE7_SYNTHETIC_READS=1`, setting `WAVE7_READS_ENABLED` and
`WAVE7_REVIEW_READ_ENABLED` to the same boolean. Both default off; old review-only
opt-in alone enables neither. The existing ownership/write-configuration guard
still validates every actual E4 read. No guard, model, migration or root dependency
is changed.

`config.wave7_urls` registers the actual three E4 API functions plus the existing
persisted E2 GET screen before generic legacy patterns. Public/base URL/settings
and middleware remain unchanged. Malformed string item IDs reach E4's fixed JSON
validator. Unsafe methods and disabled handlers do not query or mutate a DB.

C6 explicitly runs E4's eight no-DB cases with ordinary settings and PGPORT=1 via
`wave7_qa.py --suite workflow-off`. The actual ten-case DB module is appended only
to `--suite database` under the existing owned PG17/18 runner. No DB module enters
C6/D6 port-1 discovery. CI's two Wave7 jobs use the common read opt-in.

Four E5 pure wiring cases reproduce missing flags/routes first (RED: four tests,
six failure entries including subtests), then pass with unified settings and
actual routes. The shared DB module now has four cases, including real E4 API vs
SSR-context agreement for mode/filter/page state and original source/citation
data; the existing E2 screen is checked independently. These cases do not claim
that E2 already consumes E4.

An initial E5 test sent a stored question's TAB/newline as a search query. Both
PG runs correctly rejected it under the unchanged `validate_search` contract
(one test error each). The E5 test now uses valid exact search text and separately
asserts the unchanged original question and pointer source; control-containing
queries are explicitly checked as JSON 400 without DB access. No production
validation or reviewed E4 bytes were changed for that correction.

## Evidence and pending work

The explicit DB collection is 106 cases: previous 94, ten actual E4 DB cases and
two new shared-route/context cases. Pure collection is 49 (the fourth E5 wiring
case is new), plus six E2 and eight E4 default-off cases. Actual command/count/SHA
outcomes are retained under `.local/qa/wave7-integration/e4-reviewed/`; final
handoff distinguishes development DIRTY results from a clean committed SHA.

E2's producer-owned loader adaptation including mode is pending its actual patch.
Full E6 browser reruns after this E4 assembly wait for that patch. The earlier
protected browser attempts at `ca068301…` have zero browser passes and 12 cases
NOT_RUN on each PG because Cloud's Chromium SUID helper is misconfigured; no
security bypass is used. Windows/GitHub Actions, real-source checks and fresh
independent combined review remain NOT_RUN. Publication stays held.
`NOT_DEPLOYED / GATES_HOLD / USAGE_NOT_OBSERVED`.
