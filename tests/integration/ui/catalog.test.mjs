import test from "node:test";
import assert from "node:assert/strict";
import { mount, MAX_TREE_ITEMS } from "../../../apps/reference/static/reference/catalog.js";
import { documentHarness, settle, deferred } from "./dom-harness.mjs";

// Explicit test-only graph: 25 non-contiguous sibling positions and a depth-five path.
const source = { work_title: "مرجع اصطناعي للاختبار", edition: "طبعة اختبار", publisher: "ناشر اختبار", madhhab: "اختبار", source_id: "INTERNAL-SOURCE-KEY", page_id: 7654321, printed_part: "المقدمة", printed_page: 4 };
function fixture() {
  const graph = new Map();
  const row = (id, parent, depth, title) => ({ id: String(id), parent_id: parent === null ? null : String(parent), depth, title, position: id * 10, source, child_count: 0, has_children: false });
  graph.set("1", row(1, null, 1, "جذر اختبار"));
  for (let id = 2; id <= 26; id++) graph.set(String(id), row(id, 1, 2, "فرع اختبار " + id));
  for (const [id, parent, depth] of [[27, 26, 3], [28, 27, 4], [29, 28, 5]]) graph.set(String(id), row(id, parent, depth, id === 29 ? '<img src=x onerror="alert(1)"> عنوان عربي' : "مسار اختبار " + id));
  graph.set("90", row(90, null, 1, "مقدمة اختبار مستقلة"));
  const children = id => [...graph.values()].filter(node => node.parent_id === id);
  for (const node of graph.values()) { node.child_count = children(node.id).length; node.has_children = node.child_count > 0; }
  const page = (items, offset = 0) => ({ items: items.slice(offset, offset + 20).map((node, i) => ({ ...node, sibling_ordinal: offset + i + 1, sibling_total: items.length })), total: items.length, offset, limit: 20, previous_cursor: offset ? String(Math.max(0, offset - 20)) : null, next_cursor: offset + 20 < items.length ? String(offset + 20) : null });
  const calls = [];
  const adapter = {
    async catalog() { return { books: [graph.get("1")], introductions: [graph.get("90")], source: { id: 7 }, totals: { nodes: graph.size } }; },
    async children(id, { cursor = null, anchorId = null, signal } = {}) { calls.push({ id, cursor, anchorId, signal }); const items = children(id); const offset = anchorId === null ? Number(cursor ?? 0) : Math.floor(items.findIndex(node => node.id === anchorId) / 20) * 20; return page(items, offset); },
    async node(id) { const node = graph.get(id); if (!node) throw Object.assign(Error("missing"), { code: "NOT_FOUND" }); const breadcrumbs = [node]; for (let parent = graph.get(node.parent_id); parent; parent = graph.get(parent.parent_id)) breadcrumbs.unshift(parent); return { node, breadcrumbs }; },
    async search(query, options) { calls.push({ query, ...options }); return page(query === "فارغ" ? [] : query === "عميق" ? [graph.get("29")] : [...graph.values()].filter(node => node.depth === 2), Number(options.cursor ?? 0)); },
  };
  return { adapter, calls, graph };
}
const get = (doc, id) => doc.getElementById(id);
const items = doc => get(doc, "tree").querySelectorAll('[role="treeitem"]');
const item = (doc, id) => items(doc).find(node => node.dataset.id === id);
async function setup(options) { const fixtureData = fixture(), doc = documentHarness(options?.url); let shown = 0; const app = mount(fixtureData.adapter, doc, { initialNode: options?.initialNode ?? null, onCatalog() { shown++; } }); await app.ready; return { ...fixtureData, doc, app, shown: () => shown }; }

test("initial real-UI code renders nested links, one tab stop, citation and no internal keys", async () => {
  const { doc, shown, app } = await setup();
  assert.equal(shown(), 1); assert.equal(items(doc).length, 21); assert.equal(items(doc).filter(node => node.tabIndex === 0).length, 1);
  assert.equal(get(doc, "books").querySelector("a").getAttribute("href"), "/fiqh/nodes/1?edition=7");
  assert.equal(doc.defaultView.location.pathname, "/fiqh"); assert.equal(doc.activeElement, null);
  assert.match(get(doc, "reference-content").textContent, /مرجع اصطناعي للاختبار.*المقدمة/);
  assert.doesNotMatch(get(doc, "reference-content").textContent, /INTERNAL-SOURCE-KEY|7654321|معرّف|طبعة اختبار|ناشر اختبار/);
  app.destroy();
});
test("RTL hierarchical keyboard moves focus independently of selection, expands, collapses and activates", async () => {
  const { doc, app } = await setup(); item(doc, "1").focus();
  item(doc, "1").key("ArrowRight"); assert.equal(items(doc).length, 1);
  item(doc, "1").key("ArrowLeft"); await settle(); assert.equal(items(doc).length, 21);
  item(doc, "1").key("ArrowLeft"); assert.equal(doc.activeElement.dataset.id, "2");
  doc.activeElement.key("ArrowRight"); assert.equal(doc.activeElement.dataset.id, "1");
  doc.activeElement.key("ArrowDown"); assert.equal(doc.activeElement.dataset.id, "2");
  assert.equal(item(doc, "1").getAttribute("aria-selected"), "true"); assert.equal(doc.defaultView.history.length, 1);
  doc.activeElement.key("End"); assert.equal(doc.activeElement.dataset.id, "21");
  doc.activeElement.key("Home"); assert.equal(doc.activeElement.dataset.id, "1");
  doc.activeElement.key("Enter"); assert.equal(items(doc).length, 1);
  doc.activeElement.key(" "); await settle(); assert.equal(items(doc).length, 21);
  doc.activeElement.key("ArrowDown"); doc.activeElement.key("Enter");
  assert.equal(item(doc, "2").getAttribute("aria-selected"), "true"); assert.equal(doc.defaultView.location.pathname, "/fiqh/nodes/2");
  assert.equal(items(doc).filter(node => node.tabIndex === 0).length, 1); app.destroy();
});
test("paging uses ordinals rather than gapped source positions and moves focus to parent", async () => {
  const { doc, app } = await setup(); get(doc, "tree-pagination").querySelector("button").click(); await settle();
  assert.equal(items(doc).length, 6); assert.equal(item(doc, "22").getAttribute("aria-posinset"), "21");
  assert.equal(item(doc, "26").getAttribute("aria-posinset"), "25"); assert.equal(item(doc, "26").getAttribute("aria-setsize"), "25");
  assert.equal(doc.activeElement.dataset.id, "1"); get(doc, "tree-pagination").querySelector("button").click(); await settle();
  assert.equal(items(doc).length, 21); app.destroy();
});
test("deep link reveals anchored sibling pages, depth five, all ancestor pagers and escaped title text", async () => {
  const { doc, calls, app } = await setup({ initialNode: "29", url: "http://localhost/fiqh/nodes/29?edition=7" });
  assert.deepEqual(calls.filter(call => call.anchorId).map(call => [call.id, call.anchorId]), [["1", "26"], ["26", "27"], ["27", "28"], ["28", "29"]]);
  assert.equal(item(doc, "29").getAttribute("aria-level"), "5"); assert.equal(item(doc, "26").getAttribute("aria-posinset"), "25");
  assert.equal(items(doc).filter(node => node.tabIndex === 0).length, 1); assert.ok(items(doc).length <= MAX_TREE_ITEMS);
  assert.equal(get(doc, "breadcrumbs").querySelectorAll("li").length, 6);
  assert.equal(get(doc, "tree-pagination").querySelectorAll("div").length, 4);
  assert.match(get(doc, "reference-content").textContent, /<img src=x/); assert.equal(get(doc, "reference-content").querySelectorAll("img").length, 0);
  get(doc, "tree-pagination").querySelector("button").click(); await settle();
  assert.equal(item(doc, "29"), undefined); assert.equal(items(doc).length, 21); app.destroy();
});
test("direct link to a branch displays its children immediately", async () => {
  const { doc, app } = await setup({ initialNode: "26" }); assert.ok(item(doc, "27")); assert.equal(item(doc, "26").getAttribute("aria-expanded"), "true"); app.destroy();
});
test("search result native link reveals deep path and modified click preserves browser navigation", async () => {
  const { doc, app } = await setup(); get(doc, "search-query").value = "عميق"; get(doc, "search-form").dispatch("submit"); await settle();
  const result = get(doc, "search-results").querySelector("a"); assert.equal(result.getAttribute("href"), "/fiqh/nodes/29?edition=7");
  assert.equal(result.click({ ctrlKey: true }).defaultPrevented, false); assert.equal(doc.defaultView.location.pathname, "/fiqh");
  result.click(); await settle(); assert.equal(doc.activeElement.dataset.id, "29"); assert.equal(doc.defaultView.location.pathname, "/fiqh/nodes/29"); app.destroy();
});
test("back/forward restores path, expanded pages, citations and search results", async () => {
  const { doc, app } = await setup(); get(doc, "search-query").value = "عميق"; get(doc, "search-form").dispatch("submit"); await settle();
  get(doc, "search-results").querySelector("a").click(); await settle();
  get(doc, "introductions").querySelector("a").click(); await settle(); assert.equal(items(doc).length, 1);
  await doc.defaultView.history.back(); assert.equal(doc.defaultView.location.pathname, "/fiqh/nodes/29"); assert.ok(item(doc, "29"));
  assert.equal(item(doc, "26").getAttribute("aria-posinset"), "25"); assert.equal(get(doc, "search-query").value, "عميق"); assert.ok(get(doc, "search-results").querySelector("a"));
  await doc.defaultView.history.back(); assert.equal(doc.defaultView.location.pathname, "/fiqh"); assert.equal(items(doc).length, 21);
  await doc.defaultView.history.forward(); assert.ok(item(doc, "29")); assert.match(get(doc, "reference-content").textContent, /<img/); app.destroy();
});
test("search pagination retains submitted mode and scope after input controls change", async () => {
  const { doc, calls, app } = await setup(); get(doc, "search-query").value = "عنوان"; get(doc, "search-mode").value = "exact"; get(doc, "search-scope").value = "1";
  get(doc, "search-form").dispatch("submit"); await settle(); get(doc, "search-mode").value = "literal"; get(doc, "search-scope").value = "90";
  get(doc, "search-results").querySelector("button").click(); await settle();
  const call = calls.filter(call => call.query).at(-1); assert.equal(call.mode, "exact"); assert.equal(call.rootId, "1"); assert.equal(call.cursor, "20");
  assert.equal(get(doc, "search-results").querySelector("h3"), doc.activeElement); app.destroy();
});
test("child request failure keeps existing tree, resets busy and retries", async () => {
  const { doc, adapter, app } = await setup(); const original = adapter.children; adapter.children = async () => { throw Error("unavailable"); };
  get(doc, "tree-pagination").querySelector("button").click(); await settle(); assert.equal(items(doc).length, 21);
  assert.equal(get(doc, "tree-region").getAttribute("aria-busy"), "false"); assert.ok(get(doc, "error").querySelector("button"));
  adapter.children = original; get(doc, "error").querySelector("button").click(); await settle(); assert.equal(items(doc).length, 6); assert.equal(get(doc, "error").textContent, ""); app.destroy();
});
test("initial child failure leaves SSR visible and visible retry completes initialization", async () => {
  const { adapter } = fixture(); const original = adapter.children; adapter.children = async () => { throw Error("offline"); };
  const doc = documentHarness(); let shown = 0; const app = mount(adapter, doc, { onCatalog() { shown++; } }); await app.ready;
  assert.equal(shown, 0); assert.ok(get(doc, "request-status").querySelector("button")); adapter.children = original;
  get(doc, "request-status").querySelector("button").click(); await settle(); assert.equal(shown, 1); assert.equal(items(doc).length, 21); app.destroy();
});
test("stale tree response cannot replace a newer root even if transport ignores abort", async () => {
  const { doc, adapter, app } = await setup(); const original = adapter.children, pending = deferred(); adapter.children = () => pending.promise;
  get(doc, "tree-pagination").querySelector("button").click(); get(doc, "introductions").querySelector("a").click(); await settle();
  pending.resolve(await original("1")); await settle(); assert.equal(items(doc).length, 1); assert.equal(item(doc, "90").getAttribute("aria-selected"), "true");
  assert.equal(get(doc, "tree-region").getAttribute("aria-busy"), "false"); app.destroy();
});
test("empty, invalid and failed searches expose truthful states, retry and clear cancel late results", async () => {
  const { doc, adapter, app } = await setup(); get(doc, "search-query").value = "فارغ"; get(doc, "search-form").dispatch("submit"); await settle(); assert.match(get(doc, "search-results").textContent, /لم نعثر/);
  adapter.search = async () => { throw Object.assign(Error("query"), { code: "INVALID_QUERY" }); }; get(doc, "search-form").dispatch("submit"); await settle(); assert.equal(get(doc, "search-query").getAttribute("aria-invalid"), "true");
  get(doc, "clear-search").click(); assert.equal(get(doc, "search-query").getAttribute("aria-invalid"), null); assert.equal(doc.activeElement, get(doc, "search-query"));
  adapter.search = async () => { throw Error("offline"); }; get(doc, "search-form").dispatch("submit"); await settle(); assert.match(get(doc, "error").textContent, /تعذّر البحث/);
  const pending = deferred(); adapter.search = () => pending.promise; get(doc, "error").querySelector("button").click(); assert.equal(get(doc, "search-results").getAttribute("aria-busy"), "true");
  get(doc, "clear-search").click(); pending.resolve({ items: [], total: 0, offset: 0, next_cursor: null, previous_cursor: null }); await settle();
  assert.equal(get(doc, "search-results").textContent, ""); assert.equal(get(doc, "search-results").getAttribute("aria-busy"), "false"); app.destroy();
});
test("empty catalog stays empty without a tree role or invented content", async () => {
  const doc = documentHarness(); const app = mount({ catalog: async () => ({ books: [], introductions: [], source: null, totals: { nodes: 0 } }) }, doc); await app.ready;
  assert.equal(items(doc).length, 0); assert.equal(get(doc, "tree").getAttribute("role"), null); assert.equal(get(doc, "search-form").hidden, true);
  assert.match(get(doc, "tree-region").textContent, /لم يُحمّل/); app.destroy();
});
test("catalog failure and missing deep heading never announce successful initialization", async () => {
  for (const missing of [false, true]) { const { adapter } = fixture(); if (!missing) adapter.catalog = async () => { throw Error("offline"); };
    const doc = documentHarness(); let shown = false; const app = mount(adapter, doc, { initialNode: missing ? "999" : null, onCatalog() { shown = true; } }); await app.ready;
    assert.equal(shown, false); assert.ok(get(doc, "request-status").querySelector("button")); assert.equal(get(doc, "tree-region").getAttribute("aria-busy"), "false"); app.destroy(); }
});

test("back navigation aborts pending reveal and ignores its late result", async () => {
  const { doc, adapter, app } = await setup(); get(doc, "introductions").querySelector("a").click(); await settle();
  const original = adapter.node, pending = deferred(); adapter.node = () => pending.promise;
  get(doc, "breadcrumbs").querySelector("a").click(); await settle();
  // Home selected a real root; launch another result from the preserved search area.
  get(doc, "search-query").value = "عميق"; get(doc, "search-form").dispatch("submit"); await settle();
  get(doc, "search-results").querySelector("a").click(); await settle();
  await doc.defaultView.history.back(); const path = doc.defaultView.location.pathname;
  pending.resolve(await original("29")); await settle(); assert.equal(doc.defaultView.location.pathname, path); assert.equal(item(doc, "29"), undefined);
  assert.equal(get(doc, "tree-region").getAttribute("aria-busy"), "false"); app.destroy();
});
test("history storage failure leaves native links and tree navigation usable", async () => {
  const { adapter } = fixture(), doc = documentHarness(); doc.defaultView.history.replaceState = () => { throw Error("history unavailable"); }; doc.defaultView.history.pushState = () => { throw Error("history unavailable"); };
  const app = mount(adapter, doc); await app.ready; assert.equal(items(doc).length, 21);
  get(doc, "introductions").querySelector("a").click(); await settle(); assert.equal(items(doc).length, 1); assert.equal(get(doc, "reference-content").querySelector("a").getAttribute("href"), "/fiqh/nodes/90?edition=7"); app.destroy();
});


test("copy link falls back to a selectable absolute reference URL", async () => {
  const { doc, app } = await setup({ initialNode: "29" });
  get(doc, "reference-content").querySelector("button").click(); await settle();
  const field = get(doc, "reference-content").querySelector("input");
  assert.equal(field.value, "http://localhost/fiqh/nodes/29?edition=7");
  assert.equal(field.getAttribute("readonly"), ""); assert.equal(doc.activeElement, field);
  app.destroy();
});

test("reload recovers saved search and deep branch without stealing focus", async () => {
  const { doc, adapter, app } = await setup();
  get(doc, "search-query").value = "عميق"; get(doc, "search-form").dispatch("submit"); await settle();
  get(doc, "search-results").querySelector("a").click(); await settle();
  app.destroy(); doc.activeElement = null;
  const reloaded = mount(adapter, doc, { initialNode: "29" }); await reloaded.ready;
  assert.equal(get(doc, "search-query").value, "عميق"); assert.ok(get(doc, "search-results").querySelector("a"));
  assert.ok(item(doc, "29")); assert.equal(doc.activeElement, null); reloaded.destroy();
});

test("reading tools copy exact synthetic heading metadata and print without changing tree/history", async () => {
  const { doc, app, graph } = await setup({ initialNode: "29" });
  const written = []; let printed = 0;
  doc.defaultView.navigator = { clipboard: { async writeText(text) { written.push(text); } } };
  doc.defaultView.print = () => { printed++; };
  const content = get(doc, "reference-content"), controls = content.querySelectorAll("button");
  const before = structuredClone(doc.defaultView.history.state);
  controls[1].click(); await settle();
  assert.equal(written[0], source.work_title + "\nالعنوان الأصلي: " + graph.get("29").title + "\nالجزء: " + source.printed_part + "، الصفحة المطبوعة: " + new Intl.NumberFormat("ar", { useGrouping: false }).format(4));
  controls[0].click(); await settle();
  assert.equal(written[1], "http://localhost/fiqh/nodes/29?edition=7");
  assert.match(content.querySelector('[role="status"]').textContent, /تم نسخ/);
  controls[2].click(); assert.equal(printed, 1);
  assert.deepEqual(doc.defaultView.history.state, before);
  assert.equal(item(doc, "29").getAttribute("aria-selected"), "true");
  assert.equal(content.querySelectorAll("img").length, 0); app.destroy();
});

test("clipboard rejection provides one readonly manual field and print failure gives feedback", async () => {
  const { doc, app } = await setup();
  doc.defaultView.navigator = { clipboard: { async writeText() { throw Error("denied"); } } };
  const content = get(doc, "reference-content"), controls = content.querySelectorAll("button");
  controls[1].click(); await settle(); controls[1].click(); await settle();
  assert.equal(content.querySelectorAll("textarea").length, 1);
  const field = content.querySelector("textarea");
  assert.equal(field.getAttribute("readonly"), ""); assert.equal(field.getAttribute("dir"), "rtl");
  assert.equal(doc.activeElement, field); assert.match(field.value, /العنوان الأصلي/);
  assert.match(content.querySelector('[role="status"]').textContent, /Tab/);
  controls[2].click(); assert.match(content.querySelector('[role="status"]').textContent, /المتصفح/);
  app.destroy();
});

test("late clipboard rejection does not move focus from newly selected heading", async () => {
  const { doc, app } = await setup(); const pending = deferred();
  doc.defaultView.navigator = { clipboard: { writeText() { return pending.promise; } } };
  get(doc, "reference-content").querySelectorAll("button")[1].click();
  get(doc, "introductions").querySelector("a").click(); await settle();
  const focused = doc.activeElement;
  pending.reject(Error("denied")); await settle();
  assert.equal(doc.activeElement, focused);
  assert.equal(get(doc, "reference-content").querySelector("textarea"), null); app.destroy();
});


test("D4 native filters retain submitted values across paging, history and retry", async () => {
  const { doc, calls, adapter, app } = await setup();
  get(doc, "search-query").value = "  عنوان  ";
  get(doc, "search-depth").value = "2"; get(doc, "search-has_children").value = "false";
  get(doc, "search-depth").focus();
  assert.equal(get(doc, "search-depth").key("ArrowDown").defaultPrevented, false);
  get(doc, "search-form").dispatch("submit"); await settle();
  let url = doc.defaultView.location;
  assert.equal(url.searchParams.get("depth"), "2"); assert.equal(url.searchParams.get("has_children"), "false");
  assert.equal(url.searchParams.get("q"), "  عنوان  ");
  get(doc, "search-depth").value = "5"; get(doc, "search-has_children").value = "true";
  get(doc, "search-results").querySelector("button").click(); await settle();
  let call = calls.filter(call => call.query).at(-1);
  assert.equal(call.depth, 2); assert.equal(call.hasChildren, false); assert.equal(call.cursor, "20");
  assert.equal(get(doc, "search-depth").value, "2");
  get(doc, "search-depth").value = "5"; get(doc, "search-has_children").value = "true";
  get(doc, "search-form").dispatch("submit"); await settle();
  call = calls.filter(call => call.query).at(-1);
  assert.equal(call.depth, 5); assert.equal(call.hasChildren, true); assert.equal(call.cursor, null);
  await doc.defaultView.history.back();
  assert.equal(doc.defaultView.location.searchParams.get("depth"), "2");
  await doc.defaultView.history.forward(); assert.equal(get(doc, "search-depth").value, "5");
  const original = adapter.search; adapter.search = async () => { throw Error("offline"); };
  get(doc, "search-form").dispatch("submit"); await settle();
  assert.equal(get(doc, "search-results").getAttribute("aria-busy"), "false");
  adapter.search = original; get(doc, "error").querySelector("button").click(); await settle();
  assert.equal(calls.filter(call => call.query).at(-1).depth, 5);
  get(doc, "clear-search").click();
  assert.equal(doc.defaultView.location.searchParams.has("depth"), false); app.destroy();
});

test("D4 clear search keeps the SSR basic link valid with and without existing query parameters", async () => {
  for (const [url, expected] of [
    ["http://localhost/fiqh", "/fiqh?basic=1"],
    ["http://localhost/fiqh?edition=7", "/fiqh?edition=7&basic=1"],
  ]) {
    const { doc, app } = await setup({ url });
    get(doc, "search-query").value = "عنوان";
    get(doc, "search-form").dispatch("submit"); await settle();

    let basic = new URL(get(doc, "basic-link").getAttribute("href"), doc.defaultView.location);
    assert.equal(basic.pathname, "/fiqh");
    assert.equal(basic.searchParams.get("basic"), "1");
    assert.equal(basic.searchParams.get("q"), "عنوان");

    get(doc, "clear-search").click();
    assert.equal(get(doc, "basic-link").getAttribute("href"), expected);
    basic = new URL(get(doc, "basic-link").getAttribute("href"), doc.defaultView.location);
    assert.equal(basic.pathname, "/fiqh");
    assert.equal(basic.searchParams.get("basic"), "1");
    assert.equal(basic.searchParams.has("q"), false);
    app.destroy();
  }
});

test("E4 clear resets every visible search control, and history restores submitted filters", async () => {
  const { doc, app } = await setup();
  get(doc, "search-query").value = ""; get(doc, "search-mode").value = "exact";
  get(doc, "search-depth").value = "2"; get(doc, "search-has_children").value = "false"; get(doc, "search-scope").value = "1";
  get(doc, "search-form").dispatch("submit"); await settle();
  get(doc, "clear-search").click();
  for (const id of ["search-query", "search-depth", "search-has_children", "search-scope"]) assert.equal(get(doc, id).value, "", id);
  assert.equal(get(doc, "search-mode").value, "normalized");
  for (const key of ["q", "mode", "depth", "has_children", "root", "offset"]) assert.equal(doc.defaultView.location.searchParams.has(key), false);
  await doc.defaultView.history.back();
  assert.equal(get(doc, "search-depth").value, "2"); assert.equal(get(doc, "search-has_children").value, "false");
  await doc.defaultView.history.forward(); assert.equal(get(doc, "search-depth").value, ""); app.destroy();
});

test("E4 paging aligns controls and history with the query actually used", async () => {
  const { doc, app } = await setup();
  get(doc, "search-query").value = "  عنوان  "; get(doc, "search-mode").value = "exact";
  get(doc, "search-depth").value = "2"; get(doc, "search-has_children").value = "false"; get(doc, "search-scope").value = "1";
  get(doc, "search-form").dispatch("submit"); await settle();
  get(doc, "search-query").value = "تعديل لم يرسل"; get(doc, "search-mode").value = "literal";
  get(doc, "search-depth").value = "5"; get(doc, "search-has_children").value = "true";
  get(doc, "search-results").querySelector("button").click(); await settle();
  assert.equal(get(doc, "search-query").value, "  عنوان  "); assert.equal(get(doc, "search-mode").value, "exact");
  assert.equal(get(doc, "search-depth").value, "2"); assert.equal(get(doc, "search-has_children").value, "false");
  assert.equal(doc.defaultView.history.state.fatwaCatalog.snapshot.depth, "2"); app.destroy();
});

test("E4 failed search has a bookmark and restores a retryable state after navigation", async () => {
  const { doc, adapter, app } = await setup();
  const original = adapter.search;
  adapter.search = async () => { throw Error("offline"); };
  get(doc, "search-query").value = "فارغ"; get(doc, "search-depth").value = "3";
  get(doc, "search-form").dispatch("submit"); await settle();
  assert.equal(doc.defaultView.location.searchParams.get("q"), "فارغ");
  assert.equal(doc.defaultView.location.searchParams.get("depth"), "3");
  get(doc, "introductions").querySelector("a").click(); await settle();
  await doc.defaultView.history.back();
  assert.match(get(doc, "error").textContent, /تعذّر البحث/);
  adapter.search = original; get(doc, "error").querySelector("button").click(); await settle();
  assert.match(get(doc, "search-results").textContent, /لم نعثر/);
  assert.equal(get(doc, "search-results").getAttribute("aria-busy"), "false"); app.destroy();
});

test("E4 a late search cannot replace a newer root URL or leave busy results", async () => {
  const { doc, adapter, app } = await setup(), pending = deferred();
  let signal;
  adapter.search = (_query, options) => { signal = options.signal; return pending.promise; };
  get(doc, "search-query").value = "عنوان"; get(doc, "search-form").dispatch("submit");
  get(doc, "introductions").querySelector("a").click(); await settle();
  assert.equal(signal.aborted, true);
  pending.resolve({ items: [], total: 0, offset: 0, next_cursor: null, previous_cursor: null }); await settle();
  assert.equal(doc.defaultView.location.pathname, "/fiqh/nodes/90");
  assert.equal(get(doc, "search-results").getAttribute("aria-busy"), "false"); app.destroy();
});

test("E4 review R1 branch Enter supersedes pending search success and failure", async () => {
  for (const action of ["collapse", "expand"]) for (const outcome of ["resolve", "reject"]) {
    const { doc, adapter, app } = await setup(), pending = deferred();
    try {
      if (action === "expand") item(doc, "1").key("ArrowRight");
      const original = adapter.search;
      let signal;
      adapter.search = (_query, options) => { signal = options.signal; return pending.promise; };
      get(doc, "search-query").value = "عنوان متأخر";
      get(doc, "search-form").dispatch("submit");
      item(doc, "1").focus(); item(doc, "1").key("Enter"); await settle();
      const selectedURL = doc.defaultView.location.href;
      assert.equal(doc.defaultView.location.pathname, "/fiqh/nodes/1");
      const selectedHistory = structuredClone(doc.defaultView.history.state);
      const selectedFocus = doc.activeElement;
      if (outcome === "resolve") pending.resolve(await original("عنوان", {}));
      else pending.reject(Error("stale search unavailable"));
      await settle();
      assert.equal(doc.defaultView.location.href, selectedURL, action + "/" + outcome);
      assert.deepEqual(doc.defaultView.history.state, selectedHistory);
      assert.equal(doc.activeElement, selectedFocus);
      assert.equal(item(doc, "1").getAttribute("aria-selected"), "true");
      assert.equal(item(doc, "1").getAttribute("aria-expanded"), String(action === "expand"));
      assert.equal(get(doc, "search-results").getAttribute("aria-busy"), "false");
      assert.equal(get(doc, "error").textContent, "");
      assert.equal(signal.aborted, true);
    } finally { app.destroy(); }
  }
});

test("E4 review R2 new search supersedes pending detail success and failure", async () => {
  for (const outcome of ["resolve", "reject"]) {
    const { doc, adapter, app } = await setup(), pending = deferred();
    try {
      get(doc, "search-query").value = "عميق";
      get(doc, "search-form").dispatch("submit"); await settle();
      const original = adapter.node;
      let signal;
      adapter.node = (_id, options) => { signal = options.signal; return pending.promise; };
      get(doc, "search-results").querySelector("a").click();
      get(doc, "search-query").value = "فارغ";
      get(doc, "search-form").dispatch("submit"); await settle();
      const searchURL = doc.defaultView.location.href;
      const searchHistory = structuredClone(doc.defaultView.history.state);
      const searchFocus = doc.activeElement;
      assert.equal(doc.defaultView.location.searchParams.get("q"), "فارغ");
      if (outcome === "resolve") pending.resolve(await original("29"));
      else pending.reject(Error("stale detail unavailable"));
      await settle();
      assert.equal(doc.defaultView.location.href, searchURL, outcome);
      assert.deepEqual(doc.defaultView.history.state, searchHistory);
      assert.equal(doc.activeElement, searchFocus);
      assert.equal(item(doc, "1").getAttribute("aria-selected"), "true");
      assert.equal(item(doc, "29"), undefined);
      assert.match(get(doc, "search-results").textContent, /لم نعثر/);
      assert.equal(get(doc, "tree-region").getAttribute("aria-busy"), "false");
      assert.equal(get(doc, "error").textContent, "");
      assert.equal(signal.aborted, true);
    } finally { app.destroy(); }
  }
});

test("E4 review synchronous leaf selection and clear supersede a pending detail", async () => {
  for (const action of ["leaf", "clear"]) {
    const { doc, adapter, app } = await setup(), pending = deferred();
    try {
      get(doc, "search-query").value = "عميق";
      get(doc, "search-form").dispatch("submit"); await settle();
      const original = adapter.node;
      adapter.node = () => pending.promise;
      get(doc, "search-results").querySelector("a").click();
      if (action === "leaf") { item(doc, "2").focus(); item(doc, "2").key("Enter"); }
      else get(doc, "clear-search").click();
      const wantedURL = doc.defaultView.location.href;
      const wantedHistory = structuredClone(doc.defaultView.history.state);
      const wantedFocus = doc.activeElement;
      pending.resolve(await original("29")); await settle();
      assert.equal(doc.defaultView.location.href, wantedURL, action);
      assert.deepEqual(doc.defaultView.history.state, wantedHistory);
      assert.equal(doc.activeElement, wantedFocus);
      assert.equal(item(doc, "29"), undefined);
      assert.equal(get(doc, "tree-region").getAttribute("aria-busy"), "false");
      if (action === "leaf") assert.equal(item(doc, "2").getAttribute("aria-selected"), "true");
      else assert.equal(get(doc, "search-results").textContent, "");
    } finally { app.destroy(); }
  }
});

for (const action of ["search", "root", "clear", "Back"]) {
  for (const outcome of ["resolve", "reject", "abort-aware"]) {
    test(`E4 Home continuation yields to ${action} with ${outcome}`, async () => {
      const { doc, adapter, app } = await setup(), pending = deferred();
      try {
        get(doc, "introductions").querySelector("a").click(); await settle();
        const original = adapter.children;
        const group = await original("1");
        let signal;
        adapter.children = (_id, options) => {
          signal = options.signal;
          if (outcome === "abort-aware") signal.addEventListener("abort", () =>
            pending.reject(Object.assign(Error("cancelled immediately"), { name: "AbortError" })), { once: true });
          return pending.promise;
        };
        get(doc, "catalog-home").click();
        assert.equal(get(doc, "tree-region").getAttribute("aria-busy"), "true");
        if (action === "search") {
          get(doc, "search-query").value = "فارغ"; get(doc, "search-form").dispatch("submit");
        } else if (action === "root") get(doc, "introductions").querySelector("a").click();
        else if (action === "clear") get(doc, "clear-search").click();
        else await doc.defaultView.history.back();
        await settle();
        const assertLatest = () => {
          assert.equal(doc.defaultView.location.pathname, action === "root" ? "/fiqh/nodes/90" : "/fiqh");
          assert.equal(doc.defaultView.location.searchParams.get("q"), action === "search" ? "فارغ" : null);
          if (action === "Back") assert.equal(doc.defaultView.location.search, "");
          assert.equal(item(doc, action === "root" ? "90" : "1").getAttribute("aria-selected"), "true");
          const focus = action === "search" ? get(doc, "search-results").querySelector("h3") :
            action === "clear" ? get(doc, "search-query") : item(doc, action === "root" ? "90" : "1");
          assert.equal(doc.activeElement, focus);
          assert.equal(get(doc, "tree-region").getAttribute("aria-busy"), "false");
          assert.equal(get(doc, "error").textContent, "");
          assert.equal(signal.aborted, true);
        };
        assertLatest();
        const url = doc.defaultView.location.href, basic = get(doc, "basic-link").getAttribute("href");
        const history = structuredClone(doc.defaultView.history.state), length = doc.defaultView.history.length;
        const status = get(doc, "status").textContent;
        if (outcome === "resolve") pending.resolve(group);
        else if (outcome === "reject") pending.reject(Error("stale Home failure"));
        await settle();
        assertLatest();
        assert.equal(doc.defaultView.location.href, url);
        assert.equal(get(doc, "basic-link").getAttribute("href"), basic);
        assert.deepEqual(doc.defaultView.history.state, history);
        assert.equal(doc.defaultView.history.length, length);
        assert.equal(get(doc, "status").textContent, status);
      } finally { app.destroy(); }
    });
  }
}

test("E4 Home checks freshness even after its child operation succeeds", async () => {
  const { doc, adapter, app } = await setup(), pending = deferred();
  try {
    get(doc, "introductions").querySelector("a").click(); await settle();
    const group = await adapter.children("1");
    adapter.children = () => pending.promise;
    get(doc, "catalog-home").click();
    let completedBeforeNewAction = false;
    pending.resolve(group);
    queueMicrotask(() => {
      completedBeforeNewAction = item(doc, "1").getAttribute("aria-expanded") === "true" && !!item(doc, "2");
      get(doc, "introductions").querySelector("a").click();
    });
    await settle();
    assert.equal(completedBeforeNewAction, true);
    assert.equal(doc.defaultView.location.pathname, "/fiqh/nodes/90");
    assert.equal(doc.activeElement, item(doc, "90"));
    assert.equal(get(doc, "basic-link").getAttribute("href"), "/fiqh/nodes/90?edition=7&basic=1");
  } finally { app.destroy(); }
});

test("E4 current Home succeeds and retains keyboard focus and native fallback", async () => {
  const { doc, app } = await setup();
  try {
    get(doc, "introductions").querySelector("a").click(); await settle();
    get(doc, "catalog-home").click(); await settle();
    assert.equal(doc.defaultView.location.pathname, "/fiqh");
    assert.equal(item(doc, "1").getAttribute("aria-expanded"), "true");
    assert.equal(doc.activeElement, get(doc, "books").querySelector("a"));
    assert.equal(get(doc, "basic-link").getAttribute("href"), "/fiqh?edition=7&basic=1");
    assert.equal(get(doc, "tree-region").getAttribute("aria-busy"), "false");
    assert.equal(get(doc, "error").textContent, "");
  } finally { app.destroy(); }
});

test("E4 current Home failure remains retryable without claiming successful navigation", async () => {
  const { doc, adapter, app } = await setup();
  try {
    get(doc, "introductions").querySelector("a").click(); await settle();
    const previousURL = doc.defaultView.location.href, original = adapter.children;
    adapter.children = async () => { throw Error("current Home unavailable"); };
    get(doc, "catalog-home").click(); await settle();
    assert.equal(doc.defaultView.location.href, previousURL);
    assert.match(get(doc, "error").textContent, /إعادة المحاولة/);
    assert.equal(get(doc, "tree-region").getAttribute("aria-busy"), "false");
    adapter.children = original;
    get(doc, "error").querySelector("button").click(); await settle();
    assert.equal(doc.defaultView.location.pathname, "/fiqh");
    assert.equal(doc.activeElement, get(doc, "books").querySelector("a"));
    assert.equal(get(doc, "basic-link").getAttribute("href"), "/fiqh?edition=7&basic=1");
    assert.equal(get(doc, "error").textContent, "");
  } finally { app.destroy(); }
});
