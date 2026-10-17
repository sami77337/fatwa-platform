# Actual producer hooks and mandatory persisted-browser journeys

Pinned published code read for this increment:

- E1 final2678b91a7c7f2e210a7585e6997725432782aa72.
- E2 PR61 b55c4596506aafd3c3d5c3a3c0fee1450fc2d2c2.
- E3 PR60 5f4e66facfb672e610faed9cb7d154bed44c9510.
- E6 base remains accepted foundation34355; no producer cherry-picks, schema,
  shared setting, URL or production edits on the E6 branch.

The --input regression passed 1/1 against final E1. The previous c4adc40 failure
is historical and resolved; it is not a current defect/rework request.

## Service scenario and evidence boundaries

The actual adapter creates two eight-row batches from controlled derived shared
synthetic input; exact original bytes/slices are preserved by E1. No source
float JSON rewrite. It seeds only the shared fixed catalog outside other units,
then calls import_intake, verifies same-key replay/no duplicates, changed bytes
409/no mutation, cross-batch repeated external-ID isolation, and E3 verification
after intake commits. Reference state is read from current IntakeReference/DTO,
not E1's historical validation_results. UNVERIFIED references have no citation.

Actual E2 calls perform four allowed transitions with persisted events, exact old
operation replay after later transitions, and conflicting operation409. Actual
read DTO is checked for eight retained rows, exact questions, current E3 citation
state and separate review state/events. New Python processes replay the original
E1 bytes again (no duplicate records) and inspect the same persisted originals.
There is no outer atomic around producer services.

The E6 service scenario was exercised in a temporary code-components snapshot:
full E1 final tree, only published E2 service/command/view/template paths and E3
references.py overlaid, plus the owned E6 tests. No shared settings/routes patch
or E6 test URLconf was added. This is a pinned component-validation vector, not
an authoritative integration branch or a claim about final combined SHA/CI.
The producer's own temporary combined tests are not counted as independent E6
test cases. Current E6 collection is two named methods per PostgreSQL version.

Initial E6 scenario in that pinned vector passed one method per version. Final
collection after actual E2 read DTO assertions and the separate race-process
test: **2 PASS on PG17.11 and 2 PASS on PG18.6**, zero FAIL/SKIP. Concurrent
child processes returned exactly one success and one REVIEW_CONFLICT409; the
row retained one IN_REVIEW event. The full browser wrapper collected one
method and FAILED with E5_REVIEW_READ_OPT_IN_NOT_REGISTERED before intake;
all eight browser cases are NOT_RUN. This is a missing shared integration flag,
not a waived acceptance result. No root/E5 file was changed to bypass it.

## True browser gate

The full gate now requires registered wave7_editorial_review at
/dev/editorial-preview/persisted plus WAVE7_REVIEW_READ_ENABLED=True. E5 owns
both registration and separate default-off Wave7 setting; E6 does not invent
or override them. Missing modules/registration/flag fails closed before intake.

persisted_browser.mjs has eight actual engine cases using published PR61 native
controls and actual UUID GET links:

1. Desktop batch switching and same external ID, exact original text.
2. Filter/page/detail/return/back/forward/reload preservation.
3. Blocked/null rows, missing/invalid media and UNVERIFIED refs without citations.
4. Current reference verification, intake readiness and internal review/events.
5. Same-key replay in new processes; two concurrent review service processes,
   one success/one409; actual persisted event counts/state after reload.
6. 390/320 mobile native Enter search/detail/return and overflow checks.
7. Empty/error/back recovery and competing navigations retain the correct batch.
8. Console/runtime/GET-only/same-origin/no-media audit.

All writes run through actual Python services in parent/child processes, never
HTTP. Assets are checked by actual StaticLiveServer and preflight200/MIME/exact
bytes (five catalog files plus editorial stylesheet). Native Enter uses the
corrected transport helper. No DOM substitute/HTML overlay qualifies as browser
acceptance. Cases/screenshots remain NOT_RUN until actual protected-engine use.

E5 runner commands, using a separate E6-owned PG target with fixed role/marker:

```sh
python tests/acceptance/wave7/run.py --suite workflow-service
E6_WAVE7_ARTIFACTS=/tmp/e6-wave7-persisted python tests/acceptance/wave7/run.py --suite browser
```

Collect scenario.json/workflow-result.json even on failure. A missing E5 read
route or the known Cloud SUID sandbox blocker is never waived into PASS. Final
combined E4 search behavior, complete CI and protected browser remain required.
No approval/production/source acceptance is inferred from this increment.
