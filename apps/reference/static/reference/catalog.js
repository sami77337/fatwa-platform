import { createDjangoAdapter } from "./django-api.mjs";

const number = new Intl.NumberFormat("ar", { useGrouping: false });
export const MAX_TREE_ITEMS = 81; // One root and at most 20 siblings at each of four levels.
export function mount(adapter, doc = document, { initialNode = null, onCatalog = () => {} } = {}) {
  const get = id => doc.getElementById(id);
  const view = doc.defaultView;
  const state = { catalog: null, root: null, selected: null, focusId: null, expanded: [],
    groups: new Map(), searchPage: null, searchOptions: null, initialized: false,
    treeRequest: null, searchRequest: null, catalogRequest: null, disposed: false };
  const element = (tag, text, attributes = {}) => {
    const node = doc.createElement(tag);
    if (text !== null) node.textContent = text;
    for (const [key, value] of Object.entries(attributes)) node.setAttribute(key, String(value));
    return node;
  };
  const button = (text, action, attributes = {}) => {
    const node = element("button", text, { type: "button", ...attributes });
    node.addEventListener("click", action);
    return node;
  };
  const announce = text => { get("status").textContent = text; };
  const clearError = () => get("error").replaceChildren();
  const busy = (id, value) => get(id).setAttribute("aria-busy", String(value));
  const current = (lane, request) => state[lane] === request && !state.disposed;
  const cancel = lane => { state[lane]?.abort(); state[lane] = null; };
  const begin = lane => {
    cancel(lane);
    const request = new AbortController();
    state[lane] = request;
    clearError();
    return request;
  };
  const failure = (retry, message = "تعذّر تحميل العناوين. حاول مرة أخرى.") => {
    get("error").replaceChildren(element("p", message), button("إعادة المحاولة", retry));
    if (!state.initialized && get("request-status")) {
      get("request-status").replaceChildren(element("span", "تعذر فتح التصفح التفاعلي. يمكنك متابعة التصفح بالروابط المعروضة. "), button("إعادة المحاولة", () => void start()));
    }
    announce("تعذّر إتمام الطلب.");
  };
  const href = (id = null, basic = false) => {
    const params = new URLSearchParams({ edition: String(state.catalog.source.id) });
    if (basic) params.set("basic", "1");
    return (id === null ? "/fiqh" : "/fiqh/nodes/" + encodeURIComponent(id)) + "?" + params;
  };
  const link = (text, id, action, attributes = {}) => {
    const node = element("a", text, { href: href(id), ...attributes });
    node.addEventListener("click", event => {
      if (event.defaultPrevented || event.button > 0 || event.ctrlKey || event.metaKey || event.shiftKey || event.altKey) return;
      event.preventDefault();
      action();
    });
    return node;
  };
  const nodes = () => {
    const result = new Map();
    if (state.catalog) for (const node of [...state.catalog.books, ...state.catalog.introductions]) result.set(node.id, node);
    for (const group of state.groups.values()) for (const node of group.items) result.set(node.id, node);
    return result;
  };
  const lineage = node => {
    const lookup = nodes(), trail = [node];
    for (let parent = lookup.get(node.parent_id); parent; parent = lookup.get(parent.parent_id)) trail.unshift(parent);
    return trail;
  };
  const citation = node => "الجزء: " + (node.source.printed_part ?? "غير متاح") +
    "، الصفحة المطبوعة: " + (node.source.printed_page === null ? "غير متاحة" : number.format(node.source.printed_page));
  const publication = node => node.source.work_title + " — " + node.source.edition + "؛ " + node.source.publisher;
  const snapshot = () => ({ root: state.root, selected: state.selected, focusId: state.focusId,
    expanded: [...state.expanded], groups: [...state.groups], searchPage: state.searchPage,
    searchOptions: state.searchOptions, query: get("search-query").value,
    scope: get("search-scope").value, mode: get("search-mode").value });
  function remember(mode = "replace", id = undefined) {
    if (!state.initialized || !view?.history || !state.catalog.source) return;
    const url = id === undefined ? view.location.href : href(id);
    const previous = view.history.state;
    const data = { ...(previous && typeof previous === "object" ? previous : {}),
      fatwaCatalog: { version: 1, edition: state.catalog.source.id, snapshot: snapshot() } };
    try {
      const target = new URL(url, view.location.href);
      const method = mode === "push" && target.href !== view.location.href ? "pushState" : "replaceState";
      view.history[method](data, "", target.href);
    } catch { /* Links and SSR remain usable if history storage is unavailable. */ }
  }
  function showSelection(node, trail = lineage(node)) {
    state.selected = node;
    for (const item of get("tree").querySelectorAll('[role="treeitem"]')) item.setAttribute("aria-selected", String(item.dataset.id === node.id));
    const list = element("ol", null);
    const home = element("li", null);
    home.append(link("جذور الفهرس", null, () => void homeCatalog()));
    list.append(home);
    for (const ancestor of trail) {
      const li = element("li", null);
      if (ancestor.id === node.id) li.append(element("span", ancestor.title, { "aria-current": "page" }));
      else li.append(link(ancestor.title, ancestor.id, () => void openResult(ancestor.id)));
      list.append(li);
    }
    get("breadcrumbs").replaceChildren(list);
    get("reference-content").replaceChildren(
      element("p", node.title, { class: "selected-title" }),
      element("p", publication(node)), element("p", citation(node)),
      element("a", "رابط هذا العنوان", { href: href(node.id) }),
    );
    get("basic-link")?.setAttribute("href", href(node.id, true));
    doc.title = node.title + " — فهرس المرجع";
  }
  function setFocus(id, focus = true) {
    state.focusId = id;
    const items = [...get("tree").querySelectorAll('[role="treeitem"]')];
    for (const item of items) item.tabIndex = item.dataset.id === id ? 0 : -1;
    if (focus) items.find(item => item.dataset.id === id)?.focus();
  }
  function collapse(node, { activate = false } = {}) {
    cancel("treeRequest");
    busy("tree-region", false);
    const index = state.expanded.indexOf(node.id);
    if (index >= 0) {
      state.expanded.splice(index);
      for (const key of state.groups.keys()) if (!state.expanded.includes(key)) state.groups.delete(key);
    }
    state.focusId = node.id;
    // Keep selection visible when its branch is removed.
    const hiddenSelection = state.selected && !nodes().has(state.selected.id);
    if (activate || hiddenSelection) showSelection(node);
    renderTree(true);
    remember(activate || hiddenSelection ? "push" : "replace", activate || hiddenSelection ? node.id : undefined);
    announce("تم طي العنوان.");
  }
  function renderTree(focus = false) {
    const previous = doc.activeElement?.closest?.('[role="treeitem"]')?.dataset.id;
    const wanted = state.focusId ?? state.root?.id;
    let rendered = 0;
    const renderNode = node => {
      if (++rendered > MAX_TREE_ITEMS) throw new Error("Tree rendering budget exceeded");
      const expanded = state.expanded.includes(node.id);
      const attributes = { role: "treeitem", tabindex: node.id === wanted ? 0 : -1,
        "aria-level": node.depth, "aria-posinset": node.parent_id ? node.sibling_ordinal : 1,
        "aria-setsize": node.parent_id ? node.sibling_total : 1,
        "aria-selected": node.id === state.selected?.id, "aria-label": node.title, class: "tree-item" };
      if (node.has_children) attributes["aria-expanded"] = expanded;
      const item = element("div", null, attributes);
      item.dataset.id = node.id;
      const row = element("div", null, { class: "tree-row" });
      row.append(element("span", node.has_children ? (expanded ? "−" : "+") : "·", { class: "marker", "aria-hidden": "true" }), element("span", node.title));
      item.append(row);
      item.addEventListener("focus", () => setFocus(node.id, false));
      const activate = () => {
        if (node.has_children) void (expanded ? collapse(node, { activate: true }) : expand(node));
        else { showSelection(node); remember("push", node.id); announce("تم اختيار العنوان المرجعي."); }
      };
      item.addEventListener("click", event => {
        if (event.target.closest('[role="treeitem"]') !== item) return;
        item.focus(); activate();
      });
      item.addEventListener("keydown", event => {
        if (event.target !== item || event.ctrlKey || event.metaKey || event.altKey) return;
        const visible = [...get("tree").querySelectorAll('[role="treeitem"]')];
        const index = visible.indexOf(item);
        let target;
        if (event.key === "ArrowDown") target = visible[Math.min(visible.length - 1, index + 1)];
        else if (event.key === "ArrowUp") target = visible[Math.max(0, index - 1)];
        else if (event.key === "Home") target = visible[0];
        else if (event.key === "End") target = visible.at(-1);
        else if (event.key === "ArrowLeft") {
          if (node.has_children && !expanded) void expand(node, { navigate: false });
          else target = item.querySelector('[role="group"] > [role="treeitem"]');
        } else if (event.key === "ArrowRight") {
          if (expanded) collapse(node);
          else target = item.parentElement.closest('[role="treeitem"]');
        } else if (event.key === "Enter" || event.key === " ") activate();
        else return;
        event.preventDefault(); target?.focus();
      });
      if (expanded) {
        const children = element("div", null, { role: "group" });
        for (const child of state.groups.get(node.id)?.items ?? []) children.append(renderNode(child));
        item.append(children);
      }
      return item;
    };
    get("tree").replaceChildren(...(state.root ? [renderNode(state.root)] : []));
    const visible = [...get("tree").querySelectorAll('[role="treeitem"]')];
    if (!visible.some(item => item.tabIndex === 0) && visible[0]) { visible[0].tabIndex = 0; state.focusId = state.root.id; }
    renderTreePager();
    if (focus || previous) setFocus(visible.some(item => item.dataset.id === wanted) ? wanted : state.root.id);
  }
  function renderTreePager() {
    get("tree-pagination").replaceChildren();
    const lookup = nodes();
    // Every open ancestor keeps its own pager, including after a deep-result reveal.
    for (const parentId of state.expanded) {
      const group = state.groups.get(parentId), parent = lookup.get(parentId);
      if (!group || !parent) continue;
      const wrapper = element("div", null, { class: "pagination" });
      const start = group.items.length ? group.offset + 1 : 0;
      wrapper.append(element("span", "تحت «" + parent.title + "»: " + number.format(start) + "–" + number.format(group.offset + group.items.length) + " من " + number.format(group.total)));
      if (!group.items.length) wrapper.append(element("p", "لا توجد عناوين فرعية."));
      for (const [label, cursor] of [["الصفحة السابقة", group.previous_cursor], ["الصفحة التالية", group.next_cursor]]) {
        if (cursor !== null) wrapper.append(button(label, () => void expand(parent, { cursor }), { "aria-label": label + " لعناوين " + parent.title }));
      }
      get("tree-pagination").append(wrapper);
    }
  }
  async function expand(node, { cursor = null, focus = true, navigate = true } = {}) {
    const request = begin("treeRequest"), trail = lineage(node);
    busy("tree-region", true); announce("جارٍ تحميل العناوين الفرعية…");
    try {
      const group = await adapter.children(node.id, { cursor, signal: request.signal });
      if (!current("treeRequest", request)) return false;
      state.expanded = trail.map(n => n.id);
      for (const id of state.groups.keys()) if (!state.expanded.includes(id)) state.groups.delete(id);
      state.groups.set(node.id, group); state.focusId = node.id;
      const select = navigate || (state.selected && !nodes().has(state.selected.id));
      if (select) showSelection(node, trail);
      renderTree(focus);
      remember(select ? "push" : "replace", select ? node.id : undefined);
      announce(group.items.length ? "تم تحميل " + number.format(group.items.length) + " عنوانًا فرعيًا." : "لا توجد عناوين فرعية.");
      return true;
    } catch (error) {
      if (current("treeRequest", request) && error.name !== "AbortError") failure(() => void expand(node, { cursor, focus, navigate }));
      return false;
    } finally { if (current("treeRequest", request)) busy("tree-region", false); }
  }
  function markRoot() {
    for (const navigation of [get("books"), get("introductions")]) for (const control of navigation.querySelectorAll("a")) {
      if (control.dataset.id === state.root?.id) control.setAttribute("aria-current", "true");
      else control.removeAttribute("aria-current");
    }
  }
  async function chooseRoot(root, { focus = true, navigate = true } = {}) {
    cancel("treeRequest");
    state.root = root; state.focusId = root.id; state.expanded = []; state.groups.clear();
    markRoot(); showSelection(root, [root]); renderTree(focus);
    if (navigate) remember("push", root.id);
    if (root.has_children) return expand(root, { focus, navigate: false });
    busy("tree-region", false); announce("هذا العنوان بلا عناوين فرعية.");
    return true;
  }
  async function openResult(id, { focus = true, navigate = true } = {}) {
    const request = begin("treeRequest");
    busy("tree-region", true); announce("جارٍ فتح مسار العنوان…");
    try {
      const detail = await adapter.node(id, { signal: request.signal }), groups = new Map();
      for (let index = 0; index < detail.breadcrumbs.length - 1; index++) {
        if (!current("treeRequest", request)) return false;
        const parent = detail.breadcrumbs[index], child = detail.breadcrumbs[index + 1];
        groups.set(parent.id, await adapter.children(parent.id, { anchorId: child.id, signal: request.signal }));
      }
      if (!current("treeRequest", request)) return false;
      // A direct link to a branch displays its children as well as its ancestors.
      if (detail.node.has_children) groups.set(id, await adapter.children(id, { signal: request.signal }));
      if (!current("treeRequest", request)) return false;
      state.root = detail.breadcrumbs[0]; state.groups = groups; state.expanded = [...groups.keys()]; state.focusId = id;
      markRoot(); showSelection(detail.node, detail.breadcrumbs); renderTree(focus);
      remember(navigate ? "push" : "replace", navigate ? id : undefined);
      announce("تم فتح مسار العنوان المرجعي.");
      return true;
    } catch (error) {
      if (current("treeRequest", request) && error.name !== "AbortError") failure(() => void openResult(id, { focus, navigate }), error.code === "NOT_FOUND" ? "لم يعد هذا العنوان متاحًا. يمكنك العودة إلى جذور الفهرس." : undefined);
      return false;
    } finally { if (current("treeRequest", request)) busy("tree-region", false); }
  }
  function renderSearch(focus = false) {
    const result = state.searchPage, options = state.searchOptions;
    if (!result) { get("search-results").replaceChildren(); return; }
    const heading = element("h3", "نتائج البحث: " + number.format(result.total), { tabindex: "-1" });
    const list = element("ol", null, { class: "result-list", start: result.offset + 1 });
    for (const node of result.items) {
      const item = element("li", null);
      item.append(link(node.title, node.id, () => void openResult(node.id)),
        element("p", publication(node)), element("p", citation(node)));
      list.append(item);
    }
    const pager = element("nav", null, { class: "pagination", "aria-label": "صفحات نتائج البحث" });
    for (const [label, token] of [["نتائج سابقة", result.previous_cursor], ["نتائج تالية", result.next_cursor]]) {
      if (token !== null) pager.append(button(label, () => void search({ ...options, cursor: token }, true)));
    }
    get("search-results").replaceChildren(heading, result.items.length ? list : element("p", "لم نعثر على عناوين تطابق البحث."), pager);
    if (focus) heading.focus();
  }
  async function search(options, focus = true) {
    const request = begin("searchRequest");
    busy("search-results", true); get("search-query").removeAttribute("aria-invalid");
    get("search-results").replaceChildren(element("p", "جارٍ البحث في العناوين…")); announce("جارٍ البحث…");
    try {
      const result = await adapter.search(options.query, { rootId: options.rootId, cursor: options.cursor, mode: options.mode, signal: request.signal });
      if (!current("searchRequest", request)) return;
      state.searchPage = result; state.searchOptions = options; renderSearch(focus); remember();
      announce("اكتمل البحث. عدد النتائج: " + number.format(result.total));
    } catch (error) {
      if (current("searchRequest", request) && error.name !== "AbortError") {
        state.searchPage = null; state.searchOptions = null; get("search-results").replaceChildren();
        if (error.code === "INVALID_QUERY") get("search-query").setAttribute("aria-invalid", "true");
        failure(() => void search(options, focus), error.code === "INVALID_QUERY" ? "أدخل حتى ١٦٠ حرفًا وعشر كلمات، دون محارف تحكم." : "تعذّر البحث في العناوين. حاول مرة أخرى.");
        remember();
      }
    } finally { if (current("searchRequest", request)) busy("search-results", false); }
  }
  const submit = event => {
    event.preventDefault();
    void search({ query: get("search-query").value, rootId: get("search-scope").value || null, cursor: null, mode: get("search-mode").value });
  };
  const clearSearch = () => {
    cancel("searchRequest"); state.searchPage = null; state.searchOptions = null;
    get("search-query").value = ""; get("search-query").removeAttribute("aria-invalid");
    get("search-results").replaceChildren(); busy("search-results", false); clearError(); remember();
    announce("تم مسح البحث."); get("search-query").focus();
  };
  async function homeCatalog({ navigate = true, focus = true } = {}) {
    const first = state.catalog.books[0] ?? state.catalog.introductions[0];
    if (!first) return;
    await chooseRoot(first, { focus: false, navigate: false });
    if (navigate) remember("push", null);
    get("basic-link")?.setAttribute("href", href(null, true));
    if (focus) get("books").querySelector("a")?.focus();
  }
  const homeClick = event => {
    if (event.button > 0 || event.ctrlKey || event.metaKey || event.shiftKey || event.altKey) return;
    event.preventDefault(); void homeCatalog();
  };
  const pop = async event => {
    for (const lane of ["treeRequest", "searchRequest"]) cancel(lane);
    busy("tree-region", false); busy("search-results", false); clearError();
    const saved = event.state?.fatwaCatalog;
    if (saved?.version === 1 && saved.edition === state.catalog.source?.id) {
      const data = saved.snapshot;
      state.root = data.root; state.selected = data.selected; state.focusId = data.focusId;
      state.groups = new Map(data.groups); state.expanded = [...data.expanded];
      state.searchPage = data.searchPage; state.searchOptions = data.searchOptions;
      get("search-query").value = data.query; get("search-scope").value = data.scope; get("search-mode").value = data.mode;
      get("search-query").removeAttribute("aria-invalid");
      markRoot(); showSelection(state.selected); renderTree(true); renderSearch();
      announce("تمت استعادة موضعك في الفهرس.");
    } else {
      const match = view.location.pathname.match(new RegExp("^/fiqh/nodes/([1-9][0-9]*)$"));
      if (match) await openResult(match[1], { navigate: false });
      else await homeCatalog({ navigate: false });
    }
  };
  get("search-form").addEventListener("submit", submit);
  get("clear-search").addEventListener("click", clearSearch);
  get("catalog-home")?.addEventListener("click", homeClick);
  view?.addEventListener("popstate", pop);
  async function start() {
    const request = begin("catalogRequest");
    busy("tree-region", true); announce("جارٍ تحميل جذور الفهرس…");
    try {
      const catalog = await adapter.catalog({ signal: request.signal });
      if (!current("catalogRequest", request)) return;
      state.catalog = catalog;
      for (const [id, collection] of [["books", catalog.books], ["introductions", catalog.introductions]]) {
        get(id).replaceChildren(...collection.map(root => {
          const control = link(root.title, root.id, () => void chooseRoot(root)); control.dataset.id = root.id; return control;
        }));
      }
      get("search-scope").replaceChildren(element("option", "جميع جذور الفهرس", { value: "" }),
        ...[...catalog.books, ...catalog.introductions].map(root => element("option", root.title, { value: root.id })));
      get("intro-heading").hidden = catalog.introductions.length === 0;
      const first = catalog.books[0] ?? catalog.introductions[0];
      if (!first) {
        get("tree").replaceChildren(); get("tree").removeAttribute("role");
        get("tree-region").append(element("p", "لم يُحمّل فهرس مرجعي بعد."));
        get("search-form").hidden = true; busy("tree-region", false); announce("لا يوجد فهرس متاح حاليًا.");
      } else {
        const success = initialNode ? await openResult(initialNode, { focus: false, navigate: false }) : await chooseRoot(first, { focus: false, navigate: false });
        if (!success || !current("catalogRequest", request)) return;
      }
      state.initialized = true; onCatalog(catalog);
      if (catalog.source) {
        get("catalog-home")?.setAttribute("href", href());
        remember();
      }
      if (get("request-status")) get("request-status").replaceChildren();
    } catch (error) {
      if (current("catalogRequest", request) && error.name !== "AbortError") { busy("tree-region", false); failure(() => void start()); }
    }
  }
  const ready = start();
  return { ready, destroy() {
    state.disposed = true;
    for (const lane of ["treeRequest", "searchRequest", "catalogRequest"]) cancel(lane);
    get("search-form").removeEventListener("submit", submit); get("clear-search").removeEventListener("click", clearSearch);
    get("catalog-home")?.removeEventListener("click", homeClick); view?.removeEventListener("popstate", pop);
  } };
}
const panel = globalThis.document?.getElementById("interactive-catalog");
if (panel) {
  const fallback = document.getElementById("server-catalog");
  const adapter = createDjangoAdapter({ editionId: panel.dataset.edition || null });
  mount(adapter, document, { initialNode: panel.dataset.node || null, onCatalog(catalog) {
    panel.hidden = false; fallback.hidden = true;
    document.querySelector(".skip-link").href = "#catalog-panel";
    const source = catalog.source;
    document.getElementById("source-summary").textContent = source
      ? source.work.title_original + "؛ " + source.publisher + "؛ المذهب: " + source.work.madhhab + "؛ عدد العناوين: " + number.format(catalog.totals.nodes)
      : "لم يُحمّل فهرس مرجعي بعد.";
  } });
}
