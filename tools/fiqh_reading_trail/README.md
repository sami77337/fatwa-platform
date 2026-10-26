# Synthetic offline fiqh trail CLI

This stdout-only tool demonstrates the pure reading trail service using nine
invented headings. It accepts no input files, URLs, uploads, edition overrides,
output paths, or external services. It does not configure Django or connect to
PostgreSQL. The topology extends the existing Wave7 synthetic source assertions;
research entry reuses the existing `intake-1` reference occurrence 1 unchanged.

```text
python -B -m tools.fiqh_reading_trail --synthetic-fixtures-only
python -B -m tools.fiqh_reading_trail --synthetic-fixtures-only --source-row-id 42 --from-reference
```

The default heading is row 40. `--from-reference` rechecks the fixed research
origin and retains its exact return link even after moving to another heading.
Rows in source order are `1, 2, 40, 41, 42, 3, 8, 9, 10`. Their depth reaches five;
IDs, positions, and ordering have gaps. Two different branches repeat a title.
The fixture also includes Arabic marks, surrounding whitespace, HTML-looking
title text, a combining character, and decreasing/repeated printed pages.

Output is deterministic UTF-8 JSON with schema `fatwa.fiqh-reading-trail.v1`.
It includes the fixture digest, prepared-catalog checksum, unchanged HOLD gates,
and the service result. Exit 0 means a technically verified synthetic trail,
exit 2 means invalid CLI arguments or an unverified requested heading, and exit 1
means the demonstration could not complete. Unverified results contain no
headings or links. Invalid options produce no JSON and do not echo their values.

## Evidence and reproduction

Base: FAST6 PR #121, `667fd70217d794169c23569ce2df0396dcd27f7c`.
Branch: `codex/20261026-fast7c-fiqh-trail-pc1`.
Python 3.13.15, Django 5.2.18, Ruff 0.17.0, Windows.
These commands ran against that base plus the new files; delivery SHA and final
review outcome are recorded in the Draft PR.

```powershell
$trailLabels = @('tests.fiqh_reading_trail.test_services', 'tests.fiqh_reading_trail.test_boundaries', 'tests.fiqh_reading_trail.test_cli', 'tests.reference.test_records', 'tests.research_bridge.test_services', 'tests.research_bridge.test_views', 'tests.reference_triage.test_services', 'tests.editorial_workbench.test_services') + @(Get-ChildItem -LiteralPath tests/reference_links -Filter test_*.py -File | ForEach-Object { 'tests.reference_links.' + $_.BaseName })
python -B manage.py test @trailLabels --settings=config.settings.test --noinput --verbosity=1
python -B manage.py check --settings=config.settings.test
python -m ruff check apps/fiqh_reading_trail tools/fiqh_reading_trail tests/fiqh_reading_trail --no-force-exclude
python -m ruff format --check apps/fiqh_reading_trail tools/fiqh_reading_trail tests/fiqh_reading_trail --no-force-exclude
git diff --check
```

- 26 new tests passed; combined new/directly affected suite: 187 passed,
  no skips (1.664 seconds). Existing research HTTP tests use mocked catalog
  reads. No database-backed acceptance is claimed.
- System check and scoped Ruff lint/format passed. `--no-force-exclude` includes
  the CLI despite the repository's general tools exclusion.
- RED evidence: before implementation, the new service suite failed import with
  `ModuleNotFoundError: apps.fiqh_reading_trail`. GREEN: the implemented service
  passes the hierarchy, traversal, provenance and closed-result tests.
- Side-effect guards block file opens, socket creation, subprocess launch and
  the default Django catalog lookup while both pure entry points run.
- One independent final read-only review completed with no actionable findings;
  the reviewer reran 36 tests (26 new + 10 research bridge), all passing in
  1.238 seconds, plus scoped Ruff lint/format and whitespace checks.

| Artifact | SHA256 |
| --- | --- |
| `fast7c-reading-trail-synthetic-v1`, canonical `fixture_bytes()` | `b1abc9c56a6173f8c7c2f573af746aaee6140aaea58df26b6ffebd7803e12d98` |
| Prepared catalog checksum | `5349fd891831a0e2d0d831aede0a3353c5dff8bdf931c70e8645856f93c04c45` |
| CLI `--source-row-id 42 --from-reference`, 11,218 bytes | `13c149fd1d56d6fc497a104261965b77929ae0041ebf48073bb0274841a1dd8a` |

The repeated `a`/`b` archive/input pins inside the inherited source identity are
fabricated assertions. The fixture digest above measures actual canonical
synthetic bytes; it does not turn those pins into inspected archive hashes.

No protected file or shared route is changed. No CI workflow is edited; run the
explicit test labels above for this new suite. No migrations or data conversion
are needed; rollback removes the additive modules. Browser integration, original
owner archives and PostgreSQL acceptance are **NOT_RUN** for this pure-service
delivery. Exact parent edges/order are trusted prepared-catalog inputs, as
documented in `apps/fiqh_reading_trail/README.md`.

**Gate B NOT_PASSED; C/D/E HOLD; Phase01 BLOCKED;
NOT_DEPLOYED / GATES_HOLD.**
