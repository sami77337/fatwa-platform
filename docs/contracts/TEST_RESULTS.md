# S3 validation evidence — 2026-10-13

Base commit: 08f9e25e8ada9af56561d815f74b2c7ec9ba7ead.
Branch: codex/s3-contract-validators-20261013.
Initial worktree: clean. Changes remain local and uncommitted.
Scope: issue #4 only. NOT_DEPLOYED / GATES_HOLD.

## Actual executable artifact tests

Runtime observed: node --version returned v24.16.0 (exit 0).
Command run from the repository root:

    node --test tests/contracts/test_artifacts.mjs

Actual exit code: 0. Actual test-runner summary:

    tests 8
    suites 0
    pass 8
    fail 0
    cancelled 0
    skipped 0
    todo 0
    duration_ms 53.6764

These tests parse the three JSON artifacts, verify closed object schemas, confirm
the small synthetic fixture identity, match exact SHA256 pins, check inert fixture
rows and effect metadata, match synthetic source record references, and check the
pending policy flags. They do not execute the Python validator or establish a
passing permission/workflow negative test suite. Their scope is artifact integrity.

The same eight integrity properties were also checked directly through Node
assertions before adding the reproducible test runner. No independent source
review, owner acceptance, or complete-inventory validation is claimed.

## Python test and CLI attempts: NOT_RUN

The authored unittest file contains 64 test methods, including subtests for the
requested negative cases: role escalation, shadow grants, service identity
impersonation, stale policy tokens, mutable historical answers, and callable parent
transaction effects. File/provenance and CLI cases are also authored.

The actual command attempted was:

    py -3.13 -B -m unittest discover -s tests/contracts -v

Actual exit code: 112. stdout was empty. stderr was:

    No installed Python found!

The actual missing-source CLI attempt was:

    py -3.13 -B -m contracts

Actual exit code: 112, with the same empty stdout and stderr. No JSON validator
report was produced. There were zero Python tests executed, zero claimed Python
passes, and zero claimed Python assertion failures. Both checks are NOT_RUN due
to the missing runtime; they are not passing expected negative tests.

The ordinary python executable was absent (ENOENT), and py -0p reported
No installed Pythons found! A temporary official Python 3.13.7 embeddable-runtime
fetch failed before any archive was written. WSL enumeration returned access denied
(Wsl/EnumerateDistros/Service/E_ACCESSDENIED). The Docker engine was unavailable.
No runtime was installed, and no shared dependency or system setting was changed.

The exec_command helper failed before starting processes with
helper_unknown_error: setup refresh had errors. Reads, owned-path writes, and
actual local process checks were performed through the available Node tool instead.

## Fixture identity and unavailable source

No owner-reviewed contract attachment, historical 70-row inventory, or 58-transition
source file was supplied. SOURCE_CONTRACT_MISSING is the code implemented for
missing inventories or missing originals. Current full-source acceptance is BLOCKED;
this is a source-availability finding, not an observed Python execution result.
The book-622 TOC and sprint ZIPs were not used and are not contract-validation
inputs. No 70/58 source inventory was reconstructed or fabricated.

The only data inputs are the following invented, explicitly SYNTHETIC files:

| File | SHA256 of actual bytes |
|---|---|
| tests/contracts/fixtures/synthetic_inventory.json | 40df94e24af7d64b4fac4285000aa928282ac25f2110b07dce055d2994820dd4 |
| tests/contracts/fixtures/synthetic_review_excerpt.json | 266e07ae6b229a19df2d11b8a9aa986e9cd468a05ecacfd7d22de3ebdd7b760d |

The inventory contains four actions and one transition. Its source document is a
small synthetic identity excerpt, not an approved record. Both synthetic hashes were
computed from exact bytes and matched by the successful Node artifact tests.

## Remaining checks and handoff

Python 3.13 syntax/import checks and all 64 Python test methods remain NOT_RUN.
The default missing-source and explicit synthetic Python CLI paths remain NOT_RUN.
Full reviewed-source validation, record-to-original content binding, and independent
source/policy acceptance remain BLOCKED or pending. PostgreSQL, Django checks,
migrations, application API checks, and deployment are outside S3 scope and NOT_RUN.
The source-mode positive path cannot be exercised without real reviewed source;
synthetic records are deliberately insufficient for source completeness.

Run the documented Python commands once a Python 3.13 runtime is available.
Supply actual reviewed records and independently pinned hashes before attempting
complete-source validation. Successful offline structure/hash validation still leaves
source acceptance false, runtime execution false, active grants zero, policies
pending, and all product gates unchanged.

Final ownership audit found 13 new files, all in contracts/**, tests/contracts/**,
or docs/contracts/**. git diff --exit-code returned 0: preexisting tracked files
were untouched. Branch and HEAD remained the exact values above. Node assertions
checked all 13 new files for trailing spaces/tabs and final newlines and passed.
git diff --check returned 0 for tracked changes; it does not cover untracked files.
The per-file git diff --no-index --check comparisons returned 1 for new-file
differences with no whitespace diagnostics, and only Git LF-to-CRLF warnings.
No Git configuration was changed. No commit, push, PR, merge, or deployment ran.

The exact local check metadata is also available in validation-evidence.json.


## Nesting error regression — 2026-10-14

Worktree: S3 only. Branch: codex/s3-contract-validators-20261013.
Checked-out HEAD: c3dc8e5da35fc5b23b4da6b4ac90df260993b3ac.
Initial git status --short was empty. This fix is local and uncommitted; no commit,
push, PR, merge, deployment, or other-worktree change was made.
The earlier evidence above and validation-evidence.json describe the original run
and are preserved. This section records the current regression-fix attempts.

Root cause: validate_inventory caught RecursionError from json.loads but had no
explicit JSON depth limit. If the interpreter decoded the 2,000 nested arrays, the
schema then rejected their top-level array type as SCHEMA_VIOLATION. That behavior
explains the reported Python 3.12 failure; it was not reproduced locally because
neither requested Python runtime is available. Python documents that JSON nesting
limits depend on interpreter limits, not on a fixed JSON-library bound:
[Python JSON implementation limits](https://docs.python.org/3.12/library/json.html#implementation-limitations).
The [CPython 3.12.10 C recursion limits](https://github.com/python/cpython/blob/v3.12.10/Include/cpython/pystate.h#L232-L254)
are build/platform dependent, and can exceed 2,000. A fixed input contract must not
rely on a parser's recursion threshold or on a Python-version-specific exception.

The fix adds an inclusive 64-container bound, enforced by an iterative scan after
strict UTF-8 decoding and before json.loads or schema inspection. Quoted brackets,
escaped quotes, and backslash parity are handled without building nested objects.
The scan uses linear time and at most 64 stack entries. Too-deep JSON uses the
existing sanitized INVALID_JSON error path. Schema, duplicate-key, constant, byte
size, hash, policy, and source validation remain in place. The original 2,000-level
test keeps its INVALID_JSON expectation and now checks exact codes, status, and
that no counts/source reads follow a depth rejection.

Eight new Python test methods cover array/object/mixed-container depth boundaries
(63/64/65), excessive nesting in known and unknown fields, sibling containers,
quoted brackets with Arabic text and escaped quotes/backslashes, backslashes before
a real closing quote followed by excessive nesting, malformed JSON, shallow schema
errors, and CLI INVALID_JSON/exit 2. There are 72 authored Python test methods.
They have not been executed in this environment; no Python passes are claimed.

Actual final commands and results, all from this S3 repository root:

| Command | Exit | Exact result |
|---|---:|---|
| py -3.12 -B -m unittest discover -s tests/contracts -v | 112 | stdout empty; stderr: No installed Python found! (CRLF) |
| py -3.13 -B -m unittest discover -s tests/contracts -v | 112 | stdout empty; stderr: No installed Python found! (CRLF) |
| node --test tests/contracts/test_artifacts.mjs | 0 | 8 tests, 8 pass, 0 fail, 0 cancelled, 0 skipped, 0 todo; duration_ms 51.6348; stderr empty |
| node --version | 0 | v24.16.0 |
| git diff --check | 0 | No whitespace diagnostics; Git emitted LF-to-CRLF informational warnings |

Both Python suite commands were also attempted before edits with the same exit 112
and message. Thus both Python suites are NOT_RUN (0 tests executed), not passing
runs and not assertion failures. Cross-version runtime verification and the original
reported failure reproduction remain outstanding. The eight passing Node tests
only check artifacts and do not substitute for the Python validator tests.

Runtime diagnostics: py -0p printed No installed Pythons found! with exit 0;
where.exe python, python3, and uv each returned exit 1. The two official portable
Python archive fetches (3.12.10 and 3.13.7) failed with fetch failed, cause EACCES;
no archive was written. Docker had no engine pipe (exit 1), and WSL enumeration
returned Wsl/EnumerateDistros/Service/E_ACCESSDENIED (exit 4294967295).
The exec_command and apply_patch helpers also failed; authorized local reads,
owned-path edits, and process checks used the Node tool. No installation or shared
configuration changes were made.

Input fixture identity is unchanged:

| File | SHA256 of actual bytes |
|---|---|
| tests/contracts/fixtures/synthetic_inventory.json | 40df94e24af7d64b4fac4285000aa928282ac25f2110b07dce055d2994820dd4 |
| tests/contracts/fixtures/synthetic_review_excerpt.json | 266e07ae6b229a19df2d11b8a9aa986e9cd468a05ecacfd7d22de3ebdd7b760d |

Only contracts/validator.py, tests/contracts/test_validator.py,
docs/contracts/README.md, and this evidence file changed. Original reviewed 70/58
source acceptance is still BLOCKED; no source acceptance or owner policy approval
is claimed. NOT_DEPLOYED / GATES_HOLD.
