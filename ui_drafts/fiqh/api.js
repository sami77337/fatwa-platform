import { createFixture, normalizeQuery, PAGE_SIZE, SOURCE } from "./fixture.js";

export class CatalogError extends Error {
  constructor(code) { super(code); this.name = "CatalogError"; this.code = code; }
}
const abort = signal => { if (signal?.aborted) throw new DOMException("Aborted", "AbortError"); };
const copy = value => structuredClone(value);
function queryText(value) {
  if (typeof value !== "string" || Array.from(value.trim()).length < 2 || Array.from(value.trim()).length > 120) throw new CatalogError("INVALID_QUERY");
  const text = value.trim();
  const normalizedLength = Array.from(normalizeQuery(text)).length;
  if (normalizedLength < 2 || normalizedLength > 120) throw new CatalogError("INVALID_QUERY");
  return text;
}
function offset(cursor) {
  if (cursor === null || cursor === undefined) return 0;
  if (typeof cursor !== "string" || !/^(0|[1-9][0-9]{0,6})$/.test(cursor)) throw new CatalogError("INVALID_CURSOR");
  return Number(cursor);
}
function page(items, cursor) {
  const start = offset(cursor);
  if (start > items.length) throw new CatalogError("INVALID_CURSOR");
  return copy({ items: items.slice(start, start + PAGE_SIZE), total: items.length,
    next_cursor: start + PAGE_SIZE < items.length ? String(start + PAGE_SIZE) : null,
    previous_cursor: start > 0 ? String(Math.max(0, start - PAGE_SIZE)) : null });
}
export function createMockAdapter({ fixture = createFixture(), delay = 90, beforeRequest = () => {} } = {}) {
  const request = async (operation, args, signal, result) => {
    abort(signal);
    await beforeRequest(operation, args);
    await new Promise((resolve, reject) => {
      const finish = () => { signal?.removeEventListener("abort", cancel); resolve(); };
      const timer = setTimeout(finish, delay);
      const cancel = () => { clearTimeout(timer); signal?.removeEventListener("abort", cancel); reject(new DOMException("Aborted", "AbortError")); };
      signal?.addEventListener("abort", cancel, { once: true });
      if (signal?.aborted) cancel();
    });
    abort(signal);
    return result();
  };
  const find = id => {
    const node = fixture.byId.get(id);
    if (!node) throw new CatalogError("NOT_FOUND");
    return node;
  };
  return {
    catalog({ signal } = {}) {
      return request("catalog", {}, signal, () => copy({
        schema_version: 1, fixture_id: fixture.id, source: SOURCE,
        totals: { nodes: fixture.nodes.length, roots: 32, books: 30, max_depth: 5 },
        books: fixture.nodes.filter(n => n.kind === "book"),
        introductions: fixture.nodes.filter(n => n.kind === "introduction"),
      }));
    },
    children(id, { cursor = null, anchorId = null, signal } = {}) {
      return request("children", { id, cursor, anchorId }, signal, () => {
        find(id);
        const items = fixture.children.get(id) ?? [];
        if (anchorId) {
          if (cursor !== null) throw new CatalogError("INVALID_CURSOR");
          const index = items.findIndex(n => n.id === anchorId);
          if (index < 0) throw new CatalogError("NOT_FOUND");
          cursor = String(Math.floor(index / PAGE_SIZE) * PAGE_SIZE);
        }
        return page(items, cursor);
      });
    },
    node(id, { signal } = {}) {
      return request("node", { id }, signal, () => {
        const node = find(id);
        const breadcrumbs = [];
        for (let parent = node; parent; parent = parent.parent_id ? find(parent.parent_id) : null) breadcrumbs.unshift(parent);
        return copy({ node, breadcrumbs });
      });
    },
    search(query, { rootId = null, cursor = null, signal } = {}) {
      const text = queryText(query);
      return request("search", { query: text, rootId, cursor }, signal, () => {
        if (rootId && find(rootId).parent_id !== null) throw new CatalogError("INVALID_ROOT");
        const key = normalizeQuery(text);
        return page(fixture.nodes.filter(n => (!rootId || n.root_id === rootId) && normalizeQuery(n.title).includes(key)), cursor);
      });
    },
  };
}

// Strict public metadata projection. Unknown properties never reach the view.
const boundedString = (value, max = 500) => {
  if (typeof value !== "string" || !value.length || value.length > max) throw new CatalogError("INVALID_PAYLOAD");
  return value;
};
const integer = (value, min, max) => {
  if (!Number.isSafeInteger(value) || value < min || value > max) throw new CatalogError("INVALID_PAYLOAD");
  return value;
};
const boolean = value => { if (typeof value !== "boolean") throw new CatalogError("INVALID_PAYLOAD"); return value; };
const identifier = value => {
  boundedString(value, 100);
  if (!/^[A-Za-z0-9_-]+$/.test(value)) throw new CatalogError("INVALID_PAYLOAD");
  return value;
};
const nullableInteger = value => value === null ? null : integer(value, 1, 100000);
export function publicSource(value) {
  if (!value || typeof value !== "object") throw new CatalogError("INVALID_PAYLOAD");
  return {
    work_id: identifier(value.work_id), work_title: boundedString(value.work_title),
    edition: boundedString(value.edition), madhhab: boundedString(value.madhhab, 100),
    synthetic: boolean(value.synthetic),
  };
}
export function publicNode(value) {
  if (!value || !["book", "introduction", "heading"].includes(value.kind)) throw new CatalogError("INVALID_PAYLOAD");
  const source = publicSource(value.source);
  const childCount = integer(value.child_count, 0, 100000);
  const hasChildren = boolean(value.has_children);
  if (hasChildren !== (childCount > 0) || (value.depth === 5 && hasChildren)) throw new CatalogError("INVALID_PAYLOAD");
  if (value.parent_id === null) {
    if (value.kind === "heading" || value.depth !== 1 || value.root_id !== value.id) throw new CatalogError("INVALID_PAYLOAD");
  } else if (value.kind !== "heading" || value.depth <= 1) throw new CatalogError("INVALID_PAYLOAD");
  return {
    id: identifier(value.id), parent_id: value.parent_id === null ? null : identifier(value.parent_id),
    root_id: identifier(value.root_id), kind: value.kind, title: boundedString(value.title),
    depth: integer(value.depth, 1, 5), position: integer(value.position, 0, 100000),
    child_count: childCount, has_children: hasChildren,
    source: { ...source, printed_part: nullableInteger(value.source.printed_part), printed_page: nullableInteger(value.source.printed_page) },
  };
}
function publicPage(value) {
  if (!value || !Array.isArray(value.items) || value.items.length > PAGE_SIZE) throw new CatalogError("INVALID_PAYLOAD");
  const items = value.items.map(publicNode);
  if (new Set(items.map(n => n.id)).size !== items.length) throw new CatalogError("INVALID_PAYLOAD");
  return {
    items, total: integer(value.total, items.length, 100000),
    next_cursor: value.next_cursor === null ? null : boundedString(value.next_cursor, 200),
    previous_cursor: value.previous_cursor === null ? null : boundedString(value.previous_cursor, 200),
  };
}
const sameSource = (left, right) => ["work_id", "work_title", "edition", "madhhab", "synthetic"].every(key => left[key] === right[key]);
export function createReadOnlyAdapter(baseUrl, { fetchImpl = globalThis.fetch, origin = globalThis.location?.origin, timeoutMs = 8000 } = {}) {
  const base = new URL(baseUrl, origin);
  if (base.origin !== origin || !["http:", "https:"].includes(base.protocol) || base.username || base.password || base.search || base.hash || !base.pathname.endsWith("/")) throw new CatalogError("UNSAFE_API_BASE");
  let sourcePin = null;
  const pinNodes = items => {
    const expected = sourcePin ?? items[0]?.source;
    if (expected && items.some(n => !sameSource(n.source, expected))) throw new CatalogError("INVALID_PAYLOAD");
    if (expected) sourcePin = publicSource(expected);
  };
  const request = async (route, params, signal) => {
    const url = new URL(route, base);
    for (const [key, value] of Object.entries(params)) if (value !== null && value !== undefined) url.searchParams.set(key, String(value));
    const timeout = AbortSignal.timeout(timeoutMs);
    const combined = signal ? AbortSignal.any([signal, timeout]) : timeout;
    const response = await fetchImpl(url.href, {
      method: "GET", credentials: "omit", cache: "no-store", redirect: "error",
      headers: { Accept: "application/json" }, signal: combined,
    });
    if (!response.ok) throw new CatalogError(response.status === 404 ? "NOT_FOUND" : "NETWORK_ERROR");
    if (!(response.headers.get("content-type") ?? "").includes("application/json")) throw new CatalogError("INVALID_PAYLOAD");
    // Bound decoded response size before parsing; do not trust Content-Length.
    const reader = response.body?.getReader();
    if (!reader) throw new CatalogError("INVALID_PAYLOAD");
    const chunks = [];
    let size = 0;
    try {
      for (;;) {
        const { done, value } = await reader.read();
        if (done) break;
        size += value.byteLength;
        if (size > 262144) { await reader.cancel(); throw new CatalogError("INVALID_PAYLOAD"); }
        chunks.push(value);
      }
    } finally { reader.releaseLock(); }
    const bytes = new Uint8Array(size);
    let start = 0;
    for (const chunk of chunks) { bytes.set(chunk, start); start += chunk.length; }
    try { return JSON.parse(new TextDecoder("utf-8", { fatal: true }).decode(bytes)); }
    catch { throw new CatalogError("INVALID_PAYLOAD"); }
  };
  const validId = id => encodeURIComponent(identifier(id));
  return {
    async catalog({ signal } = {}) {
      const value = await request("catalog", {}, signal);
      if (value.schema_version !== 1 || !Array.isArray(value.books) || value.books.length !== 30 || !Array.isArray(value.introductions) || value.introductions.length !== 2) throw new CatalogError("INVALID_PAYLOAD");
      const catalogSource = publicSource(value.source);
      if (sourcePin && !sameSource(sourcePin, catalogSource)) throw new CatalogError("INVALID_PAYLOAD");
      const books = value.books.map(publicNode);
      const introductions = value.introductions.map(publicNode);
      if (books.some(n => n.kind !== "book" || n.parent_id !== null || n.depth !== 1) || introductions.some(n => n.kind !== "introduction" || n.parent_id !== null || n.depth !== 1) || new Set([...books, ...introductions].map(n => n.id)).size !== 32) throw new CatalogError("INVALID_PAYLOAD");
      if ([...books, ...introductions].some(n => !sameSource(n.source, catalogSource))) throw new CatalogError("INVALID_PAYLOAD");
      sourcePin = catalogSource;
      return {
        schema_version: 1, fixture_id: value.fixture_id === null ? null : boundedString(value.fixture_id, 100),
        source: publicSource(value.source), books, introductions,
        totals: { nodes: integer(value.totals?.nodes, 32, 100000), roots: integer(value.totals?.roots, 32, 32), books: integer(value.totals?.books, 30, 30), max_depth: integer(value.totals?.max_depth, 1, 5) },
      };
    },
    async children(id, { cursor = null, anchorId = null, signal } = {}) {
      if (anchorId) { identifier(anchorId); if (cursor !== null) throw new CatalogError("INVALID_CURSOR"); }
      const value = publicPage(await request("nodes/" + validId(id) + "/children", { limit: PAGE_SIZE, cursor, anchor_id: anchorId }, signal));
      if (value.items.some((n, index) => n.parent_id !== id || (index && (n.position <= value.items[index - 1].position || n.depth !== value.items[0].depth || n.root_id !== value.items[0].root_id))) || (anchorId && !value.items.some(n => n.id === anchorId))) throw new CatalogError("INVALID_PAYLOAD");
      pinNodes(value.items);
      return value;
    },
    async node(id, { signal } = {}) {
      const value = await request("nodes/" + validId(id), {}, signal);
      const node = publicNode(value.node);
      if (node.id !== id || !Array.isArray(value.breadcrumbs) || !value.breadcrumbs.length || value.breadcrumbs.length > 5) throw new CatalogError("INVALID_PAYLOAD");
      const breadcrumbs = value.breadcrumbs.map(publicNode);
      if (breadcrumbs.at(-1).id !== id || breadcrumbs[0].id !== node.root_id || breadcrumbs[0].parent_id !== null || breadcrumbs.some((n, index) => n.depth !== index + 1 || n.root_id !== node.root_id || (index && n.parent_id !== breadcrumbs[index - 1].id))) throw new CatalogError("INVALID_PAYLOAD");
      pinNodes([node, ...breadcrumbs]);
      return { node, breadcrumbs };
    },
    async search(query, { rootId = null, cursor = null, signal } = {}) {
      const q = queryText(query);
      if (rootId) identifier(rootId);
      const value = publicPage(await request("search", { q, root_id: rootId, limit: PAGE_SIZE, cursor }, signal));
      if (rootId && value.items.some(n => n.root_id !== rootId)) throw new CatalogError("INVALID_PAYLOAD");
      pinNodes(value.items);
      return value;
    },
  };
}
