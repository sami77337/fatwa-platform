// Small deterministic DOM/event harness for Node interaction regressions.
// This does not implement a layout engine or substitute for browser/AX testing.
export class Element {
  constructor(tag, doc) { this.tagName = tag.toUpperCase(); this.doc = doc; this.children = []; this.parentElement = null; this.attributes = new Map(); this.dataset = {}; this.listeners = new Map(); this.hidden = false; this.value = ""; this._text = ""; }
  setAttribute(key, value) { this.attributes.set(key, String(value)); if (key === "value") this.value = String(value); }
  getAttribute(key) { return key.startsWith("data-") ? this.dataset[key.slice(5)] ?? this.attributes.get(key) ?? null : this.attributes.get(key) ?? null; }
  removeAttribute(key) { this.attributes.delete(key); }
  get tabIndex() { return Number(this.getAttribute("tabindex") ?? -1); }
  set tabIndex(value) { this.setAttribute("tabindex", value); }
  get textContent() { return this._text + this.children.map(child => child.textContent).join(""); }
  set textContent(value) { this.replaceChildren(); this._text = String(value); }
  append(...nodes) { for (const node of nodes) { node.parentElement = this; this.children.push(node); } }
  replaceChildren(...nodes) { for (const node of this.children) node.parentElement = null; this.children = []; this._text = ""; this.append(...nodes); }
  addEventListener(type, listener) { if (!this.listeners.has(type)) this.listeners.set(type, new Set()); this.listeners.get(type).add(listener); }
  removeEventListener(type, listener) { this.listeners.get(type)?.delete(listener); }
  matches(selector) {
    const match = selector.match(/^([a-z][a-z0-9]*)?(?:\.([\w-]+))?(?:\[([\w-]+)(?:=["']?([^"'\]]+)["']?)?\])?$/i);
    if (!match) throw Error("Unsupported harness selector: " + selector);
    return (!match[1] || this.tagName.toLowerCase() === match[1]) && (!match[2] || (this.getAttribute("class") ?? "").split(" ").includes(match[2])) && (!match[3] || (match[4] === undefined ? this.getAttribute(match[3]) !== null : this.getAttribute(match[3]) === match[4]));
  }
  closest(selector) { for (let node = this; node; node = node.parentElement) if (node.matches(selector)) return node; return null; }
  querySelectorAll(selector) {
    const parts = selector.split(/\s*>\s*/);
    const descendants = [];
    const visit = node => { for (const child of node.children) { descendants.push(child); visit(child); } }; visit(this);
    if (parts.length === 2) return descendants.filter(node => node.matches(parts[1]) && node.parentElement?.matches(parts[0]));
    return descendants.filter(node => node.matches(selector));
  }
  querySelector(selector) { return this.querySelectorAll(selector)[0] ?? null; }
  focus() { this.doc.activeElement = this; this.dispatch("focus", {}, false); }
  dispatch(type, values = {}, bubbles = true) {
    const event = { target: this, button: 0, defaultPrevented: false, preventDefault() { this.defaultPrevented = true; }, ...values };
    for (let node = this; node; node = bubbles ? node.parentElement : null) for (const handler of [...(node.listeners.get(type) ?? [])]) handler(event);
    return event;
  }
  click(values) { return this.dispatch("click", values); }
  key(key) { return this.dispatch("keydown", { key }); }
}
export function documentHarness(url = "http://localhost/fiqh") {
  const listeners = new Map();
  const view = { location: new URL(url), addEventListener(type, handler) { if (!listeners.has(type)) listeners.set(type, new Set()); listeners.get(type).add(handler); }, removeEventListener(type, handler) { listeners.get(type)?.delete(handler); } };
  const entries = [{ url, state: null }]; let index = 0;
  view.history = {
    get state() { return entries[index].state; }, get length() { return entries.length; },
    replaceState(state, _unused, href) { entries[index] = { state: structuredClone(state), url: href }; view.location = new URL(href); },
    pushState(state, _unused, href) { entries.splice(index + 1); entries.push({ state: structuredClone(state), url: href }); index++; view.location = new URL(href); },
    async go(delta) { if (!entries[index + delta]) return; index += delta; view.location = new URL(entries[index].url); for (const handler of listeners.get("popstate") ?? []) await handler({ state: entries[index].state }); },
    back() { return this.go(-1); }, forward() { return this.go(1); },
  };
  const doc = { defaultView: view, activeElement: null, title: "فهرس المرجع", createElement(tag) { return new Element(tag, doc); }, getElementById(id) { return ids.get(id) ?? null; } };
  const ids = new Map();
  for (const id of ["tree", "tree-region", "tree-pagination", "status", "error", "request-status", "breadcrumbs", "reference-content", "basic-link", "catalog-home", "books", "introductions", "intro-heading", "search-form", "search-query", "search-mode", "search-scope", "search-depth", "search-has_children", "search-results", "clear-search"]) ids.set(id, doc.createElement(id.includes("link") || id === "catalog-home" ? "a" : id === "search-query" ? "input" : "div"));
  doc.getElementById("search-mode").value = "normalized";
  doc.getElementById("tree").setAttribute("role", "tree");
  return doc;
}
export const settle = async () => { for (let i = 0; i < 8; i++) await new Promise(resolve => setImmediate(resolve)); };
export const deferred = () => { let resolve, reject; const promise = new Promise((yes, no) => { resolve = yes; reject = no; }); return { promise, resolve, reject }; };
