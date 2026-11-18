# V13 bounded functional evidence update

**Current security suspension — SEC13-01.** The external review at
`97dd5793e44118d8cd050607717a6acb555f0f1c` is **BLOCKED** on product
`38cd137db50cc95ae53fa275b5d90b8274096e5d`. Its affected recovery implementation
is identical tocd22cbd (`git diff` of `apps/platform_recovery/service.py` is empty).
Canonical-schema regex normalization rewrites quoted SQL data, causing different
real partial-index predicates to share a fingerprint; an encrypted restored target
with that altered predicate incorrectly reaches READY. Both reproductions fail
on PG17.12 and18.7 in the external review. No encryption/signature bypass or
unauthenticated SQL access is inferred.

The **connected-recovery group is SUSPENDED_SECURITY**. Four unaffected bounded
groups now attach evidence to27 selected points; prior38-point attribution and
successful receipts are retained in `suspended_recovery_evidence.json` and git
history, not erased or treated as current recovery verification. Original556
classifications remain unchanged. Green CI cannot override this blocker. Repair
and independent re-review are required before restoring the affected credit.
The external reviewer's protected browser attempt had an **ENVIRONMENT ERROR
before page creation**, not a local browser PASS. No product tests were rerun by
this scope-evidence lane.

The following execution figures are historical facts, with recovery credit
suspended as stated above.

Tested product: **`cd22cbd265db4b57124a1f091a041fd5200637b8`**. The later commit
containing this document is an evidence update, not an additional product run.
The initial update added five groups to38 points before SEC13-01; all556
baseline texts, SPEC/source/decision fields, classifications and historical
P0/P1 evidence remain unchanged:303 PARTIAL,52 DECISION,168 NOT_IMPLEMENTED,
33 OUT_OF_SCOPE,0 COMPLETE. These are retained classifications, not a new progress
estimate or acceptance verdict.

| Group | Explicit points receiving bounded evidence | Important limit |
|---|---|---|
| Browser audio | 25,36,44,46,70,75,77,78,81,82,533 | Synthetic explicit microphone permission and native save; PCM mono8000Hz up to10sec; no resume, ASR, real audio or all-device guarantee |
| Timed citations | 179,346,543,549,551,552,554,556 | Exact private audio version/hash/time and human confirmation; no public timed locator, print/export or automatic migration |
| Measured Arabic search | 216,221,231,242,245,246 | First20 authorized TOC metadata candidates; synthetic baseline/after, not full text, whole corpus, semantic or human-reviewed gold |
| Human classification | 47,417 | Private experimental proposal/review ledger and unchanged Evidence; not primary/additional taxonomy, official Tags or mutation of publication category |
| Connected recovery — SUSPENDED_SECURITY | Previously30,43,44,46,75,76,82,406,408,414,415,419,425,434,435; no current credit from this group | Historical run preserved, but SEC13-01 invalidates claimed schema-integrity verification until repair/re-review |

Wide requirements receive only the bounded evidence described in
[EVIDENCE.md](EVIDENCE.md), with exact code and positive/negative test symbols.
For example543 does not prove editor phrase selection,556 does not prove printed
references, and533 does not authorize every case or U03. Points161/162/164/169/170,
219,243/244,423/424 and432 are deliberately not credited by these new slices.
Book622 is a TOC only. No acceptance or status upgrade follows from a new partial
observation against a historically NOT_IMPLEMENTED point.

## Independently fetched hosted results

Run[44222224904](https://github.com/sami77337/fatwa-platform/actions/runs/44222224904)
job metadata and decoded logs were fetched independently; minimal excerpts are
preserved under `receipts/`. Every credited test passed on both actual majors at
the exact product SHA; the validator checks the method names, SHA and observed
PostgreSQL versions rather than trusting a label.

| Actual server | Affected tests | Protected connected Chrome | Job |
|---|---|---|---|
| PostgreSQL17.12 | 91 PASS,61.910s | 1 PASS,264.227s | [134526633973](https://github.com/sami77337/fatwa-platform/actions/runs/44222224904/job/134526633973) |
| PostgreSQL18.7 | 91 PASS,49.869s | 1 PASS,220.447s | [134526634232](https://github.com/sami77337/fatwa-platform/actions/runs/44222224904/job/134526634232) |

Both actual proofs report Chrome157.0.8103.50, sandbox=true,320/1280 widths,
one canonical case,3 attachments,5 Evidence versions,6 answer revisions,3 answer
parts and2 timed citations. Delivery preserves DELIVERED / FAILED_REQUIRES_REVIEW /
SENT_UNCONFIRMED parts without re-sending. Source bindings and source review notes
are both0: this audio website journey is **not** proof of ambiguous Telegram or
YouTube intake review.

Both proofs record an independent PostgreSQL target READY, encrypted-only bundle,
separate test key, rejection of wrong key/hash before target creation, target
HTTP PASS, unchanged/FROZEN source and preserved partial delivery. The connected
test and its target helper verify restored question/answer/audio/file bytes and
current grants, then deny access after revocation. There are0 external requests
and0 page errors. Test identities/verifiers are explicitly rebound to the target;
no old sender or source application is resumed. This proves a synthetic drill,
not production PITR, managed KMS, privileged-SQL protection or a delivery/read
claim from merely opening a page. Maintenance and unknown-target manual
quarantine requirements remain in force.

## Failure history and review boundaries

- `1ea53ea`:84 affected plus protected browser PASS per major, but independent
  review reproduced late-policy-callback identity/CITE revocation leaks. These
  successful logs are historical only and cannot credit the affected groups.
- `8eb1d76`: first fix retained one failing late-CITE probe on PG17; PG18 was not
  rerun at that intermediate revision. The full failure account is retained in
  the independent report rather than hidden by later green CI.
- `4f71d2e`: second fix received7/7 focused independent tests on both majors,
  then2/2 stronger attack-executed assertions per major. The supplemental static
  read at09cc55aa found no further concrete blocker in the four new apps.
- `09cc55aa`: PG18 passed91 affected tests and protected browser; PG17 failed the
  Node startup diagnostic before product/browser execution (1ms remainder versus
  expected0). It cannot supply a paired-major final receipt. The later diagnostic
  fix kept a single deadline and added deterministic1ms/2ms boundary coverage.
- `cd22cbd`: V13's paired-major run succeeds. Overall commit workflows are
  **15 success /1 failure** when inspected: FAST9
  [44222225041](https://github.com/sami77337/fatwa-platform/actions/runs/44222225041)
  failed before browser launch. Its root cause remains UNKNOWN; neither green
  V13 nor the diagnostic change is proof that FAST9 has been resolved.

Read the [independent bounded integration review](https://github.com/sami77337/fatwa-platform/blob/cd22cbd265db4b57124a1f091a041fd5200637b8/docs/security/V13_INTEGRATION_REVIEW.md).
It does not replace the designated external full V13 application review, which
now reports **BLOCKED — SEC13-01** in the
[external report](https://github.com/sami77337/fatwa-platform/blob/97dd5793e44118d8cd050607717a6acb555f0f1c/docs/security/V13_REVIEW.md).
That later review supersedes the earlier pending state without erasing the
bounded internal review's historical results. Original D6 root cause remains ROOT_CAUSE_UNKNOWN;
passing lifecycle diagnostics does not prove its historical cause.

The derived reference workbook matching receipt establishes fidelity to the
identified XLSX only, not authoring provenance. Parent-local matching and its17
date-serialization differences are retained in[SOURCE_BYTES.md](SOURCE_BYTES.md);
`542.docx` bytes remain UNVERIFIED here/pending separate proof. Main protection
remains UNKNOWN after the earlier Forbidden response; recommendations only.

**Gate B NOT_PASSED; C/D/E HOLD; Phase01 BLOCKED; NOT_DEPLOYED.** No new percentage,
official acceptance, real send, production data/keys, unapproved U03, automated
fatwa approval, Meta contract assumption or GitHub settings change.
