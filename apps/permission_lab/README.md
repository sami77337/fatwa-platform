# FAST5 deny-default permission laboratory

An executable, read-only inspector at `/dev/permission-lab`, connected to the
existing Django development application. Every inspection returns **DENY**;
there is no allow path, grant store, authentication backend or workflow dispatch.

Run the existing local preview server from the repository root:

```powershell
python -m apps.editorial_demo
```

Open `http://127.0.0.1:8012/dev/permission-lab`. Select an exact hypothetical
actor, action and synthetic resource, then submit the GET form. The page retains
the selection and explains candidate-only metadata, pending owner policy,
internal effects, mismatched resources and incompatible workflow states.
The back link connects to the existing FAST4 editorial dashboard.

The selected actor is a hypothetical label. It neither authenticates the visitor
nor impersonates a real account. FAST4's `local_only` guard requires both a
loopback host and loopback peer and rejects production. Existing middleware and
view decorators restrict requests to GET/HEAD. Nothing changes real access-control
configuration. No database reads/writes, migration, editorial persistence, source
upload, user record lookup or public write endpoint is introduced.

## Reused sources and honest coverage

FAST4 base: `262fa3d40975cfc0698b045becc2da885760a995` on
`codex/20261025-fast4-integration-pc2`.

The S3 contracts are not present in that integration. The exact existing validator,
schema and synthetic fixtures are reused as a pinned snapshot from
`88c411852d1a90e62ec71ab1c9ae2278f72d0c76`; see
[`upstream/README.md`](upstream/README.md) and its provenance manifest.
The validator is reused unchanged, not reimplemented. Fixed paths and hash pins
reject missing or modified inputs. No runtime Git, remote access, caller-supplied
policy, file path or source inventory is accepted.

- Fixture identity: S3 `SYNTHETIC`, four invented action rows and one transition.
- Inventory SHA256: `40df94e24af7d64b4fac4285000aa928282ac25f2110b07dce055d2994820dd4`.
- Synthetic excerpt SHA256: `266e07ae6b229a19df2d11b8a9aa986e9cd468a05ecacfd7d22de3ebdd7b760d`.
- The original 70 historical rows, 58 transitions, reviewed original sources and
  detailed U03/U10 clauses are **unavailable**. They are not reconstructed.
- `apps.intake_workflow.contracts` supplies existing review actions, states and
  `next_review_status`; its valid transitions are inspected without execution.
- The eight resource contexts in `services.py` are explicitly invented lab
  bindings, not claims about historical mappings or actual case records.

`valid_combination` means exact known identifiers and compatible resource/state.
It is never authorization. The immutable decision always has `allowed=False` and
`effect=DENY`. Candidate roles and administrative hierarchy confer no access.
Pending U03/U10 means DENY. `DOMAIN_TRANSACTION` cannot act as a principal;
documented internal effects cannot be called. No scholarly approval is inferred.
Missing source integrity returns a closed failure; the UI displays DENY with 503.
Unknown/duplicate/partial/oversized inputs return 400 without resolving real data.

## Verification

Use the repository's pinned requirements with Python 3.13. Browser checks also
use the existing Node 24 / Chrome test harness; the Chrome sandbox stays enabled.
Run explicit test modules because this repository's root `tests` is a namespace
package and Django directory-label discovery fails in this environment.

```powershell
python manage.py test tests.permission_lab.test_sources tests.permission_lab.test_services tests.permission_lab.test_views tests.permission_lab.test_browser tests.wave7_foundation.test_contracts tests.editorial_dashboard.test_dashboard tests.editorial_followup.test_views tests.editorial_search.test_views tests.editorial_export.test_views tests.editorial_workbench.test_views tests.editorial_queue.test_views tests.reference_triage.test_views tests.editorial_demo.test_preview --settings=config.settings.test
python manage.py check --settings=config.settings.development
python -m ruff check apps/permission_lab tests/permission_lab --exclude apps/permission_lab/upstream
python -m ruff format --check apps/permission_lab tests/permission_lab --exclude apps/permission_lab/upstream
```

The byte-exact upstream snapshot is excluded from reformatting. Its identity is
checked separately. New tests exercise every catalog triple, exact state/action
pairs, malformed and unknown identifiers, admin-peer escalation attempts,
internal effects, pending policy activation, shadow grants, source tampering,
production/remote access, query pollution and blocked writes. Django
`SimpleTestCase` forbids database access for services, views and browser tests.

No PostgreSQL-backed acceptance, original-source acceptance or CI success is
claimed for this change. No production migrations exist.

Measured on Windows with Python 3.13.17 / Django 5.2.18, on the FAST4 base above
plus this branch's permission-lab changes: **137 tests passed in 21.211 seconds**
(28 new lab tests, 109 existing directly affected tests). The browser test passed
in sandboxed Chrome at 1280/375/320 pixels with real keyboard form submission,
skip-link focus, wrong-resource denial, dashboard navigation, no overflow and no
runtime/network/HTTP errors. Django system check, scoped Ruff lint/format,
JavaScript syntax and `git diff --check` passed. The five upstream artifact hashes
were also matched byte-for-byte against the pinned S3 Git objects.

Initial red runs exposed the absent source loader/service/route. One integration
test assumption was corrected: queries above 4096 characters are rejected by the
existing global middleware as JSON `invalid_query` before the lab renders; the
lab's own 1024-character bound and excessive-field rejection display DENY/400.
The failed directory-label discovery command was replaced with the explicit
module command above; no shared discovery configuration was changed.

One independent final read-only review returned **PASS**, with no critical,
important or minor findings. It independently ran the 27 source/service/view
tests and checked all five vendored files against their original Git objects.
Historical acceptance, unavailable policy clauses, PostgreSQL behavior,
production authorization, deployment readiness and CI success remain outside
the demonstrated evidence; the parent-run browser result is separate evidence.

Gate B NOT_PASSED; C/D/E HOLD; Phase01 BLOCKED; SCOPE_DEVIATION_HOLD; NOT_DEPLOYED.
