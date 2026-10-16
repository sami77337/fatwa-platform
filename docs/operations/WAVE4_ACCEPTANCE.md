# Wave4 local and CI acceptance

Run from the checkout root with Python 3.13 and Node 24:

```text
python -m pip install -r requirements.txt
python -m unittest discover -s tests/dev -p "test_*.py" -v
python tools/dev/wave4_qa.py --wave3 --json wave4-summary.json
```

Windows one click: `tools\dev\TEST_WAVE4_LOCAL.cmd`. It selects `.venv\Scripts\python.exe` or `python`; `FATWA_PYTHON` may select an executable (including a path containing spaces). Set `FATWA_NO_PAUSE=1` for automation. Arguments pass through, including `--isolated --wave3`. Default mode requires all D1-D5. `--isolated` permits missing lanes, but records acceptance NOT_RUN. Any actual subprocess failure still fails isolated mode.

## Explicit integration contract

`tools/dev/wave4_suites.json` is the authoritative dispatcher input. D1-D5 implementations are absent at base cf877ab6d0abadbeafe15efa8ef9c286e7795b23. No agreed Wave4 paths were supplied in the checkout. The committed paths are **proposed integration slots**, not claims that other lanes use these names. Publisher must map `implementation` to the actual Wave4 entry files, `python` to every actual Wave4 unit-suite directory, and `node` to every D4 JS test file before combined acceptance. Multiple entries are supported; `--manifest PATH` allows a reviewed alternative. Do not point implementation entries only at legacy Wave3 directories, which would not establish presence of Wave4 code. There is no auto-guessing, optional-lane CI switch, or fallback to old suites.

Each lane needs at least one implementation and Python suite; D4 also needs Node files. Paths must stay beneath the repository; manifest size, path lengths and entry counts are bounded. Missing/empty test directories are NOT_RUN. Each Python directory containing `test*.py` is explicitly discovered in an independent process, including namespace directories and duplicate leaf filenames; zero cases fail. Regular package relative imports should use package imports from the project root. Node uses an event reporter that excludes implicit file successes and skipped/todo tests; zero registered runnable tests fail. Synthetic LF/CRLF tests write temporary bytes and verify originals unchanged; no source fixture normalization is performed by the runner.

## Exit and report contract

- 0: executed checks passed; inspect `acceptance`, which can still be NOT_RUN under `--isolated`.
- 1: subprocess/test/system failure; other available lanes still run.
- 2: invalid CLI/manifest or summary write failure.
- 3: Python is not exactly 3.13; no suites run.
- 4: required integrated implementation or tests absent.

Child results retain actual exit codes, including 124 timeout and 127 unavailable executable. Reports retain at most 3000 bytes of each child's output, decoded safely, with truncation indicated. Output capture is disk backed, execution is time limited and shell-free. `--json` writes the same human-readable summary printed to stdout. Test output can include synthetic fixture text and local paths; do not run against private data.

Django `check` runs using test settings. All children receive sanitized environment, project-root PYTHONPATH and UTF-8 mode, and PostgreSQL port 1 with no inherited connection credentials. No Docker, migrations, database suites, source import, media processing or publication is dispatched. PostgreSQL acceptance remains NOT_RUN here. Existing B6 PostgreSQL 17/18 ephemeral GitHub service workflow is unchanged. D6 CI runs the dispatcher regressions plus required combined Wave4 and optional legacy suites on both Ubuntu and Windows, installs requirements and Node, and uploads JSON even after a failure. Missing lanes intentionally fail CI until integration; failures are never disabled.

NOT_DEPLOYED / GATES_HOLD.
