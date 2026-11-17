# V6 scope trace — 17 November 2026

Development receipt only: `Gate B NOT_PASSED / C-D-E HOLD / Phase01 BLOCKED / NOT_DEPLOYED`.
No release acceptance or maturity percentage is assigned here.

## Source and revision boundary

- Owner scope: [Fatwa_Platform_Scope_556.xlsx](https://chatgpt.com/library?file_id=libfile_9f712fdb7cd4819196e96b8b653de4ce&account_id=personal), current contents read on 17 November; 556 owner points and 479 specification clauses are different, many-to-many registers.
- Current execution authority: [FATWA_WORK_EXECUTION_ORDER_V6_2026-11-17(1).md](https://chatgpt.com/library?file_id=libfile_c46643bea1b881919f4d9f7382344c27&account_id=personal).
- [MASTER](https://docs.google.com/document/d/1QL3kumqm0Y_NzLUc00GYpU1TxhnbCwBfg2gNbUKwzF4/edit) and [DECISIONS](https://docs.google.com/document/d/1IoGNeCbB8dtMuGZ-BuvlInifmfaHbRos18OF1YUCN2Y/edit): D-048/049/050/055 govern evidence, access and cases; D-058/071 permit isolated parallel development; D-070 defers final design; D-072 defers U10, not D-068 citation assistance.
- Pinned base: `23839110af15baf09ed80b1002a328021cea5e31` (#208). Recovery source heads are pinned in `docs/operations/V6_CASEWORK_INTEGRATION_20261117.md`; the Draft PR supplies the published combined head.
- `VERIFIED_CODE` below means the bounded implementation was inspected and covered by the local checks listed below. `VERIFIED_INTEGRATION` requires the published combined SHA and its CI results, recorded in the Draft PR. `NOT_RUN` identifies missing execution evidence. Every row remains `ACCEPTANCE_HOLD`.

## Change-to-scope mapping

All clause IDs below have the prefix `SPEC-`. A row records progress on a requirement, not completion of its entire unit.

| Bounded behavior | Owner points | Clauses | Evidence / state |
|---|---|---|---|
| Staff phrase search equates whole-word بلا/بدون on a temporary copy | 35, 192, 219–222 | U05-007 | #183 recovery: `apps/editorial_workbench/search_terms.py`; `VERIFIED_CODE` |
| Editorial synonym recall preserves original fields and shared title normalization | 35, 192, 219–222 | U05-007 | #185 recovery: `apps/editorial_search/query_terms.py`, services and preservation tests; `VERIFIED_CODE` |
| Full normalized-field matches precede word matches, then synonyms; UI names the actual match kind | 218, 219, 231, 232, 449 | U05-006, U05-013 | Search services/template and regression tests; `VERIFIED_CODE`; no strict phrase-search mode claimed |
| Synthetic relevance evaluation measures known fixture identities without counting repeated identities | 242–246 | U05-027 | `tests/editorial_search/evaluate_relevance.py`; `VERIFIED_CODE`; specialist benchmark remains open |
| Canonical/OG URLs derive only from configured HTTPS origin, without request-host/query input | 456–458 | U09-024 | #173 recovery: public-site views/template/tests; `VERIFIED_CODE`; no production origin configured |
| Search/filter/error pages omit share metadata and request noindex | 456, 458 | U09-024 | `tests/public_site/test_share_metadata.py`; `VERIFIED_CODE`; this does not establish requester authorization or complete owner point 462 |
| Website intake persists original event before processing | 19, 21, 532 | U01-001, U01-002, U16-003 | Implemented `apps/casework` + `apps/casework_web`; `VERIFIED_CODE` |
| Duplicate intake returns the existing case; mismatched retries fail | 23 | U01-003 | Implemented transaction/idempotency tests; `VERIFIED_CODE` |
| Durable multi-case identity with public reference distinct from internal PK | 26–28, 434, 532 | U01-005 | Implemented Case model and one-to-one tracking binding; `VERIFIED_CODE` |
| Literal original question and original source remain immutable | 22, 32–34, 435 | U01-004, U01-006 | Implemented source model/database guards; `VERIFIED_CODE` |
| Followups remain within one case and preserve chronology | 29–31, 37, 38, 184, 434 | U01-009, U01-010 | Implemented evidence/events linkage; `VERIFIED_CODE` |
| New facts increment evidence version and block stale approval | 43–46, 105, 436 | U01-012, U01-013, U02-010 | Implemented stale-evidence and approval invalidation tests; `VERIFIED_CODE` |
| Staff sees original question, drafts and clarification cycle | 48–51, 39, 40, 69, 81 | U01-015, U01-017, U01-026, U02-006, U02-011 | Implemented human-authored text journey; `VERIFIED_CODE`; media is wider scope |
| Only a scoped MUFTI can create/approve a substantive answer | 2, 11, 83–85, 402 | U01-018, U14-010 | Implemented trusted identity and role-confusion tests; `VERIFIED_CODE` |
| Case/answer/evidence association rejects orphan or cross-case writes | 444, 445 | U16-005, U02-018 | Implemented FK/Unique/Check, locks and optimistic concurrency; `VERIFIED_CODE` |
| Transactions survive duplicate intake, racing updates and rollback | 23, 444, 445 | U01-003, U16-005, U02-018 | Implemented PG17/18 tests; `VERIFIED_CODE` |
| Receipt/reference appears only after durable save | 147, 503 | U08-008 | Implemented website intake HTTP/browser tests; `VERIFIED_CODE` |
| Capability authorizes one case; FT reference alone cannot authorize access | 145, 148–150 | U08-010 | Implemented token/cross-case tests; `VERIFIED_CODE` |
| Trusted recovery rotates/revokes access without deleting the case | 148–150 | U08-022, U08-023 | Implemented recovery/revocation tests; `VERIFIED_CODE`; production recovery policy remains open |
| Requester status follows operational truth without internal drafts, identities or logs | 151, 152 | U08-012, U08-013 | Implemented source-linked projection and mismatch rejection; `VERIFIED_CODE` |
| Followup correction appends evidence without overwriting original facts | 32, 37, 44–46 | U08-015 | Implemented requester followup tests; `VERIFIED_CODE` |
| POST/CSRF, no-store, noindex, bounded attempts, no cross-case disclosure | 148–150, 412, 462 | U08-010, U08-027, U09-024 | Implemented loopback-only HTTP boundary; `VERIFIED_CODE`; noindex is not authorization |
| Accepted, reported delivery, verified receipt and reading remain distinct | 129, 130, 151, 505 | U01-025, U07-012, U08-019 | Affected legacy receipt regressions passed; canonical case status is conservative. New signed-evidence binding remains `ACCEPTANCE_HOLD`, not implemented; no external sending |
| Audit records actor, action and time; default-deny and no self-escalation | 403, 404, 408, 415, 416 | U14-015, U14-011, U14-019 | Implemented case events/identity controls; `VERIFIED_CODE`; historical permissions grant nothing |
| Final combined revision has PG17/18 and desktop/mobile Chrome evidence | 54, 454 | U02-037, U09-022, U16-020, U16-026 | Final-SHA CI/browser receipt pending; `NOT_RUN` |

## Acceptance limits

The recovered dictionary is deliberately small; standalone دون is not equated with بلا. U05-027 still requires specialist evaluation of the actual dictionary and normalization rules. Fixture results do not establish full Arabic search quality.

Token lifetimes, recovery verification, rate thresholds and session policies remain development parameters under U08-022/023/028. A text-only synthetic journey does not complete attachments, audio, answer delivery or the full requester unit. In particular, U08-013 forbids saying an answer is available before it is accessible; U08-019 does not treat page access as proof of reading.

U16-027 requires release-specific acceptance and forbids counting disabled, untested functionality as complete. The workbook's acceptance receipts remain unproven. The inherited 47% estimate is not recomputed, and neither CI success nor this mapping upgrades a gate.

## Final integration evidence

Local preparation checks: 42 Arabic search tests; 45 public-page tests; 74 combined case/tracking tests on each of PostgreSQL 17.11 and 18.7 (51 casework + 23 affected legacy tests, not 148 distinct functions). Populated migration reversal/reapply preserved both cases and restored all 17 integrity triggers on both majors. Changed Python files passed Ruff.

Published-head CI and real Chrome evidence are pending at preparation; the Draft PR records their eventual exact SHA, counts, URLs and any failures. Local Chrome is NOT_RUN because startup sockets are unavailable in this executor. Do not infer browser success from HTTP or core tests, or apply earlier local results to a later SHA without an affected-scope check.
