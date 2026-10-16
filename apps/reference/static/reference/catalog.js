import { createDjangoAdapter } from "./django-api.mjs";

const number = new Intl.NumberFormat("ar", { useGrouping: false });
export const MAX_TREE_ITEMS = 81; // One root + 20 siblings at each of four levels.
export function mount(adapter, doc = document, { initialNode = null, onCatalog = () => {} } = {}) {
  const get = id => doc.getElementById(id);
  const state = { catalog: null, root: null, selected: null, focusId: null, expanded: [], groups: new Map(), treeRequest: null, searchRequest: null, catalogRequest: null, disposed: false };
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
  const failure = (retry, message = "تعذّر تحميل البيانات. حاول مرة أخرى.") => {
    get("error").replaceChildren(element("p", message), button("إعادة المحاولة", retry));
    announce("تعذّر إتمام الطلب.");
  };
  const busy = (id, value) => get(id).setAttribute("aria-busy", String(value));
  const current = (lane, request) => state[lane] === request && !state.disposed;
  const begin = lane => {
    state[lane]?.abort();
    const request = new AbortController();
    state[lane] = request;
    clearError();
    return request;
  };
  const nodes = () => {
    const result = new Map();
    if (state.catalog) for (const node of [...state.catalog.books, ...state.catalog.introductions]) result.set(node.id, node);
    for (const group of state.groups.values()) for (const node of group.items) result.set(node.id, node);
    return result;
  };
  const lineage = node => {
    const lookup = nodes();
    const trail = [node];
    for (let parent = lookup.get(node.parent_id); parent; parent = lookup.get(parent.parent_id)) trail.unshift(parent);
    return trail;
  };
  const sourceLabel = node => node.source.synthetic ? "عنوان مرجعي تجريبي — ليس فتوى" : "عنوان مرجعي — ليس فتوى";
  const citation = node => {
    const part = node.source.printed_part === null ? "غير متاح" : String(node.source.printed_part);
    const page = node.source.printed_page === null ? "غير متاحة" : number.format(node.source.printed_page);
    return "الجزء: " + part + "، الصفحة المطبوعة: " + page;
  };
  function showSelection(node, trail = lineage(node)) {
    state.selected = node;
    for (const item of get("tree").querySelectorAll('[role="treeitem"]')) item.setAttribute("aria-selected", String(item.dataset.id === node.id));
    const list = element("ol", null);
    for (const ancestor of trail) {
      const li = element("li", null);
      if (ancestor.id === node.id) li.append(element("span", ancestor.title, { "aria-current": "location" }));
      else li.append(button(ancestor.title, () => {
        const target = [...get("tree").querySelectorAll('[role="treeitem"]')].find(item => item.dataset.id === ancestor.id);
        if (target) { target.focus(); showSelection(ancestor); }
        else void openResult(ancestor.id);
      }));
      list.append(li);
    }
    get("breadcrumbs").replaceChildren(list);
    if (state.catalog?.source) {
      const url = new URL(location.href);
      url.pathname = "/fiqh/nodes/" + node.id;
      url.search = new URLSearchParams({ edition: String(state.catalog.source.id) });
      history.replaceState(null, "", url);
    }
    get("reference-content").replaceChildren(
      element("p", node.title),
      element("span", sourceLabel(node), { class: "badge" }),
      element("p", node.source.work_title + " — " + node.source.edition + " — المذهب: " + node.source.madhhab),
      element("p", citation(node)),
      element("p", "معرّف العنوان الأصلي: " + node.source.source_id + "؛ معرّف صفحة المصدر: " + node.source.page_id),
      element("a", "رابط هذا العنوان", { href: "/fiqh/nodes/" + encodeURIComponent(node.id) + "?edition=" + encodeURIComponent(state.catalog.source.id) }),
    );
  }
  function setFocus(id) {
    state.focusId = id;
    const items = [...get("tree").querySelectorAll('[role="treeitem"]')];
    for (const item of items) item.tabIndex = item.dataset.id === id ? 0 : -1;
    items.find(item => item.dataset.id === id)?.focus();
  }
  function collapse(node) {
    state.treeRequest?.abort();
    state.treeRequest = null;
    busy("tree-region", false);
    const index = state.expanded.indexOf(node.id);
    if (index >= 0) {
      state.expanded.splice(index);
      for (const key of state.groups.keys()) if (!state.expanded.includes(key)) state.groups.delete(key);
    }
    state.focusId = node.id;
    showSelection(node);
    renderTree(true);
    announce("تم طي العنوان.");
  }
  function renderTree(focus = false) {
    const previous = doc.activeElement?.closest?.('[role="treeitem"]')?.dataset.id;
    const wanted = state.focusId ?? state.root?.id;
    const lookup = nodes();
    let rendered = 0;
    const renderNode = node => {
      if (++rendered > MAX_TREE_ITEMS) throw new Error("Tree rendering budget exceeded");
      const expanded = state.expanded.includes(node.id);
      const attributes = {
        role: "treeitem", tabindex: node.id === wanted ? 0 : -1,
        "aria-level": node.depth, "aria-posinset": node.parent_id ? node.position + 1 : 1,
        "aria-setsize": node.parent_id ? lookup.get(node.parent_id)?.child_count ?? 1 : 1,
        "aria-selected": node.id === state.selected?.id,
        "aria-label": node.title,
        class: "tree-item",
      };
      if (node.has_children) attributes["aria-expanded"] = expanded;
      const item = element("div", null, attributes);
      item.dataset.id = node.id;
      const row = element("div", null, { class: "tree-row" });
      row.append(element("span", node.has_children ? (expanded ? "−" : "+") : "·", { class: "marker", "aria-hidden": "true" }), element("span", node.title));
      item.append(row);
      item.addEventListener("focus", () => {
        state.focusId = node.id;
        for (const other of get("tree").querySelectorAll('[role="treeitem"]')) other.tabIndex = other === item ? 0 : -1;
        showSelection(node);
      });
      item.addEventListener("click", event => {
        if (event.target.closest('[role="treeitem"]') !== item) return;
        item.focus();
        if (node.has_children) void (expanded ? collapse(node) : expand(node));
      });
      item.addEventListener("keydown", event => {
        if (event.target !== item) return;
        const visible = [...get("tree").querySelectorAll('[role="treeitem"]')];
        const index = visible.indexOf(item);
        let target;
        if (event.key === "ArrowDown") target = visible[Math.min(visible.length - 1, index + 1)];
        else if (event.key === "ArrowUp") target = visible[Math.max(0, index - 1)];
        else if (event.key === "Home") target = visible[0];
        else if (event.key === "End") target = visible.at(-1);
        else if (event.key === "ArrowLeft") {
          if (node.has_children && !expanded) void expand(node);
          else target = item.querySelector('[role="group"] > [role="treeitem"]');
        } else if (event.key === "ArrowRight") {
          if (expanded) collapse(node);
          else target = item.parentElement.closest('[role="treeitem"]');
        } else if (event.key === "Enter" || event.key === " ") {
          if (node.has_children) void (expanded ? collapse(node) : expand(node));
          else showSelection(node);
        } else return;
        event.preventDefault();
        target?.focus();
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
    if (visible.length > MAX_TREE_ITEMS) throw new Error("Tree rendering budget exceeded");
    if (!visible.some(item => item.tabIndex === 0) && visible[0]) {
      visible[0].tabIndex = 0;
      state.focusId = state.root.id;
    }
    renderTreePager();
    if (focus || previous) setFocus(visible.some(item => item.dataset.id === wanted) ? wanted : state.root.id);
  }
  function renderTreePager() {
    const parentId = state.expanded.at(-1);
    const group = state.groups.get(parentId);
    const parent = nodes().get(parentId);
    get("tree-pagination").replaceChildren();
    if (!group || !parent) return;
    const wrapper = element("div", null, { class: "pagination" });
    wrapper.append(element("span", "عناوين مباشرة تحت «" + parent.title + "»: " + number.format(group.total)));
    if (!group.items.length) wrapper.append(element("p", "لا توجد عناوين فرعية."));
    for (const [label, cursor] of [["الصفحة السابقة", group.previous_cursor], ["الصفحة التالية", group.next_cursor]]) {
      if (cursor === null) continue;
      wrapper.append(button(label, () => void expand(parent, { cursor, focus: true }), { "aria-label": label + " لعناوين " + parent.title }));
    }
    get("tree-pagination").append(wrapper);
  }
  async function expand(node, { cursor = null, focus = true } = {}) {
    const request = begin("treeRequest");
    busy("tree-region", true);
    announce("جارٍ تحميل العناوين الفرعية…");
    const trail = lineage(node);
    try {
      const group = await adapter.children(node.id, { cursor, signal: request.signal });
      if (!current("treeRequest", request)) return;
      state.expanded = trail.map(n => n.id);
      for (const id of state.groups.keys()) if (!state.expanded.includes(id)) state.groups.delete(id);
      state.groups.set(node.id, group);
      state.focusId = node.id;
      showSelection(node, trail);
      renderTree(focus);
      announce(group.items.length ? "تم تحميل " + number.format(group.items.length) + " عنوانًا فرعيًا." : "لا توجد عناوين فرعية.");
    } catch (error) {
      if (current("treeRequest", request) && error.name !== "AbortError") failure(() => void expand(node, { cursor, focus }));
    } finally { if (current("treeRequest", request)) busy("tree-region", false); }
  }
  function markRoot() {
    for (const navigation of [get("books"), get("introductions")]) for (const control of navigation.querySelectorAll("button")) {
      if (control.dataset.id === state.root?.id) control.setAttribute("aria-current", "page");
      else control.removeAttribute("aria-current");
    }
  }
  async function chooseRoot(root, { focus = true } = {}) {
    state.treeRequest?.abort();
    state.treeRequest = null;
    state.root = root;
    state.focusId = root.id;
    state.expanded = [];
    state.groups.clear();
    markRoot();
    showSelection(root, [root]);
    renderTree(focus);
    if (root.has_children) await expand(root, { focus });
    else { busy("tree-region", false); announce("هذا العنوان بلا عناوين فرعية."); }
  }
  async function openResult(id) {
    const request = begin("treeRequest");
    busy("tree-region", true);
    announce("جارٍ فتح مسار العنوان…");
    try {
      const detail = await adapter.node(id, { signal: request.signal });
      const groups = new Map();
      for (let index = 0; index < detail.breadcrumbs.length - 1; index++) {
        const parent = detail.breadcrumbs[index];
        const child = detail.breadcrumbs[index + 1];
        const group = await adapter.children(parent.id, { anchorId: child.id, signal: request.signal });
        groups.set(parent.id, group);
      }
      if (!current("treeRequest", request)) return;
      state.root = detail.breadcrumbs[0];
      state.groups = groups;
      state.expanded = [...groups.keys()];
      state.focusId = id;
      markRoot();
      showSelection(detail.node, detail.breadcrumbs);
      renderTree(true);
      announce("تم فتح مسار العنوان المرجعي.");
    } catch (error) {
      if (current("treeRequest", request) && error.name !== "AbortError") failure(() => void openResult(id));
    } finally { if (current("treeRequest", request)) busy("tree-region", false); }
  }
  async function search(query, rootId, cursor = null, focus = false) {
    const request = begin("searchRequest");
    busy("search-results", true);
    get("search-query").removeAttribute("aria-invalid");
    get("search-results").replaceChildren(element("p", "جارٍ البحث في العناوين…"));
    announce("جارٍ البحث…");
    try {
      const result = await adapter.search(query, { rootId, cursor, mode: get("search-mode").value, signal: request.signal });
      if (!current("searchRequest", request)) return;
      const heading = element("h3", "نتائج البحث: " + number.format(result.total), { tabindex: "-1" });
      const list = element("ol", null, { class: "result-list" });
      for (const node of result.items) {
        const item = element("li", null);
        item.append(button(node.title, () => void openResult(node.id)), element("p", sourceLabel(node), { class: "badge" }),
          element("p", node.source.work_title + " — " + node.source.edition + " — المذهب: " + node.source.madhhab), element("p", citation(node)));
        list.append(item);
      }
      const pager = element("div", null, { class: "pagination" });
      for (const [label, token] of [["نتائج سابقة", result.previous_cursor], ["نتائج تالية", result.next_cursor]]) {
        if (token !== null) pager.append(button(label, () => void search(query, rootId, token, true)));
      }
      get("search-results").replaceChildren(heading, result.items.length ? list : element("p", "لم نعثر على عناوين تطابق البحث."), pager);
      if (focus) heading.focus();
      announce("اكتمل البحث. عدد النتائج: " + number.format(result.total));
    } catch (error) {
      if (current("searchRequest", request) && error.name !== "AbortError") {
        get("search-results").replaceChildren();
        if (error.code === "INVALID_QUERY") get("search-query").setAttribute("aria-invalid", "true");
        const message = error.code === "INVALID_QUERY" ? "أدخل حتى ١٦٠ حرفًا وعشر كلمات للبحث." : "تعذّر البحث في العناوين. حاول مرة أخرى.";
        failure(() => void search(query, rootId, cursor, focus), message);
      }
    } finally { if (current("searchRequest", request)) busy("search-results", false); }
  }
  const submit = event => {
    event.preventDefault();
    void search(get("search-query").value, get("search-scope").value || null);
  };
  const clearSearch = () => {
    state.searchRequest?.abort();
    state.searchRequest = null;
    get("search-query").value = "";
    get("search-query").removeAttribute("aria-invalid");
    get("search-results").replaceChildren();
    busy("search-results", false);
    clearError();
    announce("تم مسح البحث.");
    get("search-query").focus();
  };
  get("search-form").addEventListener("submit", submit);
  get("clear-search").addEventListener("click", clearSearch);
  async function start() {
    const request = begin("catalogRequest");
    busy("tree-region", true);
    announce("جارٍ تحميل قائمة الكتب…");
    try {
      const catalog = await adapter.catalog({ signal: request.signal });
      if (!current("catalogRequest", request)) return;
      state.catalog = catalog;
      for (const [id, collection] of [["books", catalog.books], ["introductions", catalog.introductions]]) {
        get(id).replaceChildren(...collection.map(root => {
          const control = button(root.title, () => void chooseRoot(root));
          control.dataset.id = root.id;
          return control;
        }));
      }
      onCatalog(catalog);
      const all = element("option", "جميع جذور هذه الطبعة", { value: "" });
      get("search-scope").replaceChildren(all, ...[...catalog.books, ...catalog.introductions].map(root => element("option", root.title, { value: root.id })));
      const first = catalog.books[0] ?? catalog.introductions[0];
      if (!first) {
        get("tree").replaceChildren(element("p", "لم يُحمّل فهرس مرجعي بعد. لا توجد بيانات بديلة مصطنعة."));
        get("search-form").hidden = true;
        busy("tree-region", false);
        announce("لا يوجد فهرس مستورد في قاعدة البيانات.");
      } else if (initialNode) await openResult(initialNode);
      else await chooseRoot(first, { focus: false });
    } catch (error) {
      if (current("catalogRequest", request) && error.name !== "AbortError") { busy("tree-region", false); failure(() => void start());
        const fallbackStatus = get("request-status");
        if (fallbackStatus) fallbackStatus.textContent = "تعذر فتح الواجهة التفاعلية. يمكنك استخدام الفهرس الأساسي المعروض."; }
    }
  }
  const ready = start();
  return { ready, destroy() {
    state.disposed = true;
    for (const lane of ["treeRequest", "searchRequest", "catalogRequest"]) state[lane]?.abort();
    get("search-form").removeEventListener("submit", submit);
    get("clear-search").removeEventListener("click", clearSearch);
  } };
}
const panel = document.getElementById("interactive-catalog");
if (panel) {
  const fallback = document.getElementById("server-catalog");
  const adapter = createDjangoAdapter({ editionId: panel.dataset.edition || null });
  mount(adapter, document, { initialNode: panel.dataset.node || null, onCatalog(catalog) {
    panel.hidden = false;
    fallback.hidden = true;
    document.querySelector(".skip-link").href = "#catalog-panel";
    const source = catalog.source;
    document.getElementById("source-summary").textContent = source
      ? source.work.title_original + " — " + source.title + "؛ " + source.publisher + "؛ المذهب: " + source.work.madhhab + "؛ عدد العناوين: " + number.format(catalog.totals.nodes)
      : "لم يُستورد فهرس مرجعي بعد.";
  } });
}
