import {permittedRequest} from "../wave7/cdp.mjs";

export function allowedRequest(request, origin) {
  try {
    if (!permittedRequest(request, origin)) return false;
    const {pathname} = new URL(request.url);
    return /^\/dev\/editorial-workbench(?:\/[a-zA-Z0-9_.-]+)?$/.test(pathname)
      || /^\/dev\/editorial-queue(?:\/[a-zA-Z0-9_.-]+)?$/.test(pathname)
      || /^\/dev\/reference-triage(?:\/[a-zA-Z0-9_.-]+)?$/.test(pathname)
      || /^\/fiqh(?:\/nodes\/\d+(?:\/children)?)?$/.test(pathname)
      || /^\/api\/v1\/fiqh\/(?:books|roots|search|nodes\/\d+(?:\/children)?)$/.test(pathname)
      || /^\/assets\/reference\/[a-zA-Z0-9_.-]+$/.test(pathname)
      || pathname === "/assets/django_htmx/htmx-2.min.js"
      || pathname === "/favicon.ico";
  } catch { return false; }
}

export function aggregateResult(cases) {
  if (cases.some(item => item.result === "FAIL")) return "FAIL";
  return cases.length && cases.every(item => item.result === "PASS") ? "PASS" : "NOT_RUN";
}

export function catalogIdentity(inventory) {
  const edition = inventory?.items?.[0];
  return inventory?.items?.length === 1 && edition?.work?.source_namespace === "wave7-synthetic-toc"
    && edition.work.source_book_id === "622" && edition.heading_count === 3
    && edition.edition_key === "wave7-synthetic-edition-v1"
    && edition.source_archive_sha256 === "b".repeat(64) && edition.source_input_sha256 === "a".repeat(64);
}
