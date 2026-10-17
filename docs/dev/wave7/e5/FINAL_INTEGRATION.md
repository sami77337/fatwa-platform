# Wave7 final local composition for fresh independent review

Continue the existing isolated local branch from
`003a8d65c6c01572cbd1f0a95ba87e3f04584f81`. Foundation remains exact
`34355f5173667c6167351cf379ad56957d7f35f3`; models, migrations, shared guard,
fixed configuration and source contracts are unchanged. Publication approval
remains pending: no push, PR, metadata update, deployment, main change, real data
or Wave8. This is development integration, not product/source acceptance.

## E2 transfer and provenance

All eight numbered ASCII base64 chunks were saved individually and their supplied
SHA-256 values verified before concatenation. Chunks 1–7 are 2,400 bytes each;
chunk 8 is 420 bytes. Only after all eight arrived was concatenation decoded:

| Payload | Bytes | SHA-256 |
| --- | ---: | --- |
| gzip | 12,914 | `63913013860afeb2755f90a756a060b69a834cd06a29804eaf5e00c0af770b95` |
| raw E2 patch | 43,383 | `14ede6eb50c6fcf361fa03908e2f3d4d644962fe415ebda2dc643731f73ecc93` |

The coordinator reports Independent Astra ACCEPT for this exact patch (75 no-DB,
80 plus eight independent adversarial DB cases on each PG major, no failures or
skips). Those are supplied review reports, not E5 execution claims or independent
acceptance of this new composition. Reported producer-local
`0eef2ea494b336e66f6622b89efa63d94cbc43d1` is based on published E2
`b55c4596506aafd3c3d5c3a3c0fee1450fc2d2c2`. The local hash is patch provenance,
not remote ancestry. `git apply --check` passed on the actual E4/E6 composition.

The nine E2 paths are applied unchanged, including its actual service/view,
template, original read regressions and new eight-case adapter DB module. Their
postimages are checked against an independent temporary application of the exact
verified patch. The original E4 patch and E6-P2 provenance remain recorded in
the preceding handoffs; published E1/E2/E3/E6 heads remain ancestors.

## Necessary integration changes only

E5 adds `tests.editorial_demo.test_wave7_e4_adapter_db` to the mandatory PG-only
registry. All modules must import and collect nonzero cases; DB tests never enter
the C6/D6 port-1 labels. The E5 shared-route test uses the canonical common read
flag and explicitly preserves the new `mode` query state.

An actual HTTP/DB reproduction exposed a consumer incompatibility: the old E6
browser searched `W7-READY-2` and expected one row. The real adapted E2/E4
question-only search correctly returns zero, so the controlled old expectation
fails (one RED test). E6's desktop and mobile queries now use question text
`اصطناعي`, native mode `normalized`, and `READY_FOR_EDITOR`; the actual E5 DB
regression verifies one selected row and exact question/citation per batch, while
the external-ID query remains empty. The browser now checks mode in return state.
This changes no producer contract or source text, and removes no exact citation,
pointer, ordinal, row, batch or locator assertion introduced by E6 P2.

The existing common read setting/alias, three E4 JSON routes, E2 persisted route,
loopback and GET/HEAD boundaries remain unchanged. No source guard is relaxed,
no source fixture is repaired and no arbitrary media/network/write path is added.

## Same-head verification contract

The fresh final handoff under `.local/qa/wave7-integration/final-assembly/final/`
records the exact clean committed SHA for every run and transferable diff/bundle.
Required groups are:

- 115 Wave7 PG cases per PG17/18, including actual contracts, idempotency/review
  races, real partial-write rollback, source preservation, E3/E4 reads, E2 adapter
  and shared API/SSR/browser-query integration.
- E6 actual storage/assets six plus actual workflow/new-process race two per PG.
- Full B6 regression (170 cases), migrations/checks on both synthetic PG majors.
- Wave7 pure49, E2-off6 and E4-off8 with unreachable DB; legacy D2 no-DB61
  plus the latter two groups give the 75-case E2/E4 no-DB scope.
- E4 Node62, E6 Node18 (including the standalone mandatory ten-case reference
  negative gate), dispatcher, C6/D6, system and full importer inventory/regressions.
- Actual E6 catalog baseline and persisted browser entrypoints, protected sandbox
  flags only, separate artifacts and explicit NOT_RUN if the engine cannot start.

These counts identify intended/collected groups, not a future success claim;
actual commands, failures/skips and SHA-specific results are in the final manifest.
Earlier DIRTY development reports and setup corrections are preserved separately.
No unsupported browser workaround, DOM substitute or HTTP 200 satisfies browser
acceptance. Cloud's previous Chromium launches failed its SUID helper check;
Windows/GitHub Actions and real-source checks remain NOT_RUN until actually run.

The coordinator owns fresh independent Astra review and any later dispatch.
`WAVE7_LOCAL_INTEGRATION_READY` means local review handoff, not approval of browser,
Windows, real source or product gates. `NOT_DEPLOYED / GATES_HOLD / USAGE_NOT_OBSERVED`.
