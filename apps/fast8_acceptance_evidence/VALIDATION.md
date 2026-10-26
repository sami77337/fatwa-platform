# FAST8 acceptance-evidence validation

Reviewed starting commit: `92fa517ecdefe3f1a92a1ab145ff55943474df44` (Draft PR #134).
Isolated branch: `codex/20261026-fast8-acceptance-evidence-pc1`.
Draft PR target: `codex/20261026-fast7-ci-integration-pc1`.

Python 3.13.15 on Windows; existing dependencies only. The following targeted
command passed on the delivered file contents: **31 tests, zero failures/errors,
zero skips** (20 new adapter tests and 11 directly reused FAST6 integration tests).

```console
python -m unittest tests.fast8_acceptance_evidence.test_services tests.fast8_acceptance_evidence.test_cli tests.fast6_journey.test_integration -v
python -m ruff check apps/fast8_acceptance_evidence tools/fast8_acceptance_evidence tests/fast8_acceptance_evidence
python -m ruff format --check apps/fast8_acceptance_evidence tools/fast8_acceptance_evidence tests/fast8_acceptance_evidence
git diff --check
```

The first new-test run reported one test-harness error: its database access spy
named `bridge.DjangoCatalog`, but the existing class resides in `django_adapter`.
The spy path was corrected; the same negative assertion now passes. Ruff also
identified an unused test import and formatting; both were corrected. No negative
test was removed, weakened or skipped.

One independent read-only review completed with no blocking code findings. Its
documentation finding was addressed in `tools/fast8_acceptance_evidence/README.md`.
No parallel implementation worker was used.

Actual generated fixed synthetic report:

- 21 matrix rows: PASS 3, FAIL 0, BLOCKED 4, NOT_RUN 6, NOT_SUPPLIED 6,
  NOT_CONNECTED 2. Overall status BLOCKED.
- Exact FAST6 integration report: 282,974 bytes,
  SHA256 `1f398dc8820159559f5afafee3054d592e2e5ac02992e7e9461c82ae582a97e5`.
- Exact FAST8 matrix: 292,704 bytes,
  SHA256 `c90bc0ef489e1160c79bc755584b43e8687eccd63f82e56bfde47356137cfae2`.
- Inputs are exclusively the existing fixed synthetic FAST6 journey, stock and
  prepared workbench cases, workflow replay and synthetic policy inventory.
  Policy inventory SHA256:
  `40df94e24af7d64b4fac4285000aa928282ac25f2110b07dce055d2994820dd4`;
  synthetic review excerpt SHA256:
  `266e07ae6b229a19df2d11b8a9aa986e9cd468a05ecacfd7d22de3ebdd7b760d`.
  The complete producer payload retains every case/input/source identity.

Negative coverage includes forged owner acceptance, grants, bool/int aliases,
empty passing checks, changed schemas/scopes, claimed browser success, duplicate
or invented connections, upstream unavailability, bounded invalid input, replay
tampering, production guards, private-argument redaction, exact Arabic/CRLF and
prohibited filesystem writes, archives, sockets, subprocesses and DB lookups.

No local browser/PostgreSQL suite was run: no UI/DB change is made in this lane.
Remote B6/C6/D6 results and actual delivery SHA are recorded separately in the
Draft PR; this offline report never infers those results. Existing CI YAML does
not collect this new lane automatically; the targeted local result above is its
executable evidence, and the integration coordinator must explicitly register it.

Owner archives, 70 historical policy rows, 58 transition records and U03/U10
acceptance are NOT_SUPPLIED. No owner content was opened, copied or reconstructed.
No migrations, grants, scholarly approvals, production writes or deployment.

NOT_DEPLOYED / GATES_HOLD / SCOPE_DEVIATION_HOLD.
Gate B NOT_PASSED; C/D/E HOLD; Phase01 BLOCKED;
U03/U10 OWNER_APPROVAL_PENDING.
