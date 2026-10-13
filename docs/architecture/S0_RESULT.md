# S0 result — issue #1 — 2026-10-13

**NON_PRODUCTION_DRAFT / NOT_DEPLOYED / GATES_HOLD. Runtime acceptance blocked.**
Branch: codex/fatwa-foundation-20261013. Baseline and unchanged current HEAD:
08f9e25e8ada9af56561d815f74b2c7ec9ba7ead. All implementation files are left on
disk, untracked for the coordinator's path review; no Git writes or PR actions.

Implemented Django settings/security/method denial, public catalog ORM, two
PostgreSQL migrations and immutable hierarchy guards, typed atomic dry-run-first
S1 adapter, bounded read-only JSON/SSR services, Arabic RTL/htmx templates,
synthetic backend tests and a read-only performance command.

## Changed paths

- config/**: settings, middleware, URL table, ASGI/WSGI.
- apps/reference/**: models, migrations, ingest contract/services/views, database
  checks, fixed public CSS/JS, benchmark_reference management command.
- templates/reference/**: five minimal service-integrated templates.
- manage.py; pyproject.toml; requirements.txt; requirements-dev.txt.
- tests/reference/**: pure synthetic record/query checks and PostgreSQL/HTTP tests.
- docs/architecture/**: PLAN.md, README.md, INGEST_CONTRACT.md, API.md, this result.

The complete new-file inventory from git ls-files --others --exclude-standard
was checked against exact S0 ownership; no forbidden paths were found. AGENTS.md,
coordination, root README, sibling lanes and shared Git metadata were not edited.

## Actual commands and outcomes

| Exact command | Outcome |
|---|---|
| git status --short --branch | Correct S0 branch; only owned new paths |
| git rev-parse HEAD | 08f9e25e8ada9af56561d815f74b2c7ec9ba7ead |
| py -0p | Exit 0, output: No installed Pythons found! |
| python --version | ENOENT; interpreter absent |
| where.exe psql | Exit 1; not found |
| docker version --format '{{json .}}' | Exit 1; Server null, daemon pipe absent; config access warning |
| python manage.py check --settings=config.settings.test --database=default | NOT_RUN: spawn ENOENT |
| python manage.py makemigrations --check --dry-run --settings=config.settings.test | NOT_RUN: spawn ENOENT |
| python -m unittest discover -s tests/reference -p test_records.py -v | NOT_RUN: spawn ENOENT |
| python manage.py test tests/reference --settings=config.settings.test --verbosity=2 | NOT_RUN: spawn ENOENT |
| python -m ruff check --no-cache config apps/reference tests/reference manage.py | NOT_RUN: spawn ENOENT |
| python -m ruff format --check --no-cache config apps/reference tests/reference manage.py | NOT_RUN: spawn ENOENT |
| python -m mypy --cache-dir=tests/reference/.mypy_cache | NOT_RUN: spawn ENOENT |
| node --check apps/reference/static/reference/tree.js | PASS: exit 0; JavaScript syntax only |
| git diff --check | Exit 0; tracked diff empty, so does not validate new files |

A separate local Node scan of all new text files found no trailing whitespace.
Shell/process operations ran through local Node child_process because unified
exec_command failed in setup before execution. Python tests did not start, so
there is **no unit/PostgreSQL/API/coverage PASS**. Migrate/reversal, clean pip
install/pip check, dependency audit, browser/RTL/mobile/accessibility smoke,
full-source import and performance benchmark: **NOT_RUN** for missing runtime
and/or required sibling integration. No performance numbers were invented.

Source identity command actually run (exit 0):

~~~powershell
Get-FileHash -LiteralPath '_codex_input/FATWA_BUILD_SPRINT_01_R2_20261011.zip','_codex_input/FATWA_622_FIQH_COMPLETE_TOC_11397_20261011.zip' -Algorithm SHA256 | Select-Object Hash,Path | ConvertTo-Json -Compress
~~~

Matched archive SHAs: sprint 2b50ef138d2890156121e784618715e9992e04bed7d437bbf13e5d6250d0e78b;
TOC 82a797806430635350decdde27d07fe41fb1278838c8173dc4080f9d109957ce.
Read-only Node ZIP-member inspection observed 11,397 JSONL records, title max 198,
part max 7, and member SHA 37544f6122ef72fb6bd908556ffb41821b235be28bcbd1413752042dbac01d14.
Member: FATWA_622_FIQH_COMPLETE/622_الفهرس_كامل_11397.jsonl. This proves observed
input identity/shape, not full title/ID/graph/page validation or ORM import.
Source files were supplied; BLOCKED_SOURCE_FILE_MISSING does not apply. Input
code was not executed; no raw data, private exports or input files were copied
into the changed files. Test fixture: hand-authored s0-five-rows-v1, five headings,
two roots, max depth 3, synthetic placeholder hashes; no source acceptance claim.

## Required integration / blockers

1. S5/coordinator: provide Python 3.13 and disposable PostgreSQL 18/17; install
   exact dependencies, run checks above, execute/reverse migrations and record
   actual DB version. Schema migrations were authored without a Django runtime;
   consistency and runtime behavior require independent verification.
2. S1: wire its validator/command to apps.reference.ingest.ingest_catalog per
   INGEST_CONTRACT.md; validate every original title/ID/page and 11397/32/5;
   preview then checksum-pinned commit then unchanged rerun. Full import blocked
   by absent runtime and S1 integration, despite verified source ZIP identities.
3. S2/S4: integrate the UI, test native and htmx/no-JS paths on desktop/mobile,
   then independent security/negative HTTP QA. Existing test assertions are not
   evidence until run.
4. S5: CI and dependency audit. Full ORM/view static typing is still unverified;
   configured strict mypy scope is the pure boundary modules. Coordinator must
   link docs/architecture/README.md from the root README, outside S0 ownership.
5. After verified import, run python manage.py benchmark_reference --edition
   <actual-id> --expected-headings 11397 --query "كتاب" --repeats 5 and retain
   real output/source hashes. No database import or gate status is accepted here.

Gate B NOT_PASSED; C/D/E HOLD; Phase01 BLOCKED; U03/U10 pending. Production boot
is denied. No private intake, active grants, publication/approval, AI, delivery,
Telegram, deployment, purchase, external messages, Git writes or PR publishing.
Coordinator owns optional commit/push and DRAFT PR after review.
