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
