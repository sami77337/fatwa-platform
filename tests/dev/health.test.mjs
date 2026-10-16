import test from "node:test";
import assert from "node:assert/strict";
import { EventEmitter } from "node:events";
import { healthcheck, readLocal, sourcePins, origin } from "../../tools/dev/health.mjs";

function fixture(change = () => {}) {
  const edition = { id: 1, source_archive_sha256: sourcePins.archive, source_input_sha256: sourcePins.input,
    heading_count: 11397, root_count: 32, max_depth: 5, work: { source_namespace: "shamela", source_book_id: "622" } };
  const sample = { id: 1, parent_id: null, title: "كتاب اختبار", depth: 1, children_count: 2 };
  const roots = Array.from({ length: 32 }, (_, i) => ({ ...sample, id: i + 1, children_count: i ? 0 : 2 }));
  const calls = [];
  const transport = async route => {
    const url = new URL(route, origin);
    calls.push(url);
    if (["/", "/fiqh"].includes(url.pathname)) return {
      status: 200, type: "text/html; charset=utf-8", body: '<html lang="ar" dir="rtl">عنوان</html>',
    };
    const page = (items, limit, total = items.length) => ({ items, limit, total, offset: 0, edition });
    let status = 200, data;
    if (url.searchParams.get("limit") === "101") {
      status = 400; data = { error: "invalid_query" };
    } else if (url.pathname === "/healthz") data = { alive: true, read_only: true };
    else if (url.pathname === "/readyz") data = { database_reachable: true };
    else if (url.pathname === "/api/v1/status") data = { read_only: true, sensitive_write_routes_enabled: false, fatwa_publications_available: false };
    else if (url.pathname.endsWith("/books")) data = page([edition], 100);
    else if (url.pathname.endsWith("/roots")) data = page(roots, 100);
    else if (url.pathname.endsWith("/children")) data = { ...page([{ id: 90, parent_id: 1 }], 20, 2), parent: 1 };
    else if (url.pathname.endsWith("/search")) data = { ...page([sample], 100), mode: url.searchParams.get("mode"), query: sample.title };
    else data = { node: sample, ancestors: [sample], edition };
    data.kind = "SOURCE_BOOK_TOC_NOT_FATWAS";
    change(data, url);
    return { status, type: "application/json; charset=utf-8", body: JSON.stringify(data) };
  };
  return { transport, calls };
}
test("health checks homepage, fiqh, readiness and bounded pinned catalog APIs using read-only transport", async () => {
  const { transport, calls } = fixture();
  const report = await healthcheck({ transport });
  assert.equal(report.result, "PASS");
  assert.equal(report.method, "GET_ONLY");
  assert.equal(report.checks.length, 14);
  assert.equal(report.catalog_metadata.result, "PASS");
  assert.equal(report.django_postgresql_tests, "NOT_RUN");
  assert.equal(report.source_archive_verification, "NOT_RUN");
  assert.equal(report.full_source_row_comparison, "NOT_RUN");
  assert.deepEqual(calls.filter(url => url.pathname.endsWith("/search")).map(url => url.searchParams.get("mode")),
    ["exact", "literal", "normalized"]);
  assert.ok(calls.every(url => url.origin === origin));
  assert.ok(calls.every(url => !url.searchParams.has("limit") ||
    [20, 100, 101].includes(Number(url.searchParams.get("limit")))));
});
test("valid HTTP behavior remains separate from an incorrect real-source count", async () => {
  const { transport } = fixture(data => {
    if (data.items?.[0]?.work) data.items[0].heading_count = 11396;
  });
  const report = await healthcheck({ transport });
  assert.equal(report.http_behavior, "PASS");
  assert.equal(report.catalog_metadata.result, "FAIL");
  assert.equal(report.result, "FAIL");
});
test("false readiness, privileged status or wrong edition fails even with HTTP 200", async () => {
  for (const change of [
    (data, url) => { if (url.pathname === "/readyz") data.database_reachable = false; },
    (data, url) => { if (url.pathname.endsWith("/status")) data.sensitive_write_routes_enabled = true; },
    (data, url) => { if (url.pathname.endsWith("/roots")) data.edition = { ...data.edition, id: 9 }; },
    (data, url) => { if (url.pathname.endsWith("/children")) data.items[0].parent_id = 999; },
  ]) {
    const report = await healthcheck(fixture(change));
    assert.equal(report.result, "FAIL");
    assert.ok(report.checks.some(check => check.result === "FAIL"));
  }
});
test("a synthetic kind or missing source edition is not reported as source-backed success", async () => {
  const { transport } = fixture((data, url) => {
    if (url.pathname.endsWith("/books")) data.kind = "SYNTHETIC_FIXTURE";
  });
  const report = await healthcheck({ transport });
  assert.equal(report.result, "FAIL");
  assert.equal(report.catalog_metadata.result, "NOT_RUN");
});
test("malformed, oversized page and missing search results fail visibly", async () => {
  for (const change of [
    (data, url) => { if (url.pathname.endsWith("/roots")) data.items.push(data.items[0]); },
    (data, url) => { if (url.pathname.endsWith("/search")) data.items = []; },
    (data, url) => { if (url.pathname.endsWith("/roots")) data.limit = 10000; },
  ]) assert.equal((await healthcheck(fixture(change))).result, "FAIL");
});
test("privacy: raw error, response body and title query never enter the health report", async () => {
  const broken = await healthcheck({ transport: async () => { throw Error("password=synthetic-private-response"); } });
  assert.ok(!JSON.stringify(broken).includes("synthetic-private"));
  const fake = fixture((data, url) => {
    if (url.pathname.endsWith("/books")) data.items[0].heading_count = "synthetic-private-response";
  });
  const report = await healthcheck(fake);
  assert.equal(report.catalog_metadata.observed_counts.headings, null);
  assert.ok(!JSON.stringify(report).includes("synthetic-private"));
  assert.ok(!JSON.stringify(report).includes("كتاب اختبار"));
});
test("unavailable site records failures without false PASS or test-database claims", async () => {
  const report = await healthcheck({ transport: async () => { throw Error("HTTP_UNAVAILABLE"); } });
  assert.equal(report.result, "FAIL");
  assert.equal(report.catalog_metadata.result, "NOT_RUN");
  assert.equal(report.django_postgresql_tests, "NOT_RUN");
});
function requestHarness({ status = 200, chunks = ["ok"], never = false, interrupted = false } = {}) {
  const calls = [];
  const requestImpl = (options, callback) => {
    calls.push(options);
    const request = new EventEmitter();
    request.destroy = () => {};
    request.end = () => {
      if (never) return;
      queueMicrotask(() => {
        const response = new EventEmitter();
        response.statusCode = status;
        response.headers = { "content-type": "text/html" };
        response.destroy = () => {};
        callback(response);
        for (const chunk of chunks) response.emit("data", Buffer.from(chunk));
        if (interrupted) response.emit("error", Error("synthetic-private-socket-message"));
        else response.emit("end");
      });
    };
    return request;
  };
  return { calls, requestImpl };
}
test("actual HTTP adapter fixes IPv4 loopback and port 8000, GET, no cookies/auth/proxy or pooling", async () => {
  const { calls, requestImpl } = requestHarness();
  const response = await readLocal("/fiqh", { requestImpl });
  assert.equal(response.body, "ok");
  assert.deepEqual(calls, [{
    hostname: "127.0.0.1", port: 8000, path: "/fiqh", method: "GET",
    headers: { Accept: "application/json,text/html", "Cache-Control": "no-store" }, agent: false,
  }]);
});
test("absolute URLs, network-path redirects and injected request paths are rejected before connecting", () => {
  for (const route of ["http://remote.invalid", "//remote.invalid/path", "/\\remote", "/fiqh\r\nsecret", "/fiqh#fragment"]) {
    assert.throws(() => readLocal(route, { requestImpl: () => assert.fail("must not connect") }));
  }
});
test("redirect responses are returned as failures to callers without following Location", async () => {
  const { calls, requestImpl } = requestHarness({ status: 302 });
  assert.equal((await readLocal("/fiqh", { requestImpl })).status, 302);
  assert.equal(calls.length, 1);
});
test("response size and total request deadlines are enforced", async () => {
  await assert.rejects(readLocal("/fiqh", { ...requestHarness({ chunks: ["12345"] }), maxBytes: 4 }),
    /HTTP_RESPONSE_TOO_LARGE/);
  await assert.rejects(readLocal("/fiqh", { ...requestHarness({ never: true }), timeoutMs: 5 }),
    /HTTP_TIMEOUT/);
});
test("socket failures omit underlying raw details", async () => {
  await assert.rejects(readLocal("/fiqh", requestHarness({ interrupted: true })),
    error => error.message === "HTTP_RESPONSE_INTERRUPTED");
});

test("HTTP failure records the actual bounded status without retaining the body", async () => {
  const report = await healthcheck({ transport: async () => ({
    status: 503, type: "text/plain", body: "synthetic-private-diagnostic",
  }) });
  assert.equal(report.result, "FAIL");
  assert.equal(report.checks[0].status, 503);
  assert.ok(!JSON.stringify(report).includes("synthetic-private"));
});
