# V14 continuation — deterministic private selected-page PDF preview

This is an **optional, private staff verification derivative** on top of the
existing human-confirmed `PdfCitation`. It is not a new original, full-document
redaction, independently approved citation, publication grant or source upload.

## Actual behavior

The original `/document/` and `/review-document/` endpoints remain unchanged.
The original iframe's `#page=N` fragment is still merely a viewer-navigation
hint. The staff desk offers a **second, clearly labelled link** for a one-page
derivative; it is intentionally not named or represented as an original.

- `GET/HEAD /casework/staff/pdf-citations/<uuid>/review-page/`: only a
  currently permitted proposed/confirmed locator for the current draft.
- `GET/HEAD /casework/staff/pdf-citations/<uuid>/page/`: only the current,
  confirmed locator.
- No query string, anonymous access, requester capability, external host, POST,
  cross-case read or public route is accepted.

The source's exact owner, SHA-256, version, parser metadata, physical page index,
case/evidence/current-answer revision, READ_MEDIA/CITE, identity and staff
session are checked by the existing `services.open_pdf` transaction.

`page_only=True` asks an isolated `page_worker` to revalidate the **same
original** and copy only its selected physical page into a transient PDF. The
worker removes annotations/actions metadata, validates the single-page result,
and never writes a derivative to disk. Limits: original <=192000 bytes, 1–10
original pages, derived response <=262144 bytes, six-second parent timeout,
worker three-second CPU and 256MiB address-space limits on Linux. Missing,
malformed, oversized or unsafe PDFs fail closed and **never** fall back to
returning the full original from the selected-page URL.

The service rechecks rights and staff identity **after** the conversion while
still holding the scoped transaction, including the source-expiry guard. The
private `_inline` response keeps `sandbox` CSP, `SAMEORIGIN`, no-store,
noindex and actual derived Content-Length on GET/HEAD. Every access revalidates
current authorization. The immutable original and history are untouched.

## Verification and limitations

The **selected physical PDF object** can be tested deterministically because the
derived document contains exactly one page, copied from original page N. The
unit tests generate three pages with different widths and reject other indices.

This does **not** assert that Chrome's built-in PDF viewer honored `#page=N` in
the *original* multi-page document, nor does it prove a scanned page's text,
printed pagination, visual rendering, semantic content or safe public release.
The selected-page link provides a practical alternative for human inspection.

Tests:
- `apps.pdf_citations.test_page_preview`: isolated producer, malformed/active
  content and bounded-failure checks
- `apps.pdf_citations.tests`: private GET/HEAD, confirmed/proposed state,
  revocation during derivation, error fallback denial, unchanged original
- `apps.pdf_citations.browser_tests`: native RTL actions, one-page authenticated
  byte inspection, withdrawal
- `tests.casework.test_v14_pdf_bindings`: integrated CaseworkGuard and
  current source rights

The V14 workflow includes the pure tests in its real PostgreSQL 17/18 and
protected Chrome matrix. This page describes the implementation contract, not
a claim that an uninspected CI run passed.

**Gate B NOT_PASSED; C/D/E HOLD; Phase01 BLOCKED; NOT_DEPLOYED.**
No public delivery, production data, authority changes, KMS/PITR guarantee,
automatic scholarly approval, new taxonomy, U03 permissions or main merge.
