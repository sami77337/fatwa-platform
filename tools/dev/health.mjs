// Fixed loopback HTTP transport: no proxy, credentials, redirects, or mutations.
import http from "node:http";

export const origin = "http://127.0.0.1:8000";
export const sourcePins = Object.freeze({
  archive: "82a797806430635350decdde27d07fe41fb1278838c8173dc4080f9d109957ce",
  input: "37544f6122ef72fb6bd908556ffb41821b235be28bcbd1413752042dbac01d14",
});
const kind = "SOURCE_BOOK_TOC_NOT_FATWAS";

export function readLocal(route, { timeoutMs = 4000, maxBytes = 512 * 1024, requestImpl = http.request } = {}) {
  if (typeof route !== "string" || !/^\/(?!\/)/.test(route) || /[\\\r\n#]/.test(route) ||
      new URL(route, origin).origin !== origin) throw new Error("Invalid local route");
  return new Promise((resolve, reject) => {
    let settled = false;
    const finish = (error, value) => {
      if (settled) return;
      settled = true;
      clearTimeout(timer);
      if (error) reject(error); else resolve(value);
    };
    const request = requestImpl({
      hostname: "127.0.0.1", port: 8000, path: route, method: "GET",
      headers: { Accept: "application/json,text/html", "Cache-Control": "no-store" },
      agent: false,
    }, response => {
      const parts = [];
      let size = 0;
      response.on("data", chunk => {
        size += chunk.length;
        if (size > maxBytes) {
          finish(new Error("HTTP_RESPONSE_TOO_LARGE"));
          response.destroy();
          request.destroy();
        } else parts.push(chunk);
      });
      response.on("error", () => finish(new Error("HTTP_RESPONSE_INTERRUPTED")));
      response.on("end", () => finish(null, {
        status: response.statusCode,
        type: response.headers["content-type"] ?? "",
        body: Buffer.concat(parts).toString("utf8"),
        bytes: size,
      }));
    });
    const timer = setTimeout(() => {
      finish(new Error("HTTP_TIMEOUT"));
      request.destroy();
    }, timeoutMs);
    request.on("error", () => finish(new Error("HTTP_UNAVAILABLE")));
    request.end();
  });
}

function requireHealth(condition, message) {
  if (!condition) throw new Error(message);
}
function id(value) {
  requireHealth(Number.isSafeInteger(value) && value > 0, "INVALID_PUBLIC_ID");
  return value;
}
function page(payload, limit) {
  requireHealth(Array.isArray(payload.items) && payload.items.length <= limit, "UNBOUNDED_RESPONSE");
  requireHealth(Number.isSafeInteger(payload.total) && payload.total >= payload.items.length, "INVALID_TOTAL");
  requireHealth(payload.limit === limit && payload.offset === 0, "INVALID_PAGING");
  return payload;
}

export async function healthcheck({ transport = readLocal } = {}) {
  const checks = [];
  const check = async (label, route, validate, expected = 200) => {
    const started = Date.now();
    let observedStatus;
    try {
      const response = await transport(route);
      observedStatus = response.status;
      requireHealth(response.status === expected, "UNEXPECTED_HTTP_STATUS");
      const value = validate(response);
      checks.push({ check: label, result: "PASS", status: response.status, elapsed_ms: Date.now() - started });
      return value;
    } catch (error) {
      // Fixed messages only. Never retain body text, request titles, or transport errors.
      const allowed = /^(HTTP_(TIMEOUT|UNAVAILABLE|RESPONSE_TOO_LARGE|RESPONSE_INTERRUPTED)|UNEXPECTED_HTTP_STATUS|INVALID_[A-Z_]+|UNBOUNDED_RESPONSE|WRONG_[A-Z_]+)$/;
      checks.push({ check: label, result: "FAIL", reason: allowed.test(error.message) ? error.message : "INVALID_RESPONSE",
        ...(Number.isInteger(observedStatus) && observedStatus >= 100 && observedStatus <= 599 ? { status: observedStatus } : {}),
        elapsed_ms: Date.now() - started });
      return undefined;
    }
  };
  const json = response => {
    requireHealth(response.type.includes("application/json"), "INVALID_CONTENT_TYPE");
    const payload = JSON.parse(response.body);
    requireHealth(payload.kind === kind, "WRONG_CATALOG_KIND");
    return payload;
  };
  const html = response => {
    requireHealth(response.type.includes("text/html"), "INVALID_CONTENT_TYPE");
    requireHealth(/lang=["']ar["']/.test(response.body) && /dir=["']rtl["']/.test(response.body), "INVALID_ARABIC_PAGE");
  };
  await check("homepage", "/", html);
  await check("fiqh", "/fiqh", html);
  await check("fiqh_basic", "/fiqh?basic=1", html);
  await check("liveness", "/healthz", response => {
    const value = json(response);
    requireHealth(value.alive === true && value.read_only === true, "INVALID_LIVENESS");
  });
  await check("readiness", "/readyz", response => {
    requireHealth(json(response).database_reachable === true, "INVALID_READINESS");
  });
  await check("public_status", "/api/v1/status", response => {
    const value = json(response);
    requireHealth(value.read_only === true && value.sensitive_write_routes_enabled === false &&
      value.fatwa_publications_available === false, "INVALID_PUBLIC_BOUNDARIES");
  });
  const books = await check("books", "/api/v1/fiqh/books?limit=100&offset=0", response => page(json(response), 100));
  const edition = books?.items?.find(item => item?.work?.source_namespace === "shamela" && item.work.source_book_id === "622");
  let catalog = { result: "NOT_RUN", basis: "Live API metadata only; archive bytes and all stored rows are not verified." };
  if (books) {
    const counts = edition && {
      headings: Number.isSafeInteger(edition.heading_count) ? edition.heading_count : null,
      roots: Number.isSafeInteger(edition.root_count) ? edition.root_count : null,
      max_depth: Number.isSafeInteger(edition.max_depth) ? edition.max_depth : null,
    };
    const matches = edition && books.total === 1 &&
      edition.source_archive_sha256 === sourcePins.archive && edition.source_input_sha256 === sourcePins.input &&
      counts.headings === 11397 && counts.roots === 32 && counts.max_depth === 5;
    catalog = { ...catalog, result: matches ? "PASS" : "FAIL",
      ...(counts ? { observed_counts: counts } : {}),
      expected_counts: { headings: 11397, roots: 32, max_depth: 5 },
      archive_sha256_matches: edition?.source_archive_sha256 === sourcePins.archive,
      input_sha256_matches: edition?.source_input_sha256 === sourcePins.input };
  }
  if (edition && Number.isSafeInteger(edition.id) && edition.id > 0) {
    const selected = id(edition.id);
    const sameEdition = payload => {
      requireHealth(payload.edition?.id === selected &&
        payload.edition?.source_archive_sha256 === sourcePins.archive &&
        payload.edition?.source_input_sha256 === sourcePins.input, "WRONG_EDITION");
      return payload;
    };
    const roots = await check("roots", "/api/v1/fiqh/roots?edition=" + selected + "&limit=100&offset=0", response => {
      const value = sameEdition(page(json(response), 100));
      requireHealth(value.total === 32 && value.items.length === 32 &&
        value.items.every(row => row.parent_id === null && row.depth === 1), "WRONG_ROOTS");
      return value;
    });
    const sample = roots?.items?.find(row => Number.isSafeInteger(row.id) && row.id > 0 &&
      typeof row.title === "string" && row.title.length > 0 && row.title.length <= 160 && row.children_count > 0);
    if (sample) {
      const sampleId = id(sample.id);
      await check("node", "/api/v1/fiqh/nodes/" + sampleId + "?edition=" + selected, response => {
        const value = sameEdition(json(response));
        requireHealth(value.node?.id === sampleId && value.node.title === sample.title &&
          value.node.parent_id === null && value.ancestors?.length === 1 &&
          value.ancestors[0].id === sampleId, "INVALID_NODE");
      });
      await check("children", "/api/v1/fiqh/nodes/" + sampleId + "/children?edition=" + selected + "&limit=20&offset=0", response => {
        const value = sameEdition(page(json(response), 20));
        requireHealth(value.parent === sampleId && value.total === sample.children_count &&
          value.items.length > 0 && value.items.every(row => row.parent_id === sampleId), "INVALID_CHILDREN");
      });
      for (const mode of ["exact", "literal", "normalized"]) {
        await check("search_" + mode, "/api/v1/fiqh/search?" + new URLSearchParams({
          edition: String(selected), q: sample.title, mode, limit: "100", offset: "0",
        }), response => {
          const value = sameEdition(page(json(response), 100));
          requireHealth(value.mode === mode && value.query === sample.title &&
            value.items.some(row => row.id === sampleId && row.title === sample.title), "INVALID_SEARCH");
        });
      }
    } else {
      checks.push({ check: "node_children_search", result: "NOT_RUN", reason: "No bounded root sample available" });
    }
  } else {
    checks.push({ check: "roots_node_children_search", result: "NOT_RUN", reason: "No valid book-622 edition" });
  }
  await check("invalid_limit_rejected", "/api/v1/fiqh/books?limit=101", response => {
    requireHealth(json(response).error === "invalid_query", "INVALID_ERROR_RESPONSE");
  }, 400);
  return {
    result: checks.every(item => item.result === "PASS") && catalog.result === "PASS" ? "PASS" : "FAIL",
    http_behavior: checks.every(item => item.result === "PASS") ? "PASS" : "FAIL",
    catalog_metadata: catalog,
    source_archive_verification: "NOT_RUN",
    full_source_row_comparison: "NOT_RUN",
    django_postgresql_tests: "NOT_RUN",
    browser_mobile_keyboard: "NOT_RUN",
    method: "GET_ONLY", origin, checks,
  };
}
