# FATWA Codex parallel execution runbook — 2026-10-13

**Owner mandate:** intensive concurrent engineering, but no rushed unsafe integration. **Seven Codex sessions**, one issue + isolated branch each, draft pull requests only. Root `main` remains untouched until independently reviewed/authorized.

## Shared source and operating context
- [GitHub tasks #1–#7](https://github.com/sami77337/fatwa-platform/issues)
- [Project decision log](https://docs.google.com/document/d/1IoGNeCbB8dtMuGZ-BuvlInifmfaHbRos18OF1YUCN2Y/edit)
- [Execution command center](https://docs.google.com/document/d/1QR8XZGRELBG98cZWVRzIQKaVoWAZUBZKQE2QTS4rICA/edit)
- Catalog: 11,397 titles from book 622, 32 roots = 2 introductions + 30 fiqh books, max depth 5. This is *source index*, not vetted published fatwas.
- Latest local artifacts exist as ChatGPT attachments, **not automatically in GitHub or Codex Cloud**:
  - `FATWA_BUILD_SPRINT_01_R2_20261011.zip`, sha256 `2b50ef138d2890156121e784618715e9992e04bed7d437bbf13e5d6250d0e78b`
  - `FATWA_622_FIQH_COMPLETE_TOC_11397_20261011.zip`, sha256 `82a797806430635350decdde27d07fe41fb1278838c8173dc4080f9d109957ce`
- Feature shape: code-first. Visual UI is temporary, Figma only after all owner-accepted functions are complete, per D-070.
- Gate B runtime not passed, Gate C/D/E HOLD, Phase01 blocked. Sibling development runs are **isolated experiments** without privileged business execution or publishing.

## Concurrent worker table

| Order | Issue | Branch | Owner-owned paths | Output |
|---|---|---|---|---|
| S0 | [#1](https://github.com/sami77337/fatwa-platform/issues/1) | `codex/fatwa-foundation-20261013` | Django config, models, migrations, backend endpoints, minimal templates | Draft PR + test log |
| S1 | [#2](https://github.com/sami77337/fatwa-platform/issues/2) | `codex/s1-fiqh-import-20261013` | `tools/fiqh_import/**` and scoped tests/docs | Deterministic ingest/validator |
| S2 | [#3](https://github.com/sami77337/fatwa-platform/issues/3) | `codex/s2-rtl-public-fixtures-20261013` | `ui_drafts/fiqh/**` and API-contract docs | Accessible functional UI only |
| S3 | [#4](https://github.com/sami77337/fatwa-platform/issues/4) | `codex/s3-contract-validators-20261013` | `contracts/**` and scoped tests/docs | Read-only/deny-by-default validation |
| S4 | [#5](https://github.com/sami77337/fatwa-platform/issues/5) | `codex/s4-security-qa-20261013` | `quality/**` and scoped docs | Independent negative tests + threat model |
| S5 | [#6](https://github.com/sami77337/fatwa-platform/issues/6) | `codex/s5-infra-ci-20261013` | `infra/dev/**`, `.github/workflows/**`, docs/operations | Local PostgreSQL/CI |
| S6 | [#7](https://github.com/sami77337/fatwa-platform/issues/7) | `codex/s6-scope-product-20261013` | `docs/product/**`, `docs/release-plan/**`, `tools/feature_registry/**` | Owner-facing scope, no fake approvals |

## Worker prompt (copy into EACH separate Codex task, substitute issue and branch)
```text
Work in GitHub repo sami77337/fatwa-platform.
Read AGENTS.md. Use ONLY branch: <EXACT_BRANCH>.
Implement ONLY GitHub issue: <ISSUE_URL> and its exclusive path ownership.
Do not modify main or any sibling's files. Do not merge, deploy, or enable private business operations.
Attach/read real source files only if supplied; otherwise use synthetic fixtures and report missing data.
Run actual tests, capture command/results, and open a Draft Pull Request to main.
Report the PR URL, changed paths, passing/failing tests, blocked items and integration contract.
```

## Coordination: safe speed, not destructive concurrency
1. All seven workers may code simultaneously in isolated branches after GitHub is connected and the user opens seven separate Codex sessions/tasks. An issue/branch does **not** imply a worker is running. Avoid launching all agents against one working tree or one branch.
2. No cross-lane edits. Do not add product operation endpoints for draft workflow states; 70 historical rows non-granting, U03/U10 pending. Source security audit gates remain explicit.
3. Source ownership: S0 owns `apps/reference/**`, Django migrations/settings, root dependency files; S1 owns standalone parser only, returns interface contract; S2 owns standalone functional prototype only; S5 owns Compose/CI but may use S0's declared install commands only after they're committed.
4. No rebase/force push/commit to `main` to resolve conflicts. Coordinator stages integration after review.
5. **Integration sequence:** (a) review & integrate S0 foundation in an integration-only branch; (b) apply S1 importer and S5 infrastructure/CI; (c) wire S2 UI and run Chrome/mobile accessibility checks; (d) add S4 QA harness and run full security negatives; (e) keep S3 contract data fail-closed and S6 product scope evidence linked but never grant/progress sensitive features without separately accepted policies.
6. Review `git diff --name-only` from every draft PR. If unauthorized paths altered, return for correction, don't silently merge.
7. For each PR, require explicit checklist with actual: Django check, migration check, PostgreSQL version + integration outcome, import counts if source present, security/ACL negative tests and positive public browsing path, CI lint/type/test status, reproducible clean install. Any absent test: `NOT_RUN`, never PASS.
8. Phase00 reviews/owner contract decisions still gate real Phase01. Present every development PR as **NON_PRODUCTION_DRAFT**.

## Acceptance gate for the coordinator
- S0 Django/PostgreSQL real tests must be evidenced, not asserted.
- Full TOC must validate all **11,397** source title IDs & names before import is called complete.
- Tests must prove public catalog never exposes private fatwa questions, unapproved fatwa versions or user data.
- Source-book index displayed as *one **Hanbali** reference, not as universally sanctioned categorization; edition and citations preserved.
- User chooses which non-required features to remove; generic "excellent" is not exact acceptance.
- No Figma, no deployment, no privileged account grants or provider messages.

**Correct wording:** "Seven tasks and branches ready; Codex has not yet been launched" until actual agent run evidence exists.
