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

No V14 functional, browser or final-head CI completion is claimed here yet.
The V14 verification runner rejects missing composition; it does not substitute
the narrower V13 journey for V14. Source fidelity corrections are attributed to
local coordinator checks, not independent Cloud verification. Historical startup
failures retain ROOT_CAUSE_UNKNOWN unless new evidence proves a cause.
