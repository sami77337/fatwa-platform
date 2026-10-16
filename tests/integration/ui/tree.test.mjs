import test from "node:test";
import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import { runInNewContext } from "node:vm";
const code = await readFile(new URL("../../../apps/reference/static/reference/tree.js", import.meta.url), "utf8");
function setup() {
  const handlers = new Map(), status = { textContent: "" }, target = { attributes: {}, setAttribute(key, value) { this.attributes[key] = value; } };
  runInNewContext(code, { document: { addEventListener(type, handler) { handlers.set(type, handler); }, getElementById() { return status; } } });
  return { status, target, send(type, extra) { handlers.get(type)({ detail: { target, ...extra } }); } };
}
test("SSR branch loading announces progress and clears busy on success", () => {
  const { send, target, status } = setup(); send("htmx:beforeRequest"); assert.equal(target.attributes["aria-busy"], "true"); assert.match(status.textContent, /جارٍ/);
  send("htmx:afterRequest", { successful: true }); assert.equal(target.attributes["aria-busy"], "false"); assert.match(status.textContent, /تم تحميل/);
});
test("HTTP, connection and timeout errors clear busy and keep heading-link recovery instructions", () => {
  for (const event of ["htmx:responseError", "htmx:sendError", "htmx:timeout"]) {
    const { send, target, status } = setup(); send("htmx:beforeRequest"); send(event); assert.equal(target.attributes["aria-busy"], "false"); assert.match(status.textContent, /رابط عرض العناوين الفرعية/);
    send("htmx:afterRequest", { successful: false }); assert.match(status.textContent, /تعذر/);
  }
});
