# Offline synthetic workflow replay

Run from the repository root with Python 3.13. No dependency installation,
Django configuration, database, server, network or output file is required.

```powershell
python -m tools.workflow_invariants --scenario rehearsal
python -m tools.workflow_invariants --scenario preparation
python -m tools.workflow_invariants --scenario blocked
python -m tools.workflow_invariants --input tools/workflow_invariants/fixtures/rehearsal.json
python -m tools.workflow_invariants --input -
python -m tools.workflow_invariants --scenario preparation --emit-fixture
python -m tools.workflow_invariants --scenario rehearsal --fail-on-rejection
```

Output is canonical UTF-8 JSON on stdout. Diagnostics are JSON on stderr.
Exit codes: `0` replay completed (expected rejections are evidence), `1` rejected
events with `--fail-on-rejection`, `2` invalid envelope/JSON or input I/O failure,
`3` invariant mismatch. Invalid command-line options use argparse's usage error.
The CLI only reads the specified input and writes stdout/stderr. Shell redirection
is optional and caller-controlled. Supply synthetic event commands only.

`rehearsal` exercises the existing eight FAST5 attempts, including prohibited and
out-of-order review actions. `preparation` traverses the remaining preparation
edges on the existing populated `history` fixture. `blocked` proves no draft is
fabricated for a blocked duplicate intake row. JSON fixture files are command
logs pinned to those existing synthetic sources, not owner archives or policies.

For a reusable service, see [the engine contract](../../apps/workflow_invariants/README.md).

```powershell
python -m unittest discover -s tests/workflow_invariants -v
```
