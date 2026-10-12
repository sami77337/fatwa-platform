# AGENTS.md — Fatwa Platform (Codex development branch)

## Mission
Build a professional Arabic-first fatwa and scholarly research platform in measured, testable increments. Follow issue [#1](https://github.com/sami77337/fatwa-platform/issues/1) for the **first isolated engineering mission**. The website design is temporary; final branding/Figma comes **after** completion of accepted functions (owner decision D-070). Deliver code with tests, not visual-only mockups.

## Source of truth / safety gates
- Product has independent **Phase00 Gate B not passed, Gates C/D/E HOLD, Phase01 BLOCKED**. This branch is for a non-production **development spike**. Never deploy, merge to main, turn on privileged actions, or infer owner approvals.
- U03 (48 clauses) + U10 (28 clauses) are **OWNER_APPROVAL_PENDING**. Changes requiring those policies must remain disabled until accepted.
- D-067: MUFTI and ORGANIZER_ADMIN have equivalent administrative hierarchy; ORGANIZER has configurable lower operational access. **Only MUFTI** creates or approves substantive scholarly rulings. Never use wildcard grants.
- All 70 historical permission rows are **DENY_DEFAULT, NONE_CANDIDATE_BINDING_ONLY**. The 58 draft workflow transitions are documentation, not endpoints. `DOMAIN_TRANSACTION` is an internal atomic effect, never a runnable principal.
- D-068: inline AI scholarly citation assistance is a human-reviewed V1 feature **to develop later**. No AI fatwa writing or approval. External ChatGPT integration is V2. No AI/network access needed in current sprint.
- D-069: **book 622** (*Kashshaf al-Qina'*, Ministry of Justice edition) is one reference work's fiqh table of contents; it is NOT the approved global fatwa taxonomy, nor a published fatwa corpus. Only fiqh reference tree in current scope; other sciences deferred until their source is supplied.
- No requester/private case data, no delivery/Telegram/WhatsApp, no fatwa publishing, no user administration, no production migrations. Do not modify `sami77337/telegram-fatwa-bot-v2` or old Phase00 evidence.

## Stack / engineering discipline
- Python 3.13; Django 5.2 LTS modular monolith; PostgreSQL 18 preferred, 17 fallback; psycopg3.
- Django SSR templates with htmx for interactive public catalog; React/TypeScript islands **only when justified** by functional need.
- Arabic RTL, keyboard-accessible, mobile-first functional UI; keep aesthetics plain.
- Services with typed interfaces and explicit domain boundaries. No unsafe implicit state transitions, hidden permission grants, or unreviewed database mutations. Configurable environment secrets and CSP/security defaults. Do not commit keys/tokens or requester data.
- Real Postgres-backed tests and migrations. Pin project dependencies. Lint, format, system checks, unit/integration/UI/security tests in CI. Measure query counts and response performance, do not invent results. Respect crawl/rights limits.

## First Codex task
1. Read issue #1 carefully. Inspect repository and state exactly what is missing.
2. Build production-architectured **development-only** Django foundation for a public read-only reference catalog. No deployment.
3. If provided separately by the owner, validate:
   - `FATWA_BUILD_SPRINT_01_R2_20261011.zip`, SHA256 `2b50ef138d2890156121e784618715e9992e04bed7d437bbf13e5d6250d0e78b`;
   - `FATWA_622_FIQH_COMPLETE_TOC_11397_20261011.zip`, SHA256 `82a797806430635350decdde27d07fe41fb1278838c8173dc4080f9d109957ce`.
   These files **are not yet in the repository**. Do not fabricate or say you tested import against the originals before they are supplied.
4. If source data available, ingest **11,397 title nodes / 32 roots (30 fiqh books + 2 introductions), max depth 5** via audited idempotent import. Preserve source text, source IDs, parent edges, ordering and printed part/page.
5. Expose read-only public views and APIs with safe bounded Arabic search and accessible expandable tree.
6. Run tests, record real output and failing commands. Create **draft PR** from `codex/fatwa-foundation-20261013` targeting `main` for human review only. Do not merge.

## Definition of Done
- Deterministic clean install and startup instructions + `manage.py check`.
- PostgreSQL migrations and integrity tests pass; accurate coverage/CI results.
- User can navigate a source-pinned fiqh hierarchy on desktop/mobile and find an original title without confusing it with a fatwa.
- `POST/PUT/PATCH/DELETE` to non-existent or unauthorized product functionality is rejected, not quietly activated.
- README says which features work, which depend on files/approvals, and which are unimplemented.
- PR contains clear before/after, test evidence, security assumptions, migration plan, known gaps, and an explicit **NOT_DEPLOYED / GATES_HOLD** statement.

## References
- https://github.com/sami77337/fatwa-platform/issues/1
- Decision log: https://docs.google.com/document/d/1IoGNeCbB8dtMuGZ-BuvlInifmfaHbRos18OF1YUCN2Y/edit
- Project timeline: https://docs.google.com/document/d/1QR8XZGRELBG98cZWVRzIQKaVoWAZUBZKQE2QTS4rICA/edit
