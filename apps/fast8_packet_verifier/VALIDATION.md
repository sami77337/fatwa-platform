# FAST8 packet-verifier focused evidence

Reviewed base: `92fa517ecdefe3f1a92a1ab145ff55943474df44` (FAST7 guarded-CI
integration, Draft PR #134). Worktree branch:
`codex/20261026-fast8-packet-verifier-pc1`. PR target:
`codex/20261026-fast7-ci-integration-pc1`.

Local environment: Windows, Python 3.13.15, existing Ruff 0.17.0. No dependency
installation. Only built-in synthetic fixtures; no owner archives supplied or
opened. Exact final commit and remote CI results belong in the Draft PR because
a committed evidence file cannot contain its own commit hash.

## Commands and observed results

```text
python -B -m unittest discover -s tests/fast8_packet_verifier -v
25 tests; OK; 0 failures/errors/skips

python -B manage.py test tests.fast8_packet_verifier.test_services tests.fast8_packet_verifier.test_cli tests.editorial_workbench.test_packets tests.editorial_export.test_services --settings=config.settings.test --noinput --verbosity=1
40 tests; OK; 0 failures/errors/skips
System check identified no issues (0 silenced).

python -B -m ruff check --no-cache apps/fast8_packet_verifier tests/fast8_packet_verifier
All checks passed!

python -B -m ruff format --check --no-cache apps/fast8_packet_verifier tests/fast8_packet_verifier
8 files already formatted
```

The combined 40 includes the same 25 new tests, not 65 distinct tests. Fifteen
directly affected producer/export tests exercise unchanged authority services.
Five new CLI tests include real subprocess execution, missing acknowledgements,
production guards, immutable input files, canonical output and private-safe
tamper rejection. Symlink/reparse rejection is tested using metadata injection;
no claim of an actual Windows symlink or concurrent filesystem attack test.

Initial red evidence: the service tests failed because the new module did not
exist, and all four initial CLI tests failed before `__main__` existed. Two test
assumptions were corrected: `intake-1` has no draft (the cross-case revision test
uses `batch-synthetic-csv-1`), and a depth-limit test needs an object root to reach
depth validation rather than root-type rejection. No production negative check
was weakened. A subsequent byte-equality assertion exposed real Windows stdout
CRLF conversion; it failed before switching receipt output to binary stdout and
passed afterward.

An initial Django test invocation used the namespace package label
`tests.fast8_packet_verifier` and failed during discovery with
`TypeError: _path_normpath ... NoneType`. Explicit module names resolved discovery;
no shared package/configuration changes were made.

One independent read-only review ran the 25 new tests and 7,208 canonical JSON
tree mutations over the history packet and manifest: all mutations were rejected
with `PacketVerificationError`, no accepted changes or uncaught exceptions. For
that mutation probe only, the reviewer reused the fixed prebuilt export through
a mock to avoid repeated fixture construction; it is not a separate production
verification path. The review found README Python snippets needed formatting
after the initial Ruff run. Those snippets were formatted and the final documented
Ruff check/format commands passed (eight files). Review mutation probes are not
added to the committed test count.

## Exact synthetic input identities

Manifest SHA256:
`44f4d707fba4eb1e07545cfb640188fe76d55de848924b12773214332b1453d2`.

| Case | Source representation | Packet bytes | Packet SHA256 |
| --- | --- | ---: | --- |
| `history` | `serialized_intake` | 25173 | `fc1dcedcddc1f04cd3e25b84ea2fa862d35bd91884ee7d81c401dd87785c9e63` |
| `intake-1` | `original_utf8_slice` | 5528 | `8afc5136f7706e8f5373c46fbafed060983e28b2bf2b097192f70f8c3a25ec2c` |
| `batch-synthetic-csv-1` | `parsed_row_serialization` | 6761 | `64f615e4ca56de6b4a610a6a4ca682ee13121fb42a262aafffae5986f56062c2` |

| Case | Input SHA256 | Source text SHA256 |
| --- | --- | --- |
| `history` | `75fc9bc0ebedbac1ae3b9cbe28cfc308ab25f5eeb6813aeb50156c27be655bb0` | `75fc9bc0ebedbac1ae3b9cbe28cfc308ab25f5eeb6813aeb50156c27be655bb0` |
| `intake-1` | `cfb2bebf24e9f11bab46787e8b5926e93627b616ce85f6457c6d3715a236c0cb` | `9997733aafa7ef2daf20e944fecf31a5057d4c8d48b0575ecdc1fc26b7c96a09` |
| `batch-synthetic-csv-1` | `0e5d1bfe94c5f9abf5652a065b57212fcaa143abd738f95f2b233df5b68410f8` | `0598e433692f151215645cb4fac62b86aace9f4fa5572ed905bbb7a6d5d9b434` |

The history packet preserves revision numbers `[1,2,4,7,9,11]` (not inferred
consecutive numbers) and reference ordinals `[1,2,3]`. Intake-1 has no snapshots;
the CSV case has snapshot 1. All 20 fixed export cases are exercised separately
within the positive fixture test, preserving duplicate external IDs and blocked
or pending receipts without borrowing another case's snapshots.

## Limits and integration

- Browser/DB tests: NOT_RUN locally for this offline lane; no UI or DB changes.
- Owner-source acceptance: NOT_RUN / NOT_SUPPLIED.
- Full on-disk bundle contents: NOT_SUPPLIED to the single-packet command.
- Shared CI YAML is unchanged. The new focused module commands are provided for
  the integration coordinator; remote B6/C6/D6 results must not be described as
  automatic coverage of these new tests unless their logs demonstrate collection.
- No policy, role grants, scholarly decisions, production writes, migrations,
  deployment, protected source changes or merge to main.

NOT_DEPLOYED / GATES_HOLD / SCOPE_DEVIATION_HOLD.
Gate B NOT_PASSED; C/D/E HOLD; Phase01 BLOCKED;
U03/U10 OWNER_APPROVAL_PENDING.
