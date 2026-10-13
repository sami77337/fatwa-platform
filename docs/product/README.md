# سجل نطاق المنتج — S6 / issue #7

**NON_PRODUCTION_DRAFT — NOT_DEPLOYED / GATES_HOLD.** Gate B is NOT_PASSED, C/D/E are HOLD, and Phase01 is BLOCKED. This document and registry grant no permissions and enable no product operations.

[feature_registry.json](feature_registry.json) contains **24 feature groups**: 16 product units with all **479 exact clause anchors**, plus eight later-decision/current-scope entries. It includes independently written summaries and **93 planned group acceptance criteria**, all NOT_RUN. The original text and raw JSONL export are not copied into this repository.

The two pinned originals were actually available locally under ignored `_codex_input`. Their whole-file SHA256 pins, 479 unique identities, exact specification line ranges, individual text hashes and recorded approval anchors were verified. See [SOURCES.md](SOURCES.md) and [S6_RESULT.md](S6_RESULT.md) for evidence and limitations.

## Reading the registry

Each feature records its source evidence IDs, precise revision, separate owner approval, dependencies, security sensitivity, suggested release slice, development scope, implementation status and acceptance criteria. Resolve an evidence ID through `evidence`, then its `source_id` through `sources`. Clause anchors also retain the original unit/number and JSONL index line. Source identity is S04 / `sources/04_product_spec.txt`; that historic path describes provenance, not a repository file to execute.

Every clause belongs to its exact unit group. Grouping provides a readable product inventory; it does not assert 479 independently designed tests or feature-level implementation. The 93 criteria cover representative positive/negative journeys and are **not exhaustive clause-by-clause acceptance tests**. Before dependent implementation, its task must name the exact clauses and add their specific acceptance cases.

| Classification | Meaning in this revision | Groups |
|---|---|---:|
| OWNER_APPROVED | A precise documentary unit approval or repository-recorded decision exists, within its stated scope | 16 |
| OWNER_APPROVAL_PENDING | Exact acceptance still needed: U03 48 clauses and U10 28 clauses | 2 |
| PROPOSED | Suggested release ordering awaiting exact choices | 1 |
| SUPERSEDED | Requires an explicit later replacement decision; none invented | 0 |
| DEFERRED | Later V1 citation assistance, V2 ChatGPT, other-science data, final design | 4 |
| OUT_OF_SCOPE | Current-sprint prohibited operations, not permanent owner deletion | 1 |
| IMPLEMENTED_VERIFIED | Requires actual implementation/test evidence; none exists here | 0 |
| UNKNOWN | Supported for missing evidence; owner acceptance is UNKNOWN on the proposed plan and current exclusions | 0 |

Classification and owner approval are different axes: a deferred decision may have a recorded approval while its development remains deferred. A proposed engineering plan does not have owner product acceptance. Source approval never implies implemented behavior, cleared gates or active permissions. Every activation is DISABLED, every implementation status is NOT_EVALUATED, and every product test status is NOT_RUN.

## Authority and later decisions

The supplied specification records exact approval markers dated 2026-10-07 for U01/U02/U04–U09/U11–U16 (403 clauses grouped by unit). These are **documentary records**, not an independently obtained approval conversation or live Drive revision. Earlier “for review” headers are retained in the ignored original; the exact final unit-status markers are the recorded approval evidence. U03 and U10 have no comparable final marker. The current issue and AGENTS mandate explicitly keep their 76 clauses pending. The JSONL `approval_record` label is not used to infer acceptance.

D-067 preserves equivalent MUFTI/ORGANIZER_ADMIN administrative hierarchy and configurable lower ORGANIZER access. Only MUFTI creates or approves substantive rulings. It neither accepts U03 nor binds the 70 historical DENY_DEFAULT/NONE_CANDIDATE_BINDING_ONLY rows. The 58 draft workflow transitions remain documentation; DOMAIN_TRANSACTION is not a runnable principal.

D-068 puts human-reviewed inline citation suggestions in later V1; external ChatGPT belongs to V2. AI fatwa writing/approval and AI/network calls in this sprint remain disabled. D-069 limits the current reference-data slice to book 622 fiqh metadata, one Hanbali reference index rather than a universal approved fatwa taxonomy or a fatwa corpus. Broader historical knowledge capabilities remain traced for later review; a narrow development slice does not remove them. D-070 puts final Figma and branding after owner-accepted functions.

Original D-067–D-070 decision-log revisions are missing locally. These entries cite the current repository mandate precisely and label that limited documentary basis. No new supersession, deletion, executive policy or owner approval is inferred.

## Review and integration contract

See [OWNER_DECISIONS_NEEDED.md](OWNER_DECISIONS_NEEDED.md) for exact pending decisions and [release slices](../release-plan/SLICES.md) for safe development vs blocked product work. S0/S1/S2/S4/S5 supply public-catalog implementation and evidence; S3 retains fail-closed policy documents. S6 supplies documentation and read-only validation only. No endpoint, migration, UI styling, user record, secret or external provider action is part of these changes.

Node 22+ standard-library commands are documented in [the validator README](../../tools/feature_registry/README.md). Default validation works without private exports and explicitly reports their verification NOT_RUN. The explicit local-source mode verifies the pinned originals, fails if requested files are missing, and prints metadata only. Source/version changes must receive a reviewed registry revision and updated pins; do not quietly bypass a mismatch.
