# Synthetic policy-gap CLI

This offline development report compares synthetic candidates with fixed local
evidence and runs adversarial checks. Every decision remains `DENY` with
`allowed: false`. Successful execution grants no permission and accepts no owner
policy. Gate B remains `NOT_PASSED`, Gates C/D/E remain `HOLD`, and Phase01 remains
`BLOCKED`. Nothing is deployed.

Run from the repository root with Python 3.13:

```console
python -m tools.policy_gap_engine --synthetic-only
python -m tools.policy_gap_engine --synthetic-only --actor MUFTI --action synthetic::answer.create --resource synthetic::answer
python -m tools.policy_gap_engine --synthetic-only --actor MUFTI --action complete_review --resource workflow::IN_REVIEW --target-state REVIEWED_INTERNAL
python -m tools.policy_gap_engine --help
```

The exact `--synthetic-only` flag is required. Supply `--actor`, `--action`, and
`--resource` together, or omit all three to use the fixed synthetic requests.
`--target-state` requires that complete triple. Custom values are untrusted
synthetic candidates, never grants; unknown values are sanitized in the report.
No file, policy, or output path options are supported. The CLI does not initialize
Django, connect to a database, or access the network.

Stdout contains canonical UTF-8 JSON with sorted keys, two-space indentation,
and a trailing newline. The report includes separate adversarial-check results.
Identical inputs and evidence produce identical output bytes. Argument errors
go to stderr without a JSON report.

| Exit code | Meaning |
| --- | --- |
| `0` | Report completed (or help displayed). Never a permission grant. |
| `2` | Invalid arguments or missing explicit synthetic acknowledgement. |
| `3` | Evidence unavailable or adversarial checks failed. Decisions remain denied. |

Run the CLI tests from the repository root:

```console
python -B -m unittest discover -s tests/policy_gap_engine -p test_cli.py -v
```
