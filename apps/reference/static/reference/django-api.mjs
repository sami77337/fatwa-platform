// S2 adapter implemented against S0's real, edition-scoped Django read API.
// No fixture import, network fallback, credentials, or write methods.
export class CatalogError extends Error {
  constructor(code) { super(code); this.name = "CatalogError"; this.code = code; }
}
const PAGE_SIZE = 20;
const KIND = "SOURCE_BOOK_TOC_NOT_FATWAS";
const OWNER_ARCHIVE = "82a797806430635350decdde27d07fe41fb1278838c8173dc4080f9d109957ce";
const check = condition => { if (!condition) throw new CatalogError("INVALID_PAYLOAD"); };
const integer = (value, minimum = 1, maximum = Number.MAX_SAFE_INTEGER) => {
  check(Number.isSafeInteger(value) && value >= minimum && value <= maximum);
  return value;
};
const text = (value, maximum = 500) => {
  check(typeof value === "string" && value.length > 0 && value.length <= maximum);
  return value;
};
const ident = value => {
  check(typeof value === "string" && /^[1-9][0-9]{0,15}$/.test(value));
  return integer(Number(value));
};
const cursorOffset = cursor => {
  if (cursor == null) return 0;
  check(typeof cursor === "string" && /^(0|[1-9][0-9]{0,4})$/.test(cursor));
  return integer(Number(cursor), 0, 20000);
};
export function createDjangoAdapter({ editionId = null, origin = globalThis.location?.origin,
  fetchImpl = globalThis.fetch, timeoutMs = 8000 } = {}) {
  const base = new URL("/api/v1/fiqh/", origin);
  check(base.origin === origin && ["http:", "https:"].includes(base.protocol));
  if (editionId !== null) editionId = ident(String(editionId));
  let edition = null;
  const request = async (route, params = {}, signal) => {
    const url = new URL(route, base);
    check(url.origin === origin && url.pathname.startsWith(base.pathname));
    for (const [key, value] of Object.entries(params)) if (value !== null) url.searchParams.set(key, String(value));
    const controller = new AbortController();
    const cancel = () => controller.abort();
    if (signal?.aborted) controller.abort();
    else signal?.addEventListener("abort", cancel, { once: true });
    const timer = setTimeout(cancel, timeoutMs);
    try {
      const response = await fetchImpl(url.href, { method: "GET", credentials: "omit", cache: "no-store",
        redirect: "error", headers: { Accept: "application/json" }, signal: controller.signal });
      if (!response.ok) throw new CatalogError(response.status === 400 ? "INVALID_QUERY" : response.status === 404 ? "NOT_FOUND" : "UNAVAILABLE");
      check((response.headers.get("content-type") ?? "").includes("application/json"));
      const payload = await response.json();
      check(payload?.kind === KIND);
      return payload;
    } catch (error) {
      if (controller.signal.aborted && !signal?.aborted) throw new CatalogError("TIMEOUT");
      throw error;
    } finally { clearTimeout(timer); signal?.removeEventListener("abort", cancel); }
  };
  const setEdition = value => {
    check(value && value.work);
    integer(value.id); text(value.edition_key); text(value.title); text(value.publisher);
    text(value.work.title_original); text(value.work.madhhab, 100);
    text(value.work.source_namespace, 40); text(value.work.source_book_id, 80);
    integer(value.heading_count, 1, 20000); integer(value.root_count, 1, 20000); integer(value.max_depth, 1, 5);
    for (const key of ["source_archive_sha256", "source_input_sha256"]) check(/^[a-f0-9]{64}$/.test(value[key]));
    edition = value; editionId = value.id;
  };
  const verifyEdition = value => {
    check(value?.id === editionId && value.source_archive_sha256 === edition.source_archive_sha256 &&
      value.source_input_sha256 === edition.source_input_sha256 && value.edition_key === edition.edition_key &&
      value.work?.source_namespace === edition.work.source_namespace &&
      value.work?.source_book_id === edition.work.source_book_id &&
      value.work?.title_original === edition.work.title_original && value.title === edition.title &&
      value.publisher === edition.publisher && value.work?.madhhab === edition.work.madhhab);
  };
  const project = row => {
    check(edition !== null && row);
    const id = String(integer(row.id));
    const parent = row.parent_id === null ? null : String(integer(row.parent_id));
    const depth = integer(row.depth, 1, 5);
    check((parent === null) === (depth === 1));
    const children = integer(row.children_count, 0, 20000);
    check(depth < 5 || children === 0);
    const isOwner622 = edition.work.source_book_id === "622" && edition.source_archive_sha256 === OWNER_ARCHIVE;
    const kind = parent !== null ? "heading" : isOwner622 && ["1", "23"].includes(id) ? "introduction" : "book";
    return { id, parent_id: parent, kind, title: text(row.title), depth,
      position: integer(row.position) - 1, child_count: children, has_children: children > 0,
      source: { work_id: edition.work.source_book_id, work_title: edition.work.title_original,
        edition: edition.title, publisher: edition.publisher, madhhab: edition.work.madhhab,
        synthetic: edition.work.source_namespace === "synthetic", source_id: text(row.source_id, 100),
        printed_part: text(row.part, 100), printed_page: integer(row.page), page_id: integer(row.page_id) } };
  };
  const page = payload => {
    verifyEdition(payload.edition);
    const total = integer(payload.total, 0, 20000), limit = integer(payload.limit, 1, 100);
    const offset = integer(payload.offset, 0, 20000);
    check(Array.isArray(payload.items) && payload.items.length <= limit && offset + payload.items.length <= Math.max(offset, total));
    const next = offset + limit < total ? offset + limit : null;
    check(payload.next_offset === next);
    // Original sibling positions can have gaps. ARIA uses the ordinal within this page.
    return { items: payload.items.map((row, index) => ({ ...project(row),
      sibling_ordinal: offset + index + 1, sibling_total: total })), total, offset, limit, next_cursor: next === null ? null : String(next),
      previous_cursor: offset ? String(Math.max(0, offset - limit)) : null };
  };
  return {
    async catalog({ signal } = {}) {
      const inventory = await request("books", { limit: 100 }, signal);
      check(Array.isArray(inventory.items));
      if (!inventory.items.length && editionId === null) return { books: [], introductions: [], totals: { nodes: 0 }, source: null };
      const selected = editionId === null && inventory.total === 1 ? inventory.items[0] : inventory.items.find(item => item.id === editionId);
      if (!selected) throw new CatalogError("EDITION_REQUIRED");
      setEdition(selected);
      let roots = [], offset = 0;
      do {
        const payload = await request("roots", { edition: editionId, limit: 100, offset }, signal);
        const result = page(payload); roots.push(...result.items);
        check(roots.length <= 1000);
        offset = result.next_cursor === null ? null : Number(result.next_cursor);
      } while (offset !== null);
      check(roots.length === edition.root_count && new Set(roots.map(row => row.id)).size === roots.length);
      check(roots.every(row => row.parent_id === null));
      return { books: roots.filter(row => row.kind !== "introduction"), introductions: roots.filter(row => row.kind === "introduction"),
        totals: { nodes: edition.heading_count, roots: edition.root_count, max_depth: edition.max_depth }, source: edition };
    },
    async children(id, { cursor = null, anchorId = null, signal } = {}) {
      ident(id); check(edition !== null && !(cursor !== null && anchorId !== null));
      const params = { edition: editionId, limit: PAGE_SIZE };
      if (anchorId !== null) params.anchor = ident(anchorId);
      else params.offset = cursorOffset(cursor);
      const payload = await request("nodes/" + id + "/children", params, signal);
      check(payload.parent === Number(id));
      const result = page(payload);
      check(result.items.every(row => row.parent_id === id));
      if (anchorId !== null) check(result.items.some(row => row.id === anchorId));
      return result;
    },
    async node(id, { signal } = {}) {
      ident(id); check(edition !== null);
      const payload = await request("nodes/" + id, { edition: editionId }, signal);
      verifyEdition(payload.edition);
      const node = project(payload.node);
      check(Array.isArray(payload.ancestors) && payload.ancestors.length >= 1 && payload.ancestors.length <= 5);
      const breadcrumbs = payload.ancestors.map(project);
      check(node.id === id && breadcrumbs.at(-1).id === id && breadcrumbs[0].parent_id === null);
      for (let i = 1; i < breadcrumbs.length; i++) check(breadcrumbs[i].parent_id === breadcrumbs[i - 1].id);
      return { node, breadcrumbs };
    },
    async search(query, { rootId = null, cursor = null, mode = "normalized", depth = null, hasChildren = null, signal } = {}) {
      if (typeof query !== "string" || query.length > 160 || query.split(/\s+/).filter(Boolean).length > 10 || /[\x00-\x1f\x7f]/.test(query)) throw new CatalogError("INVALID_QUERY");
      if (!["normalized", "literal", "exact"].includes(mode)) throw new CatalogError("INVALID_QUERY");
      if (depth !== null && (!Number.isInteger(depth) || depth < 1 || depth > 5)) throw new CatalogError("INVALID_QUERY");
      if (hasChildren !== null && typeof hasChildren !== "boolean") throw new CatalogError("INVALID_QUERY");
      check(edition !== null);
      return page(await request("search", { edition: editionId, q: query, mode, limit: PAGE_SIZE,
        offset: cursorOffset(cursor), root: rootId === null ? null : ident(rootId), depth, has_children: hasChildren }, signal));
    },
  };
}
