// Diagnostic evidence for the failing fixed synthetic queue journey only.
export const tracedCase = "FAST3 filtered prepared queue preserves exact record, revision and malformed recovery";

const queryValues = {
  packet: ["html"],
  revision: ["1"],
  before: ["1"],
  after: ["1"],
  batch: ["synthetic-csv", "synthetic-malformed"],
};
function safeUrl(value, origin) {
  try {
    const url = new URL(value);
    if (url.origin !== origin || url.username || url.password ||
        !/^\/dev\/editorial-(?:queue|workbench)(?:\/batch-synthetic-csv-1)?$/.test(url.pathname)) return "[redacted]";
    const query = new URLSearchParams();
    for (const [key, values] of Object.entries(queryValues)) {
      for (const entry of url.searchParams.getAll(key)) if (values.includes(entry)) query.append(key, entry);
    }
    return url.pathname + (query.size ? "?" + query : "") + (url.hash === "#snapshot" ? url.hash : "");
  } catch { return "[redacted]"; }
}

// Serialized into a CDP evaluation. Keep observations best effort: an error
// collecting evidence must not replace the original focus or assertion outcome.
function observe(selector) {
  try {
    const link = document.querySelector(selector);
    const active = document.activeElement;
    return {
      url: location.href, href: link?.href, ready: document.readyState,
      tag: active?.tagName, id: active?.id, focused: Boolean(link && active === link),
      revision_one: document.querySelector("#snapshot strong")?.textContent === "1",
      snapshot: Boolean(document.querySelector("#snapshot")), packet: Boolean(document.querySelector(".case-packet")),
      error_page: Boolean(document.querySelector("#error-heading")),
    };
  } catch { return null; }
}

export const packetSelector = 'a[href*="packet=html"]';
export function observation(selector) {
  return '(' + observe.toString() + ')(' + JSON.stringify(selector) + ')';
}

// Insert observations into the original evaluations without another CDP round trip.
export function focusCommand(selector, traced) {
  const focus = 'document.querySelector(' + JSON.stringify(selector) + ').focus()';
  if (!traced) return focus;
  const probe = observation(selector);
  return `(() => {const before=${probe}; ${focus}; return [before,${probe}];})()`;
}

export function navigationTrace(origin) {
  const events = [];
  const started = performance.now();
  const report = {events, dropped: 0, capture_errors: 0};
  function add(event, data = {}) {
    if (events.length >= 128) { report.dropped++; return; }
    events.push({seq: events.length + 1, ms: Math.round(performance.now() - started), event, ...data});
  }
  function dom(event, state) {
    if (!state) { report.capture_errors++; return; }
    const snapshot = {
      url: safeUrl(state.url, origin), href: safeUrl(state.href, origin),
      ready: ["loading","interactive","complete"].includes(state.ready) ? state.ready : null,
      tag: ["A","BODY","SECTION","INPUT","SELECT"].includes(state.tag) ? state.tag : null,
      id: ["snapshot","q","batch","main-content"].includes(state.id) ? state.id : null,
      focused: !!state.focused, revision_one: !!state.revision_one, snapshot: !!state.snapshot,
      packet: !!state.packet, error_page: !!state.error_page,
    };
    if (event === "failure") report.failure_snapshot = snapshot;
    add(event, snapshot);
  }
  function cdp({method, params: p = {}}) {
    // The IDs below are Chromium protocol identifiers, not header or body data.
    const ids = {frame: p.frameId, loader: p.loaderId, request: p.requestId};
    if (method === "Page.frameNavigated") {
      add(method, {frame: p.frame.id, loader: p.frame.loaderId, top: !p.frame.parentId, url: safeUrl(p.frame.url, origin)});
    } else if (method === "Page.navigatedWithinDocument") {
      add(method, {...ids, url: safeUrl(p.url, origin)});
    } else if (method === "Page.loadEventFired") {
      add(method);
    } else if (p.type === "Document" && method === "Network.requestWillBeSent") {
      add(method, {...ids, url: safeUrl(p.request.url, origin), redirect_status: p.redirectResponse?.status});
    } else if (p.type === "Document" && method === "Network.responseReceived") {
      add(method, {...ids, url: safeUrl(p.response.url, origin), status: p.response.status});
    } else if (p.type === "Document" && method === "Network.loadingFailed") {
      add(method, {...ids, canceled: !!p.canceled});
    }
  }
  return {report, add, dom, cdp(message) {
    try { cdp(message); } catch { report.capture_errors++; }
  }};
}
