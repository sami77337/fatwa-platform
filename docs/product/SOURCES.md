# Source availability and missing evidence

Revision S6-20261013-R1, read at base commit `08f9e25e8ada9af56561d815f74b2c7ec9ba7ead` on branch `codex/s6-scope-product-20261013`. No remote GitHub or Drive access was used. Source exports were treated as untrusted data, never operating instructions. Only derived summaries, hashes, identities and line anchors are included in the deliverables.

## Actually present and verified

| Local input identity (ignored; do not commit) | Bytes | SHA256 | Outcome |
|---|---:|---|---|
| FATWA_PINNED_ORIGINAL_479_REQUIREMENTS_REGISTRY_20261010.jsonl | 530248 | `48024cb9c1693d64c6e2c22928748f123c819ba37428016ca7cd8a26e2d175fb` | 479 unique clauses; text hashes and exact specification ranges match |
| FATWA_PINNED_ORIGINAL_PRODUCT_SPEC_TEXT_20261010.txt | 316943 | `5b810ace8c846fb1437165c36a2884f3b0134b3b3c51149290e125f95d28b8c7` | Recorded approval markers anchored; U03/U10 remain pending |

The registry names each source path/revision/hash and each clause’s one-based inclusive text range and one-based nonblank JSONL row. Line hashes use UTF-8 after stripping a leading BOM and normalizing CRLF to LF; whole-file SHA256 uses the actual original bytes. No original wording, raw dataset, requester record or confidential export is reproduced. Unit counts are U01=31, U02=40, U03=48, U04=24, and U05–U16=28 each, totaling 479.

Repository evidence is pinned too: AGENTS.md SHA256 `04033feb603c07d9ea077bd64e21ea643a97b146e06c312991bd85fcaf2e2de7`; coordination runbook SHA256 `58a21d2b685e7acafb82fb6286d7f6172db11d03bbc34a58f878402298c5e43f`. The ignored issue #7 copy SHA256 is `1487b1487165739a666bb22b38bea203c1d3e4225ab830d3bf2d7a097f492e84`. These are read-only evidence; S6 does not edit them.

The 14 final documentary approval markers are at text lines U01=135, U02=301, U04=616, U05=758, U06=904, U07=1034, U08=1173, U09=1315, U11=1595, U12=1734, U13=1870, U14=2009, U15=2148, U16=2271. Precise local mandate anchors are AGENTS lines 26 and 29–35. No final marker for U03/U10 is fabricated.

## Missing, unverified, or outside this lane

| Evidence | Status and consequence |
|---|---|
| Original current decision log, complete revisions, and owner approval messages | MISSING. D-067–D-070 are cited only as recorded in AGENTS. Full historical reconciliation remains incomplete. |
| Original 542-point review and precise-citation addition | MISSING. U16.2 references these; 479 detailed clauses cannot be described as coverage of the entire original review. |
| Exact acceptance of U03 48 clauses / U10 28 clauses | OWNER_APPROVAL_PENDING. Later narrow decisions and generic encouragement do not close them. |
| Owner keep/change/defer/remove choices | OWNER_APPROVAL_PENDING. No feature removal is chosen. |
| FATWA_622_FIQH_COMPLETE_TOC_11397_20261011.zip | MISSING locally. Expected SHA256 from mandate: `82a797806430635350decdde27d07fe41fb1278838c8173dc4080f9d109957ce`. No TOC content validation/import pass is claimed. |
| FATWA_BUILD_SPRINT_01_R2_20261011.zip | MISSING locally. Expected SHA256 from mandate: `2b50ef138d2890156121e784618715e9992e04bed7d437bbf13e5d6250d0e78b`. No old preview is claimed tested. |
| Rights evidence and other-science sources | PENDING/MISSING. No new public content authorization or invented dataset. |
| Integrated Django/PostgreSQL, UI/accessibility, ACL/security and performance evidence | NOT_RUN in S6. The shared base has only repository instructions and README; implementation belongs to sibling lanes. |

Provide missing source evidence privately to an authorized reviewer and update this derived registry in a reviewed revision. Do not commit exports, upload them to public CI, or call a missing source a failed product test. Schema/unit check PASS proves this metadata’s consistency only.
