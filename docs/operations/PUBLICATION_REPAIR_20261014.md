# S5 publication repair validation — 2026-10-14

**NON_PRODUCTION_DRAFT / NOT_DEPLOYED / GATES_HOLD**

Branch: codex/s5-infra-ci-20261013  
Unchanged HEAD: 08f9e25e8ada9af56561d815f74b2c7ec9ba7ead

The controller's S5-only dry run returns **READY_TO_PUBLISH**. This is a source/security inspection result; no publication action was executed. All 19 candidate files are within S5 ownership. The existing seven lane worktrees, their branches and HEADs were preserved. The six sibling status inventories are unchanged, and S5 has no staged changes or tracked-file modifications.

## Repairs and credential classification

- Replaced the incorrect equals-sign SQL assertion with validation of the existing quoted psql parameter binding, environment import, quoted heredoc, restricted role flags, public privilege revocations and environment cleanup. The correct initdb script was retained.
- Added empty-password rejection to healthcheck.sh and smoke.sh, preserving mounted secret reads and authenticated TCP readiness. Fixed smoke.sh's final newline.
- Replaced hardcoded negative-test credential strings with values generated during each test. These remain inputs that the Compose validator must reject.
- Changed the disposable CI fixture expressions to consist entirely of runtime run identifiers. They are public ephemeral CI fixture values, not production credentials.
- Corrected the controller's credential scanner to distinguish whole runtime references, psql parameters, JavaScript expressions and regex signatures from literal credentials. All legacy token/private-key signatures remain unconditional. New rules detect fine-grained GitHub tokens, AWS access key identifiers, short and unquoted credential values, SQL password literals, and credential-bearing database/HTTP URLs.
- Added fail-closed path checks for case variants of .env and private .local directories. No file, lane or synthetic credential value was blanket exempted.

The original six scanner matches were three mounted-file reads, a psql variable binding and two test literals. No live token/private key was found in the S5 publication candidates. Detection errors identify file paths without printing matched values.

## Actual results

| Check | Result |
| --- | --- |
| node --test infra/dev/tests/infra.test.mjs | PASS: 25 tests, 0 failures, 0 skips |
| node infra/dev/checks.mjs | PASS |
| Controller publication-security regressions | PASS: 17 tests, including generated positive/negative cases |
| Existing controller ScopeAndSafetyTests | PASS: 6 tests |
| node --check | PASS: all five JavaScript modules |
| Git for Windows sh.exe -n | PASS: all three shell scripts |
| Actual standalone Compose config --quiet | PASS: PostgreSQL 18 and 17 definitions; both warn that Docker config access is denied |
| node infra/dev/dev.mjs validate | PASS |
| node infra/dev/application.mjs detect | Correct explicit NOT_RUN: manage.py absent |
| Controller publish_lane(..., S5, dry_run=True) | PASS: READY_TO_PUBLISH, 19 scoped files |
| Docker preflight | FAILED: local named-pipe daemon unavailable |
| Worktree/branch/HEAD/index preservation | PASS |

Controller tests ran with the existing bundled Python **3.12.14**, discovered beneath the Codex runtime cache. This satisfies the controller's Python 3.9+ requirement; it does not satisfy or claim the Django Python 3.13 acceptance environment. No Python installation was performed. The existing controller publishing/queue integration tests were not invoked because they create commits/pushes in temporary repositories and execute the publisher; the security and read-only test selections above were run.

The unit tests use generated temporary synthetic values and mock Docker/application command execution. The database fixture remains **s5-synthetic-v1**, with exactly two artificial rows defined in smoke.sh. No owner source ZIP was supplied or accepted. Actual fixture and controller hashes appear below.

## Remaining runtime blockers

The local Docker daemon cannot be reached, so PostgreSQL readiness, role restrictions, persistence and backup/restore execution remain **NOT_RUN**. S0, Python 3.13 and its application dependencies are not integrated in this worktree, so Django acceptance checks remain **NOT_RUN**. actionlint, dependency vulnerability audits and GitHub Actions execution remain **NOT_RUN**; no workflow was pushed or triggered.

Gate B remains NOT_PASSED, Gates C/D/E HOLD, Phase01 BLOCKED, and U03/U10 remain pending owner acceptance. No production setting, owner policy, main branch, old Telegram bot, sibling implementation, running-controller lock, commit, push, merge, deployment or privileged business operation was changed.

## Artifact identities

| Artifact | SHA256 |
| --- | --- |
| infra/dev/smoke.sh | ff58beb72121cf65244c7eb414e14e13bc7c8d244f343da21608fc277944b8bf |
| infra/dev/tests/infra.test.mjs | 5b3f347c077618b0ea3cebfbad74c733889f4cce5e1b6e74e4c41500fc6dd166 |
| infra/dev/checks.mjs | 1f50a5bc0d371c465081c80fd2720c53a259e6bd62e28f5d0dbdeeeb5ac8affa |
| .github/workflows/s5-ci.yml | 73f09fd47051c50f2df8ac200e10d089db7816ee525a35695aa94867c1c720b0 |
| controller/fatwa_autopilot.py | 9e3d3fa6863f44aff87421f864ca26dc7969dd52a059f213d13aa39eeeefbdf8 |
| controller/tests/test_publication_security.py | 912ef1dc041ea341c7f9dfa986f83cc70bb715d8d9e77966d6778c6151fef459 |
