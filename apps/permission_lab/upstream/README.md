# Pinned S3 inert documentation contracts

These five vendored files are byte-exact copies from local Git commit
`88c411852d1a90e62ec71ab1c9ae2278f72d0c76`, originally available at
`origin/codex/s3-contract-validators-20261013`. `manifest.json` records each
original path, vendored filename, and exact SHA256. Runtime code does not use
Git, the remote ref, the network, or the manifest to select executable code.
`../sources.py` uses fixed filenames and independently embedded digest pins.

| Original path | SHA256 |
| --- | --- |
| `contracts/__init__.py` | `ae35be2a0ae110ebaaddd5e58f770d1002a20a22e6df4e3185d9c8dc55f13c81` |
| `contracts/validator.py` | `847118024daec38656a2829402af8cd8a2e7866b99ced3e382ad190538796834` |
| `contracts/inventory.schema.json` | `c0c64ab3454a9d6d4a153b9e7815aa91c7c842b7c07f0c6135f95966df7a3712` |
| `tests/contracts/fixtures/synthetic_inventory.json` | `40df94e24af7d64b4fac4285000aa928282ac25f2110b07dce055d2994820dd4` |
| `tests/contracts/fixtures/synthetic_review_excerpt.json` | `266e07ae6b229a19df2d11b8a9aa986e9cd468a05ecacfd7d22de3ebdd7b760d` |

The actual inventory has **four invented synthetic actions and one synthetic
transition**. The original 70 historical permission rows, 58 historical workflow
transitions, original reviewed sources, and detailed U03/U10 clauses are absent.
They have not been reconstructed. Expected historical totals in the validator
are completeness requirements only: 70 actions (37 DOMAIN_STATE, 33 UI;
55 UNMAPPED_HOLD, 15 MAPPED_DRAFT) and 58 transitions.

The two P00-03 effect identifiers exercise known inert-effect rules using invented
fixture content; their presence does not establish original-record acceptance.
Candidate principals are metadata, never grants. The loader reuses the original
`inspect_structure(..., synthetic=True)` implementation and verifies all bundled
input/schema/validator bytes. It provides no caller-supplied path or policy input.

Validation cannot approve U03/U10 or permit a product operation. Every supplied
action remains DENY_DEFAULT, NONE_CANDIDATE_BINDING_ONLY, non-callable, and
grant_effect NONE; every transition remains disabled. Gate B NOT_PASSED,
Gates C/D/E HOLD, Phase01 BLOCKED, AI DISABLED. NOT_DEPLOYED / GATES_HOLD.

The historical S3 evidence did not establish a passing Python validator suite:
its Python runtime was unavailable. New FAST5 source-loader test results must be
reported separately and must not be presented as historical source acceptance.
