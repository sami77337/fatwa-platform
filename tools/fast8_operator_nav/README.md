# FAST8 operator navigation

Development-only RTL navigation over the existing fixed synthetic queue,
search, workbench, research bridge and export services. The list exposes the
20 actual catalog case keys; bounded search preserves hit revision identities,
pagination and the return path. Sparse history IDs are selected by the existing
revision selector. Source text is escaped without Unicode/CRLF normalization.

The app is deliberately **unmounted**. A coordinator can mount
`path("dev/operator-navigation", include("apps.fast8_operator_nav.urls"))`
in an isolated integration after review. No installed-app or template-loader
setting is needed: fixed app-owned templates use the existing Django engine.
No shared configuration, routes, CI, source data or existing files were changed.
Removal of this mount and the new directories is the rollback; no migrations.

GET/HEAD only. Existing host AND peer loopback plus production guards apply
before fixtures are read, including CSS. Missing named service mounts display
NOT_CONNECTED without guessed links. Sibling FAST8 contracts remain
NOT_CONNECTED. The research destination is case-level original/current
references, **not** the selected historical revision. Export is explicitly the
complete catalog. Revision timestamps are NOT_SUPPLIED by the synthetic domain.

## Reproduce focused verification

Python 3.13, existing pinned dependencies, Node and an installed sandboxed Chrome:

```powershell
python -B manage.py test tests.fast8_operator_nav.test_views tests.fast8_operator_nav.test_browser tests.editorial_queue.test_services tests.editorial_search.test_services --settings=config.settings.test --verbosity=1
python -m ruff check apps/fast8_operator_nav tests/fast8_operator_nav
python -m ruff format --check apps/fast8_operator_nav tests/fast8_operator_nav
git diff --check
```

The tests alone mount `/operator` through an owned URLconf. The browser uses the
existing ProtectedBrowser lifecycle and CDP transport. All page traffic is
intercepted: allowlisted loopback GET/HEAD only, all other traffic fails the test.
`FATWA_FASTBUILD_BROWSER` may name an existing Chrome executable; none is installed
by this lane. Startup/application/cleanup failures are errors, never skipped.

Local evidence on the final code: **36 tests passed, zero skips** (13 new HTTP,
1 new browser, 22 directly used queue/search service regressions). Runs were
split after correcting a test-only assumption that search page 2 contained a
revision hit. Guarded Chrome verified 320/375/1280 viewport geometry, keyboard
skip-link focus/outline, service links, search-return identity, and exact prepared
CSV CRLF/combining Unicode: 165 intercepted requests, zero external/write requests.
Desktop clientWidth excludes the vertical scrollbar; innerWidth remains exact,
mobile clientWidth is exact, and overflow is checked against clientWidth.
Ruff check/format and whitespace validation pass.

One independent final review completed with no blocking findings; its executable
probe followed 82 generated links across all cases and search pages. Both review
suggestions (strict viewport geometry and browser textContent preservation) were
implemented and passed. No agent remains actively reviewing.

Initial attempts are recorded rather than counted as passes: package-label Django
discovery failed on the namespace `tests` package (explicit modules work); initial
red tests failed on the missing new app; a page-2 test expected a revision hit
where only other document types existed; strict desktop clientWidth equality
failed on Chrome's 15px scrollbar and was corrected as described above. No
application guard, source assertion or existing negative test was removed.

## Input identity and limits

Reviewed base: `92fa517ecdefe3f1a92a1ab145ff55943474df44` (Draft PR #134).
Only existing fabricated in-code fixtures were used, unchanged:

| Fixture producer | Local file SHA256 |
| --- | --- |
| `apps/editorial_demo/revision_fixtures.py` / `REVISION_HISTORY_RECORD` | `2dded1030f319e039565192f24a3b170b170113ff8e9a1fe2e08cc587a82ea22` |
| `apps/intake_workflow/fixtures.py` / `synthetic_payload()` | `24cfcdd469eebacc2a3bb5c1259c84b2481b9acd90ead186c3a395f15dbc531d` |
| `apps/editorial_workbench/batch_fixtures.py` / `synthetic_inputs()` | `c9de0de61fd54aee32ad938d754cf3f8c944b2568721a1b53680a77ae562c027` |

HTTP/browser research lookup uses an explicitly unavailable-catalog test double.
Database access is forbidden by SimpleTestCase. PostgreSQL/source-owner archive
acceptance: NOT_RUN / NOT_SUPPLIED. No archives were accessed or copied. Existing
B6/C6/D6 CI does not automatically collect this new lane; integration must add
the explicit tests above. Exact commit/remote/CI status belongs to the Draft PR.

NOT_DEPLOYED / GATES_HOLD / SCOPE_DEVIATION_HOLD.
Gate B NOT_PASSED; C/D/E HOLD; Phase01 BLOCKED;
U03/U10 OWNER_APPROVAL_PENDING. No scholarly action, account/role mutation,
public write endpoint, source import, production write or deployment.
