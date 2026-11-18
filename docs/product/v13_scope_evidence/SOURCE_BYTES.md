# Original XLSX — verified in the parent's environment, not this Cloud

Source: the integrator relayed the parent's P0-A independent matching receipt on
2026-11-18. This lane did not receive original XLSX bytes or execute its validator.
The original must not enter the repository. Prior V12 download failures remain
historical evidence; this later receipt changes global availability, not that history.

| Field | Parent-reported result |
|---|---|
| Original | `Fatwa_Platform_Scope_556.xlsx`, 211695 bytes |
| Original SHA-256 | `874326f71ded93a1a4ccb11a9038429a8f604d1e9e23acef7e8c52327b42969e` |
| Parent status | `SOURCE_BYTES_VERIFIED_LOCALLY` in the parent environment only |
| This Cloud/worktree | `SOURCE_BYTES_UNAVAILABLE`, no local original-byte verification |
| Scope | 8 sheets; 11289 values and52 headers;556 owner points;479 SPEC clauses |
| Compared extraction/matrix | `5ec6373f5eaf3cd5ea2b14d7b3e7119826ceb4c8`; point/SPEC text/order and matrix/specification fields matched |
| Independent results | Two local results with the same reported digest `a73978ac0c72b20c982b72f35b49ab803f5b53b4bd2ddd542f68b6010f321a15` |
| Stdlib validator | Reported digest `8cad3eb213d74234a84daa83478c8f1ba1551d7a1ef9722c81d4120b1b7f4bd3` |

There are **17 serialization differences**, not whole-workbook string equality:
`المراجع والقرارات!C5:C21` uses OOXML `t=d` ISO8601Z versus the extraction's
space separator, six fractional digits and omitted UTC suffix. Time components
match according to the independent receipt; the representation difference is retained.

The attested original Excel row equals `parsed_index + 2`: original point1 is row5,
point556 is row560. `matrix.json` leaves historical `source_locator.parsed_index`
unchanged and adds `v13.attested_original_excel_row` with
`excel_row_basis=PARENT_LOCAL_ATTESTATION`; it never labels this as local parsing.

Nine formula cells were compared by their **saved values only**. No recalculation,
visual workbook comparison, hidden-cell completeness claim, or original Word-byte
validation is inferred. The result/validator hashes above were relayed, not computed
from result/validator files by this lane. Extracted-text hashes remain distinct from
the original XLSX hash. See machine-readable provenance in `source_bytes.json`.
