# FAST5 transcript validation

Validation date: 2026-10-25. Runtime: Python 3.13.17; Ruff 0.17.0.
FAST4 base: `262fa3d40975cfc0698b045becc2da885760a995`.
Branch: `codex/20261025-fast5-transcripts-pc2`.

## Executed checks

| Command (using Python 3.13) | Result |
|---|---|
| `python -m unittest discover -s tests/transcript_pipeline -v` | 23 passed |
| `python -m unittest discover -s tests/prepared_pipeline -v` | 79 passed |
| `python -m unittest discover -s tests/content_intake -v` | 54 passed |
| `python -m unittest discover -s tests/fatwa_drafts -v` | 38 passed |
| Ruff check and format check on all new Python files | passed |
| `git diff --check` | passed |

Total: 194 tests, no failures or skips in these suites. Early service/CLI test
runs failed because the implementation entry points did not yet exist, then
passed after implementation. The Windows `py -3.13` alias was unavailable;
the installed uv CPython 3.13.17 executable was used directly instead.

## Synthetic fixture identity and actual integration result

Input: `tools/transcript_pipeline/examples/synthetic-manual.json`.
This fixture was fabricated for development; it contains no recording, private
case, scholarly approval or source citation. LF bytes are pinned locally using
the owned directory's `.gitattributes`.

- Exact input SHA256: `e217c93eac5fa0109e3c4134b478ce3e6500e8723692312a6c14194ccece40ee`
- Canonical source SHA256: `5181128620c7e1a84e226540df48e2f5f1a712c66c48ca9dbebc8f778c1e9f0e`
- Report SHA256: `d252494ffc92bd35838ce539848e8ad2441e63c699399b18d5fdfa995f8552e2`
- Prepared export SHA256: `9c3e678856c05ff7c00bdcfddc9e7c55f72075f8e0c3bd276f2ddc8194580385`

Both real CLI modes were executed. The prepared bytes were passed to the existing
`apps.prepared_pipeline.prepare_batch(..., synthetic_fixtures_only=True)`.
Observed result: two transcript segments, one prepared question, zero drafts;
statuses `needs-editor-review` and `references-unverified`. Exact answers remain
in the transcript report because the existing preparation schema has no answer
field. No fake media links are generated.

## One independent final review

The independent read-only reviewer inspected the implementation, CLI, tests,
documentation and reused FAST4 contracts. They reran all 23 transcript tests and
probed malformed values in every input field. Result: ready for a draft PR,
no blocking correctness or safety findings. One nonblocking coverage gap remains:
direct symlink/junction rejection is implemented but not individually exercised
by the subprocess tests; UNC/device/drive-relative inputs and directories are.
No second independent review was performed.

## Limits and gates

These are offline service/CLI checks, not PostgreSQL, browser or original-corpus
acceptance. No models, migrations or routes changed. PostgreSQL and original
source ZIPs were neither required nor exercised. The synthetic declaration is a
caller attestation, not automated proof that data contains no real information.
Use trusted local directories; the CLI is not a filesystem sandbox.

No implementation blocker found in the executed checks. Existing product gates
remain: Gate B NOT_PASSED; C/D/E HOLD; Phase01 BLOCKED;
SCOPE_DEVIATION_HOLD; NOT_DEPLOYED. No merge, deployment or policy approval.
