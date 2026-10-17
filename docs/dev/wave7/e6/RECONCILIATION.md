# Recovered specification and leadership P2 review follow-up

The complete recovered Wave7 dispatch was received after first-increment PR59.
It resolves the prior missing text, preserves foundation
`34355f5173667c6167351cf379ad56957d7f35f3` and the existing E6 work, and requires
no schema/application guard/settings/middleware change here. The accepted
lossless numeric contract retains precedence over old source JSON field wording.

Reconciled facts: fixed configured scope; reference ordinal per item; sole E5
application guard before write transaction; known owned nonempty databases may
continue without reset; CLI/service writes only; existing pipeline GET reads;
E2 owns wave7_review; E5 alone registers separate opt-in app/settings/routes.
The E6 prefix/opt-in is just stricter test-resource selection before delegating
to that same shared guard, not a competing application write guard.

The approved CLI syntax is now explicit. Actual E1 head
`c4adc405b053162d054f8660065b205f94bae4e1` rejects
`wave7_intake check --input <known-synthetic-file> --synthetic-fixtures-only`
with exit2 / `unrecognized arguments: --input`. A new pure E6 regression
`tests.acceptance.wave7.test_entrypoints` uses SimpleTestCase (DB forbidden)
and the approved named flag. It fails on that real E1 source snapshot, without
editing the command. On foundation-only E6 it also fails because E1 is absent;
it is an explicit integration label, never optionalized into green baseline.
**Resolved on final E1 2678b91a7c7f2e210a7585e6997725432782aa72:** E6 rechecked
the same pure regression and it passed 1/1. No E1 rework is requested for this
historical issue. Exact currently observed E1/E3 signatures
and SHA pins are recorded in INTEGRATION_HANDOFF.md, with no execution/acceptance
claim for their complete services yet.

Leadership separately identified P2 in E6 browser key transport. Reproduced RED
through the actual CDP serializer with a recording transport: 2 tests, 1 PASS /
1 FAIL, because Enter lacked code/text/unmodifiedText. Fixed the shared E6-owned
keyboard helper: keyDown sends code='Enter', text='\r', unmodifiedText='\r';
keyUp sends code without injecting CR again. Arrow/navigation behavior remains
free of Enter text. Combined CDP/policy/keyboard suite GREEN: 8 PASS, 0 FAIL/SKIP.
The real browser search/navigation case calls this same helper for native form
submission, then requires actual search results, detail, history and reload.

Protected-browser execution of the corrected helper is NOT_RUN: the previously
observed Cloud SUID startup gate remains blocked; no supported engine run or
browser PASS is claimed. E5 must execute actual protected Chrome in supported
standard CI before acceptance. Full workflow still waits actual E1–E4 integration,
and its dedicated gate remains failing rather than falling back to catalog-only
acceptance. Actual published producer hook/PR61 journey implementation has since
been added; see PRODUCER_HOOKS.md for the current component evidence and missing
E5 route/flag/protected engine. Existing PG17/18 six-test results belong to tested head2966b99; this
follow-up does not alter their storage/asset code or the approved foundation.

No new task/worktree restart, no Wave6 changes, no other-lane production changes,
no PR58 metadata edit, no security weakening, merge, deployment or Wave8.
