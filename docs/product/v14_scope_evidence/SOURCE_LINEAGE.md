# Source lineage correction — attributed local evidence

The parent coordinator reported on 2026-11-18 that it verified the local
`V13_SOURCE_LINEAGE_ADDENDUM.md`. **The report and original bytes were not
transferred to this Cloud worktree; no independent Cloud execution is claimed.**
The following is a committed record of that trusted receipt, previously added
only to the V13 PR description. It corrects the current status without rewriting
V12/V13 historical evidence or failed downloads.

| Artifact | Parent-local result |
|---|---|
| [542.docx, authorized Drive](https://drive.google.com/file/d/1nFIFspA7OeIsccnwWGEMlfC2n_LPEdIQ/view) | 56,895 bytes; SHA-256 `436751386501bf53c6a7f39bb21ee1eec85e6d34f3326fe528cf38e6bc6c80ff`; matches historical identity |
| Derived reference XLSX | 211,695 bytes; 8 sheets; SHA-256 `874326f71ded93a1a4ccb11a9038429a8f604d1e9e23acef7e8c52327b42969e` |
| Registry of 479 specifications | 530,248 bytes; SHA-256 `48024cb9c1693d64c6e2c22928748f123c819ba37428016ca7cd8a26e2d175fb` |
| Pinned extracted text | 316,943 bytes; SHA-256 `5b810ace8c846fb1437165c36a2884f3b0134b3b3c51149290e125f95d28b8c7` |
| Historical matching XLSX | 384,127 bytes; 5 sheets; a different artifact from the derived reference XLSX |

The reported local result has SHA-256
`a930cf91421eb6ad232bbccc75a1c6ffa012bdcc39dcdeedb28fecfbdcf3531b`.
These are **reported** artifact/result hashes; this lane did not calculate them
from original bytes or from the local report file.

All 556 numbered texts and actual Word positions reportedly match the V12 matrix
and then the reference workbook. The registry's IDs, paragraphs, titles, units and
order match; the pinned text's line spans and fingerprints match. The compared
V12 matrix is pinned at `5ec6373f5eaf3cd5ea2b14d7b3e7119826ceb4c8`.
The DOCX status is now **SOURCE_BYTES_VERIFIED_LOCALLY_BY_PARENT**. Earlier V13
“DOCX UNVERIFIED” wording is retained as historical evidence, not current global
status. The legacy matrix field `source_word_paragraph_unverified` is preserved
verbatim for reproducibility; the new V14 layer records the later attributed match.
It does not assert that this Cloud worker inspected the Word locator.

The transformation chain between the historical 5-sheet workbook and reference
8-sheet workbook was **NOT REPRODUCED**. Matching identities and text does not
establish authorship, semantic approval, owner acceptance or rights to publish.
The reference workbook remains a derived artifact, not proof of authoring provenance.

The 17 serialization differences at `المراجع والقرارات!C5:C21` remain: OOXML
`t=d` ISO8601 with `Z` versus extracted space separator, six fractional digits
and omitted UTC suffix. Temporal components match by the local receipt; whole
strings/whole-workbook bytes are not equal. Nine formula cells were checked by
saved values only, without recalculation or visual comparison. Earlier reported
reference-workbook row rule `parsed_index + 2` remains an attributed rule, not
Cloud parsing (point 1 row 5; point 556 row 560).

No original DOCX, XLSX or other source binary is uploaded in this change.
[Machine-readable receipt](source_lineage.json) keeps the reporting environment,
negative claims and exact identities separate from product execution evidence.
