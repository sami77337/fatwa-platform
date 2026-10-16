import test from "node:test";
import assert from "node:assert/strict";
import { createDjangoAdapter, CatalogError } from "../../apps/reference/static/reference/django-api.mjs";

const edition = { id: 7, edition_key: "test-v1", title: "طبعة اختبار", publisher: "ناشر اختبار",
  work: { source_namespace: "synthetic", source_book_id: "test-622", title_original: "مرجع اختبار", madhhab: "اختبار" },
  heading_count: 40, root_count: 1, max_depth: 5, source_archive_sha256: "a".repeat(64), source_input_sha256: "b".repeat(64) };
const row = (id, parent = null) => ({ id, parent_id: parent, source_id: "synthetic-" + id,
  title: '<script>عنوان اختبار</script>', depth: parent === null ? 1 : 2, position: id * 10,
  source_order: id, children_count: parent === null ? 39 : 0, part: "المقدمة", page: id, page_id: 1000 + id });
const envelope = payload => ({ kind: "SOURCE_BOOK_TOC_NOT_FATWAS", ...payload });
const list = (items, total = items.length, offset = 0, limit = 20) => ({ items, total, count: total, limit, offset,
  next_offset: offset + limit < total ? offset + limit : null, edition });
function harness(custom = () => undefined) {
  const calls = [];
  const fetchImpl = async (href, options) => {
    const url = new URL(href); calls.push({ url, options });
    let payload = custom(url, options);
    if (payload instanceof Response) return payload;
    if (payload === undefined) {
      if (url.pathname.endsWith("/books")) payload = list([edition], 1, 0, 100);
      else if (url.pathname.endsWith("/roots")) payload = list([row(1)], 1, 0, 100);
      else if (url.pathname.endsWith("/children")) payload = { ...list([row(22, 1)], 39, 20), parent: 1 };
      else if (url.pathname.endsWith("/search")) payload = list([row(22, 1)], 1);
      else payload = { node: row(22, 1), ancestors: [row(1), row(22, 1)], edition };
    }
    return new Response(JSON.stringify(envelope(payload)), { headers: { "Content-Type": "application/json" } });
  };
  const adapter = createDjangoAdapter({ origin: "http://localhost:8000", editionId: 7, fetchImpl });
  return { adapter, calls };
}
test("uses real S0 inventory, roots and original named printed part", async () => {
  const { adapter, calls } = harness(); const catalog = await adapter.catalog();
  assert.equal(catalog.books.length, 1); assert.equal(catalog.introductions.length, 0);
  assert.equal(catalog.books[0].source.printed_part, "المقدمة");
  assert.equal(catalog.books[0].source.source_id, "synthetic-1");
  assert.equal(catalog.books[0].position, 9);
  assert.equal(catalog.books[0].source.synthetic, true);
  assert.equal(catalog.books[0].title, '<script>عنوان اختبار</script>');
  for (const { url, options } of calls) {
    assert.equal(url.origin, "http://localhost:8000"); assert.equal(options.method, "GET");
    assert.equal(options.credentials, "omit"); assert.equal(options.redirect, "error");
  }
});
test("child anchor and numeric cursor map to Django query parameters", async () => {
  const { adapter, calls } = harness(); await adapter.catalog();
  const result = await adapter.children("1", { anchorId: "22" });
  assert.equal(result.previous_cursor, "0"); assert.equal(result.next_cursor, null);
  assert.equal(calls.at(-1).url.searchParams.get("anchor"), "22");
  assert.equal(calls.at(-1).url.searchParams.has("offset"), false);
  await adapter.children("1", { cursor: "20" });
  assert.equal(calls.at(-1).url.searchParams.get("offset"), "20");
  await assert.rejects(adapter.children("1", { cursor: "20", anchorId: "22" }), CatalogError);
});
test("maps S0 ancestors including selected node to breadcrumbs", async () => {
  const { adapter } = harness(); await adapter.catalog(); const detail = await adapter.node("22");
  assert.deepEqual(detail.breadcrumbs.map(row => row.id), ["1", "22"]);
});
test("preserves exact Arabic query, selected mode, root, and edition", async () => {
  const { adapter, calls } = harness(); await adapter.catalog();
  await adapter.search(" عُنْوان ", { rootId: "1", mode: "exact" });
  const params = calls.at(-1).url.searchParams;
  assert.equal(params.get("q"), " عُنْوان "); assert.equal(params.get("mode"), "exact");
  assert.equal(params.get("root"), "1"); assert.equal(params.get("edition"), "7");
});
test("empty database stays empty", async () => {
  const adapter = createDjangoAdapter({ origin: "http://localhost:8000", fetchImpl: async () => new Response(JSON.stringify(envelope(list([], 0))), { headers: { "Content-Type": "application/json" } }) });
  assert.deepEqual((await adapter.catalog()).books, []);
});
test("database/API failure is surfaced with no synthetic fallback", async () => {
  const { adapter } = harness(() => new Response("unavailable", { status: 503 }));
  await assert.rejects(adapter.catalog(), error => error.code === "UNAVAILABLE");
});
test("rejects wrong source kind, edition switch, and malformed breadcrumbs", async () => {
  for (const change of [payload => ({ ...payload, edition: { ...edition, id: 8 } }),
    payload => ({ ...payload, items: [{ ...row(1), depth: 6 }] })]) {
    const { adapter } = harness(url => url.pathname.endsWith("/roots") ? change(list([row(1)], 1, 0, 100)) : undefined);
    await assert.rejects(adapter.catalog(), CatalogError);
  }
  const { adapter } = harness(url => /nodes\/22$/.test(url.pathname) ? { node: row(22, 1), ancestors: [row(22, 1)], edition } : undefined);
  await adapter.catalog(); await assert.rejects(adapter.node("22"), CatalogError);
});
test("unknown public fields are dropped", async () => {
  const { adapter } = harness(url => url.pathname.endsWith("/roots") ? list([{ ...row(1), requester: "never-project", answer: "never-project" }], 1, 0, 100) : undefined);
  const catalog = await adapter.catalog(); assert.equal("requester" in catalog.books[0], false);
  assert.equal("answer" in catalog.books[0], false);
});
test("rejects invalid IDs, cursors and query before requests", async () => {
  const { adapter, calls } = harness(); await adapter.catalog(); const before = calls.length;
  await assert.rejects(adapter.children("../1"), CatalogError);
  await assert.rejects(adapter.children("1", { cursor: "-1" }), CatalogError);
  await assert.rejects(adapter.search("x".repeat(161)), error => error.code === "INVALID_QUERY");
  assert.equal(calls.length, before);
});
test("cancellation reaches fetch", async () => {
  let cancelled = false;
  const adapter = createDjangoAdapter({ origin: "http://localhost:8000", fetchImpl: async (_url, options) => {
    cancelled = options.signal.aborted; throw new DOMException("Aborted", "AbortError");
  } });
  const controller = new AbortController(); controller.abort();
  await assert.rejects(adapter.catalog({ signal: controller.signal }), { name: "AbortError" });
  assert.equal(cancelled, true);
});

test("request timeout produces a retryable error", async () => {
  const adapter = createDjangoAdapter({ origin: "http://localhost:8000", timeoutMs: 5,
    fetchImpl: async (_url, { signal }) => new Promise((_resolve, reject) => {
      signal.addEventListener("abort", () => reject(new DOMException("Aborted", "AbortError")), { once: true });
    }) });
  await assert.rejects(adapter.catalog(), error => error.code === "TIMEOUT");
});
