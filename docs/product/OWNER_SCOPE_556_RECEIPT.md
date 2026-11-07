# Optional verification of the original owner scope

A reviewer with the six original local files can run this read-only check using Python 3.13 and the standard library. Run from the repository root, replacing the final argument with their common directory.

```sh
python -B tools/feature_registry/verify_owner_scope.py /path/to/owner-inputs
python -B tools/feature_registry/tests/check_owner_scope_negatives.py /path/to/owner-inputs
```

The directory must contain the following privately supplied originals under the specified local names.

- `542.docx`
- `requirements.jsonl`
- `PRODUCT_SPEC.txt`
- `INDEPENDENT_RECONCILIATION_DELIVERY_MANIFEST.json`
- `ORIGINAL_556_TO_479_SEMANTIC_VERIFIED.json`
- `CURRENT_479_TO_556_REVERSE_SEMANTIC_VERIFIED.json`

The verifier pins the byte-level SHA-256 of the first four files. The pinned manifest supplies the size and SHA-256 of each mapping report. The verifier reads numbered body paragraphs and examples from the DOCX and reconstructs clause text from the original specification line spans. It compares the two mapping directions, including the distinction between selected evidence and additional refinements. Standard output contains counts and the scope of the verification. Missing or modified originals cause a nonzero exit. The negative checks alter a temporary copy or in-memory records. Private inputs stay outside Git and CI.

## Documentary receipt for the October 10 reconciliation

| Measurement | Verified count |
|---|---:|
| Distinct numbered paragraphs in the original DOCX | 556 |
| Original points / D-062 appendix points | 542 / 14 |
| Additional unnumbered examples | 7 |
| Clauses in the secondary specification registry | 479 |
| Selected forward links / additional reverse refinements | 824 / 1,246 |
| Exact / composite documentary coverage | 299 / 183 |
| Partial coverage / owner-approval pending / superseded points | 38 / 33 / 3 |

These are the dispositions recorded in the historical reconciliation. Decisions taken afterward, including D-072, are applied separately to release scope. The receipt grants no owner approval, makes no claim about implementation, and runs no product or gate acceptance tests.
