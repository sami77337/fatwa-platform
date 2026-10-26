# FAST8 operator navigation

Authorized specification: assigned operator-navigation lane, base
92fa517ecdefe3f1a92a1ab145ff55943474df44; implement autonomously.

Use the existing queue catalog, bounded search and exact revision selector.
Add a standalone RTL page and app-local URLs/templates, with no shared mount
or settings change. Resolve existing service URLs; show NOT_CONNECTED when
unmounted. Research links describe case-level original/current references;
export links explicitly describe the complete catalog, never a selected revision.

- [x] HTTP tests first: real fixtures, sparse revision selection, missing routes,
  bounded query parsing, GET/HEAD and loopback/production denial before reads.
- [x] Implement list, search pagination, case/revision navigation and service links.
- [x] Run guarded Chrome at 320/375/1280px with keyboard navigation, no database,
  external network or write requests; preserve existing source files unchanged.
- [ ] Independent review, targeted validation, commit/push and one draft PR to
  codex/20261026-fast7-ci-integration-pc1; verify remote SHA and B6/C6/D6.

Only apps/fast8_operator_nav, tools/fast8_operator_nav and tests/fast8_operator_nav
may change. No migrations, deployment, privileges or policy changes.
