# V14 integration — in progress, not acceptance

Base: PR #232 at `1f08cbb7166f70ec340c495da33ccfc1eda9534e`.
Integration branch: `codex/20261118-v14-integration`; V13 is preserved.
Gate B NOT_PASSED; C/D/E HOLD; Phase01 BLOCKED; NOT_DEPLOYED.
Leadership reference 83% ±9 is unchanged, not acceptance or a new estimate.

## Actual delegated lanes

| Lane | Thread | Branch suffix after `codex/20261118-v14-` | Exclusive files |
| --- | --- | --- | --- |
| Search | `6afc8096-82c4-8191-98d8-58fba73eb00c` | search | arabic_search_eval, research_workspace |
| Startup | `6afc807f-d7cc-8191-ad01-1d971f53f019` | startup | tests/v14_browser_startup, V14_STARTUP.md |
| Recording | `6afc9ae5-b338-8191-bcff-7654953230ed` | recording | browser_audio |
| PDF citations | `6afc808d-03cc-8191-8171-3bfbe0ad201c` | pdf-citations | pdf_citations, timed_citations |
| Classification | `6afcfb09-8d84-8191-8233-aa8ae1279001` | classification | classification_review |
| Independent security | `6afc80af-d6a4-8191-a0ac-08f14e1b300b` | security | tests/v14_security_review, V14_REVIEW.md |

These are task identifiers supplied by the coordinator, not invented task URLs.
Shared routing, profiles, templates, existing services and CI have one integration
owner. Internal isolated worktrees separately own the new rights batch module,
V14 scope documents and V14 connected browser/restore tests.

## Security blocker history

SEC14-01 is independently reproduced on the base on PostgreSQL17.12 and18.7:
a later policy callback revokes an earlier search result, but its title remains
in the collection. Imported reviewer commit
`673052583830d1747e2417c7a18a93273f435df2` preserves both failures and the unchanged
regression. This is policy mutation evidence, not concurrent SQL evidence.
The affected search path remains BLOCKED pending repair and independent review.
Other V14 deltas remain PENDING review. See [review](../security/V14_REVIEW.md).

## Integrated recording and source receipt

Recording lane `397bd75344dc4e14bfa5c992addcef072eabaaf9` adds native duration/size
progress and fail-closed AudioContext interruption cleanup. The10-second/160044-byte
capture bound is retained. Integration moves the legacy attachment recorder outside
its file label while retaining the same multipart form, file name and CSRF controls.
One affected native-form HTTP test passed on each PostgreSQL17.12/18.7 in the local
integration worktree. This is not protected-browser evidence. The lane's five
browser scenarios are queued for final protected Chrome execution.

The first integration test setup attempt on both majors correctly failed before
test execution with `maintenance_unconfigured`: a strict runtime profile was used
before creating its maintenance root. The runner now bootstraps only the fresh
owned test database with the existing campaign fixture profile; operational tests
initialize their explicit maintenance/storage and strict rights before application
work. The closed V14 runtime profile is unchanged. The corrected affected HTTP
test passed on both majors; the initial setup failures are retained here.

[V14 source lineage](../product/v14_scope_evidence/SOURCE_LINEAGE.md) commits the
attributed parent-local byte/text verification. All556 scope classifications remain
unchanged, with V14 runtime evidence pending. Documentary validation:11/11 PASS.

No complete V14 functional journey, protected browser or final-head CI completion
is claimed here yet.
The V14 verification runner rejects missing composition; it does not substitute
the narrower V13 journey for V14. Source fidelity corrections are attributed to
local coordinator checks, not independent Cloud verification. Historical startup
failures retain ROOT_CAUSE_UNKNOWN unless new evidence proves a cause.

## Classification simulation and startup wiring

Classification lane `ae75b1dc54a87e3421c98bde7efc5b358925f840` is integrated with
explicit disabled defaults for the additional editorial simulation policy. It
creates a separate canonical editorial candidate; neither classification approval
nor the previous edition's publication approval authorizes the new edition.
The pending new candidate and already independently published edition have distinct
withdrawal semantics. This is a closed drill, not an accepted transfer policy.
Migrations0003/0004 and their additive bound-edition guards must survive the final
encrypted schema/asset restoration; that integrated proof remains pending.

Startup lane `8df3438cb19374c04a5870337e6c2d8a334a426d` and shared B6 observer
wiring are integrated. Nine Node checks (including three actual-entrypoint synthetic
startup failures) and12 offline evidence checks passed in the wiring worktree.
Protected B6 must now prove the actual emitted READY observation schema and four
phases through its existing mandatory Python gate. No timeout, retry or sandbox
behavior changed. [Wiring history](V14_B6_WIRING.md) retains initial fixture errors.

That focused hosted proof subsequently passed at exact
`d1ac1a33a1bcdba032e23e55b6a618def2d1af26`, before PDF/classification integration:
[B6 run44233080034](https://github.com/sami77337/fatwa-platform/actions/runs/44233080034).
Decoded logs were read for [PG17 job134562585220](https://github.com/sami77337/fatwa-platform/actions/runs/44233080034/job/134562585220)
and [PG18 job134562585202](https://github.com/sami77337/fatwa-platform/actions/runs/44233080034/job/134562585202).
Each reports10 PASS, four startup phases and READY; measured total startup647ms
and6655ms respectively, with port polling bound12000ms unchanged. These separate
observations prove wiring, not a cause or permanent fix for the historical timeout.
The final V14 head still requires its own CI; these runs are not attributed to it.

## PDF approval/use boundary

PDF lane `fbf06a03db093aeafbdf38321d18c8f81fc7bfbf` is registered default-off and
composed through exact staff routes, the existing request budget/maintenance and
case navigation. Shared `_answer_annotations` adds the PDF guard to the existing
timed guard at scholarly approval, private availability/bytes, simulated delivery,
publication and library checks, retaining the earliest validated deadline through
the outer response/transaction. An omitted app cannot hide retained annotations.

On shared product wiring `c5f44a3`, the new PDF boundary tests have11 distinct
successful checks on each PostgreSQL17.12/18.7 across focused runs;18 existing
affected PDF/audio-context tests also passed per major. This covers READ_MEDIA
and CITE withdrawal separately, late expiry, whole-library counts/categories,
FROZEN, stale evidence, absence of automatic locator copying and exact HTTP/HEAD
authorization. Initial new fixtures lacked maintenance admission around the
simulator constructor (10 setup errors each); after fixing the fixture,9/10 passed
and the remaining HTTP expectation was corrected from standalone405 to the shared
guard's existing400. That HTTP test plus the added collection adversary then passed
2/2 on each major. Product guards were unchanged during those fixture corrections.

PDF parser page count, authorized bytes and `#page` navigation are distinct from
visual page selection in Chrome's PDF engine. The latter remains NOT_VERIFIED.
No private locator or its source becomes a public PDF publication permission.

## SEC14-01B repair and exact-head focused evidence

The external re-review at search lane `e5c504bb` passed the original adversary but
found SEC14-01B: a real ledger REVOKE inside the last policy callback retained the
first title, total, facet and next-page metadata. Reviewer commit
`3204bbfd801faaf3da9ce4a6a4eadd5872d50b60` is integrated unchanged. Its historical
5 PASS / 1 FAIL per major remains; this is callback mutation in the same transaction,
not concurrent SQL. The earlier86/86 integration checks on `570f352` did not include
that new adversary and do not clear it retrospectively.

Product repair `8329364173bde5e76d1a96931cd71dd31fb255d4` adds a pure authoritative
ledger boundary outside both final policy-epoch and identity callbacks. The final
pass invokes no policy callback; it compares current source/grant/version/expiry
projection under the existing case lock before returning any results, counts,
facets or pagination. A final expiry boundary remains outside that ledger check.
The original reviewer test is unchanged; two additional integration adversaries
cover final identity and deliberately side-effecting epoch callbacks.

At that exact pushed head,21 affected checks passed on PostgreSQL17.12 (11.411s)
and18.7 (11.131s): reviewer repair suite, final-boundary tests, search batching and
search services. Search now costs32 SQL statements for both4 and24 candidates
(and the one-candidate comparison); the lane's24-query measurement belongs to the
blocked earlier implementation. The recorded pre-batch baseline was558 SQL.
Independent re-review of this repair and remaining V14 deltas is still PENDING.

## Connected journey integration

Owned journey commit `e64d97b3876c3691e327e8c06916bc4d5a29bdcb` adds one canonical
case through actual synthetic microphone capture, PDF/time locator correction,
versioned evaluation review, multipart answer, partial simulated delivery,
classification and a new independently published editorial edition. A new human
knowledge proposal/approval is required for that edition. It then freezes writers,
encrypts database/assets and opens a separately restored target over HTTP, checking
bytes, scopes, revoked/expired media rights and revoked source rights. Source stays
FROZEN and unchanged; no sender or old verifier is restarted.

Local journey debugging passed1/1 in328.512s on PG17.12, Chromium154 with sandbox
DISABLED, widths320/1280 and no external requests/page errors. The independent
restored target handled104 HTTP checks. This run preceded `8329364` and is only a
harness-debug receipt, not final-head/security/protected evidence. Hosted PG17/18
Chrome sandbox execution on the merged head remains pending. Real expert search
review remains PENDING; PDF engine-selected page rendering remains NOT_VERIFIED.
