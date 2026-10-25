# FAST5 synthetic workflow rehearsal

Goal: execute the owner's FAST5 scope on FAST4 commit
`262fa3d40975cfc0698b045becc2da885760a995` with no persistent writes.

Architecture: reuse the fixed workbench cases, draft transition/history/audit
services, reference diagnostics, and Wave7 pure review transition contract.
Frozen attempts replay deterministically; GET selects a view of the replay,
never applies a command. Preparation and review remain separate dimensions.
`REVIEWED_INTERNAL` never means scholarly approval or reference verification.

Implementation (Python 3.13 / existing Django 5.2):

- Service worker owns `services.py`, package initializers and `test_services.py`:
  test invalid/valid transitions first, then build immutable fixed replays.
- Main worker owns views, URLs, CSS, Arabic templates and `test_views.py`:
  test route/guard/query/text behavior first; add one shared URL include.
- Browser worker owns `test_browser.py` and `browser.mjs`: reuse existing
  sandboxed Chrome/CDP harness, test mobile, keyboard and exact source links.
- Run new and directly affected tests, Django checks and scoped Ruff.
- Perform ONE independent final review; fix findings, then commit/push and
  open ONE Draft PR targeting `codex/20261025-fast4-integration-pc2`.

Review focus: blocked intake cannot acquire a draft; rejected transitions leave
state unchanged; query selectors cannot supply events or records; Arabic CRLF
and combining characters survive HTML; production/non-loopback requests fail
before fixture loading. No models, migrations, persistent writes, POST actions,
permission grants, citations or approval claims. Existing protected files stay
unchanged apart from the explicitly allowed additive route include.

Gate B NOT_PASSED; C/D/E HOLD; Phase01 BLOCKED;
SCOPE_DEVIATION_HOLD; NOT_DEPLOYED.
