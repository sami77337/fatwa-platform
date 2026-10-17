# Verified E6 reference assertion patch: local application only

The coordinator authorized this exact reviewed code patch on the existing local
integration branch, with no publication and no E4 change. Its gzip/base64 packet
decoded to **12,203 bytes**, and SHA-256 was checked before `git apply --check`:

`8798945fcfa54d14d42d33c9bc33ccebfa939cfe88a100fc5d0bf4d892756da4`

The patch is based on published E6 head
`6e28248beceda4ff6f07c90e5fa5aa08c1cd6cc6`. The three modified E6 preimages match
that head exactly in local integration parent
`8d0ff3e40d4aef7ef6a1625263762689133f9076`; the two assertion files are new.
The coordinator reports equivalent code from unpublished local `c2e514c` and
IndependentAstra ACCEPT for the patch. This is **patch provenance**, not a claim
that `c2e514c` is a published or reachable commit ancestor. Published producer
heads are preserved. No remote branch is fetched or modified for this update.

The coordinator's reported independent results were 18 Node cases, four guard
cases, 17 independent probes and two workflow-service cases on each PG major,
with 12 browser cases NOT_RUN. Those reported probes are not claimed as E5 runs
or fresh independent review of the new assembled SHA.

## Exact change and regression

The old browser assertion `/VERIFIED/` also matches `UNVERIFIED`. A controlled
pre-patch reproduction uses that literal assertion from the actual old harness
and fails because UNVERIFIED is accepted. The verified patch replaces it with an
exact detail-section check for VERIFIED status, selected batch and row UUIDs,
original question and source pointer, reference ordinal, full nonempty expected
citation and printed part/page locator. It checks again after reload. The fixed
citation expectation is independent of the renderer and stored DTO under test.

Ten Node cases reject the negative status, missing/unrelated citation, wrong
locator, row, batch or pointer, and missing reference cases. With the six CDP and
two keyboard cases, the actual C6 invocations now collect **18**, rather than
eight. The new ten-case file runs through its own mandatory nonzero gate, so zero
collection cannot be masked by the existing eight. The workflow-service case
checks the new expectation against actual E1,
E2 and E3 data. Product services, frozen guards/schema, dependencies, E4 and B6
labels are unchanged. Only the verified five-file E6 patch, the actual C6 Node
invocation and supporting operation/evidence text are changed.

## Verification and remaining gates

Exact local commands, SHA, dirty/clean state and outcomes are retained separately
under `.local/qa/wave7-integration/e6-reference-p2/`:

```sh
python tools/dev/wave4_node.py tests/acceptance/wave7/cdp.test.mjs tests/acceptance/wave7/keyboard.test.mjs tests/acceptance/wave7/reference_assertions.test.mjs
python -B -m unittest tests.acceptance.wave7.test_target -v
python tests/acceptance/wave7/run.py --suite workflow-service
python tests/acceptance/wave7/run.py --suite browser-baseline
python tests/acceptance/wave7/run.py --suite browser
```

DB commands use only newly created task-owned disposable PG17/18 services, the
existing E6-prefix target/write guards, and the accepted unchanged test runner.
The final handoff reports fresh targeted results on the local patch commit.
Earlier full C6/D6/B6/importer results remain attributed to `8d0ff3e…`; they are
not relabeled as execution on this later SHA.

Protected Chromium is still blocked by the Cloud SUID sandbox configuration.
Baseline four plus persisted eight browser cases remain NOT_RUN; HTTP/asset
preflight is not acceptance. No sandbox setting or flag is changed. E4 internal
patch review remains pending. Windows/GitHub CI, real-source checks and fresh
independent assembled review remain NOT_RUN. No push, PR or metadata update.
`NOT_DEPLOYED / GATES_HOLD / USAGE_NOT_OBSERVED`.
