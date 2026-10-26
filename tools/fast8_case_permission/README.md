# Offline case/permission CLI

Run from the repository root with the existing Python 3.13 dependencies.
The CLI loads only built-in fabricated fixtures, accepts no source path or URL,
and writes JSON only to stdout. No Django setup or database is required.

Inspect an exact case (default hypothetical resource is `synthetic::case`):

```console
python -B -m tools.fast8_case_permission --synthetic-only describe --case-key batch-synthetic-csv-1 --scenario-resource synthetic::answer
```

Feed that descriptor's UTF-8 JSON to a separate evaluation. A native pipe
preserves bytes; shells that transcode native output should use a Python pipe:

```python
import subprocess
import sys

base = [sys.executable, "-B", "-m", "tools.fast8_case_permission", "--synthetic-only"]
receipt = subprocess.run(
    base
    + [
        "describe",
        "--case-key",
        "batch-synthetic-csv-1",
        "--scenario-resource",
        "synthetic::answer",
    ],
    check=True,
    capture_output=True,
).stdout
result = subprocess.run(
    base
    + [
        "evaluate",
        "--case-key",
        "batch-synthetic-csv-1",
        "--actor",
        "MUFTI",
        "--action",
        "synthetic::answer.create",
        "--descriptor-stdin",
    ],
    input=receipt,
    capture_output=True,
    check=False,
)
print(result.stdout.decode("utf-8"))
```

This produces VERIFIED synthetic context and CANDIDATE_ONLY diagnostics, while
remaining DENY / allowed=false, POLICY_PENDING and MISSING_EVIDENCE. Repeat with
`--actor ORGANIZER_ADMIN` to inspect the existing scholarly-authority rejection.
Switching evaluation's `--case-key` to `history` rejects cross-case substitution.
Describing `batch-synthetic-json-1` rejects the duplicate external ID. Changing
any row identity or receipt SHA rejects stale context. An unknown key never
selects the first row. `--target-state` delegates exact target checking to the
existing policy gap engine.

Input is bounded to 8192 UTF-8 bytes, with exact fields/types and duplicate JSON
keys rejected. No extra `allowed`/approval fields are accepted. Exit codes:

- 0: descriptor issued or valid hypothetical combination inspected; **not access**.
- 2: invalid CLI usage or missing explicit synthetic opt-in.
- 3: rejected/unavailable context or invalid hypothetical policy combination.

Focused verification:

```console
python -B -m unittest discover -s tests/fast8_case_permission -v
python -B manage.py test tests.editorial_queue.test_services tests.editorial_queue.test_cross_batch tests.policy_gap_engine.test_services tests.policy_gap_engine.test_evidence tests.permission_lab.test_services --settings=config.settings.test --noinput --verbosity=1
python -m ruff check --no-cache apps/fast8_case_permission tools/fast8_case_permission tests/fast8_case_permission
python -m ruff format --check --no-cache apps/fast8_case_permission tools/fast8_case_permission tests/fast8_case_permission
```

The shared B6/C6/D6 workflows remain unchanged. They do not automatically collect
this new test directory; the coordinator must include the focused command above
in integration acceptance. Green shared CI is not proof it ran these new tests.
