import assert from "node:assert/strict";
import {createHash} from "node:crypto";

export const widths = [1280, 375, 320];
const roots = ["editorial-queue", "editorial-search", "editorial-workbench",
  "editorial-export", "research-bridge", "reference-triage"];
const route = new RegExp(`^/dev/(?:${roots.join("|")})(?:/(?:[a-z0-9-]+|style\\.css|report\\.json|manifest\\.json|cases\\.csv|batches\\.csv))?$`);
export function permitted(request, origin, catalog = false) {
  try {
    const url = new URL(request.url);
    return ["GET", "HEAD"].includes(request.method) && url.origin === origin &&
      !url.username && !url.password && !/%|\\/.test(url.pathname) &&
      (route.test(url.pathname) && !["stored","workflow-audit"].includes(url.pathname.split("/").at(-1)) ||
       catalog && (/^\/fiqh(?:\/nodes\/[1-3](?:\/children)?)?$/.test(url.pathname) ||
         url.pathname === "/assets/django_htmx/htmx-2.min.js" ||
         /^\/assets\/reference\/(?:style.css|tree.js|catalog.css|catalog.js|django-api.mjs)$/.test(url.pathname) ||
         /^\/api\/v1\/fiqh\/(?:books|roots|nodes\/[1-3](?:\/children)?)$/.test(url.pathname)));
  } catch { return false; }
}

export const digest = text => createHash("sha256").update(text, "utf8").digest("hex");
export function assertViewport(metrics, width) {
  assert.equal(metrics.inner, width, "actual viewport width");
  // Classic desktop scrollbars may subtract width; mobile must be exact.
  assert.ok(metrics.client <= width && metrics.client >= width - 20, "layout viewport width");
  if (width < 500) assert.equal(metrics.client,width,"mobile layout viewport width");
  assert.ok(metrics.scroll <= metrics.inner, "viewport overflow");
}
export function assertPacket(actual, expected, revision) {
  assert.equal(actual.synthetic_only, true);
  for (const field of ["identity", "source", "intake", "snapshots", "persisted_review"])
    assert.deepEqual(actual[field], expected[field], `packet ${field}`);
  assert.equal(actual.selection.revision, revision);
  assert.equal(digest(actual.source.text), actual.source.text_sha256);
  assert.equal(digest(actual.source.input_text), actual.source.input_sha256);
}

export function outcome(browser, catalog) {
  if ([browser, catalog].includes("FAIL")) return "FAIL";
  return browser === "PASS" && catalog === "PASS" ? "PASS" : "NOT_RUN";
}

// A refused request must have reached Fetch interception, not just failed for
// some unrelated reason (CSP, DNS, or a dead server).
export function assertBlocked(observed, request) {
  assert.ok(observed.some(item => item.method === request.method && item.url === request.url),
    "negative probe did not reach the request guard");
}
