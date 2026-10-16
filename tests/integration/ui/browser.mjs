// Dependency-free, opt-in CDP acceptance for A1 assets + interactive template + live API.
// The temporary loopback overlay never replaces the existing Django site or its mounts.
// This exercises no SSR template rendering; run test_templates.py separately for SSR.
import assert from "node:assert/strict";
import { createServer } from "node:http";
import { spawn } from "node:child_process";
import { readFile, writeFile, mkdir, mkdtemp, rm } from "node:fs/promises";
import { fileURLToPath } from "node:url";
import path from "node:path";
const root = fileURLToPath(new URL("../../../", import.meta.url));
const artifacts = path.join(root, "docs/dev/a1");
const upstream = process.argv[2] ?? "http://127.0.0.1:8000";
const executable = process.argv[3] ?? "C:/Program Files/Google/Chrome/Application/chrome.exe";
assert.ok(["127.0.0.1", "localhost"].includes(new URL(upstream).hostname));
await mkdir(artifacts, { recursive: true });
const report = { timestamp: new Date().toISOString(), scope: "A1 interactive template and assets on a temporary loopback overlay, using existing live Django API. No site/Docker/database changes. SSR rendering is outside this browser run.", result: "NOT_RUN", tests: [], completed_checks: 0 };
const inventory = await fetch(upstream + "/api/v1/fiqh/books").then(r => r.json());
assert.equal(inventory.items.length, 1); const edition = inventory.items[0];
assert.equal(edition.work.source_book_id, "622"); assert.equal(edition.heading_count, 11397);
const template = await readFile(path.join(root, "templates/reference/interactive.html"), "utf8");
const base = await readFile(path.join(root, "templates/reference/base.html"), "utf8");
const notice = base.match(/<p class="scope-note">[\s\S]*?<\/p>/)[0];
function html(id = "") {
  const headingPath = id ? "/fiqh/nodes/" + id : "/fiqh";
  const interactive = template.replace(/{{ edition.id }}/g, String(edition.id))
    .replace(/{% if node %}{{ node.id }}{% endif %}/g, id)
    .replace(/{% if node %}{% url 'heading' node.id %}{% else %}{% url 'catalog' %}{% endif %}/g, headingPath)
    .replace(/{% url 'catalog' %}/g, "/fiqh");
  assert.ok(!interactive.includes("{%") && !interactive.includes("{{"));
  return '<!doctype html><html lang="ar" dir="rtl"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>فهرس المرجع</title><link rel="stylesheet" href="/assets/reference/style.css"><link rel="stylesheet" href="/assets/reference/catalog.css"></head><body><a class="skip-link" href="#catalog-content">انتقل إلى الفهرس</a>' + notice + '<p id="request-status" role="status"></p><div id="server-catalog"><main id="catalog-content">جارٍ فتح الفهرس…</main></div>' + interactive + '<script type="module" src="/assets/reference/catalog.js"></script></body></html>';
}
const allowed = new Set(["style.css", "catalog.css", "catalog.js", "django-api.mjs"]);
const server = createServer(async (request, response) => {
  try {
    if (request.method !== "GET") { response.writeHead(405); response.end(); return; }
    const url = new URL(request.url, "http://localhost");
    if (url.pathname.startsWith("/api/v1/fiqh/")) {
      const result = await fetch(upstream + url.pathname + url.search, { method: "GET", redirect: "error", signal: AbortSignal.timeout(10000) });
      response.writeHead(result.status, { "Content-Type": "application/json", "Cache-Control": "no-store" }); response.end(await result.text()); return;
    }
    if (url.pathname.startsWith("/assets/reference/")) { const name = url.pathname.split("/").at(-1); if (!allowed.has(name)) { response.writeHead(404); response.end(); return; }
      response.writeHead(200, { "Content-Type": name.endsWith("css") ? "text/css" : "text/javascript" }); response.end(await readFile(path.join(root, "apps/reference/static/reference", name))); return; }
    const match = url.pathname.match(/^\/fiqh(?:\/nodes\/([0-9]+))?$/);
    if (match) { response.writeHead(200, { "Content-Type": "text/html; charset=utf-8", "Content-Security-Policy": "default-src 'self'; script-src 'self'; style-src 'self'; connect-src 'self'; object-src 'none'; base-uri 'none'" }); response.end(html(match[1])); return; }
    response.writeHead(404); response.end();
  } catch (error) { response.writeHead(500); response.end("Overlay unavailable"); }
});
await new Promise(resolve => server.listen(0, "127.0.0.1", resolve));
const origin = "http://127.0.0.1:" + server.address().port;
const profile = await mkdtemp(path.join(artifacts, ".browser-profile-"));
let browser, socket, serial = 0, stderr = ""; const pending = new Map(), exceptions = [], requests = [];
const pause = ms => new Promise(resolve => setTimeout(resolve, ms));
async function until(check, label, timeout = 10000) { const deadline = Date.now() + timeout; while (Date.now() < deadline) { if (await check()) return; await pause(40); } throw Error("Timed out: " + label); }
function send(method, params = {}) { return new Promise((resolve, reject) => { const id = ++serial; const timer = setTimeout(() => { pending.delete(id); reject(Error("CDP timeout: " + method)); }, 8000); pending.set(id, { resolve, reject, timer }); socket.send(JSON.stringify({ id, method, params })); }); }
async function evaluate(expression) { const value = await send("Runtime.evaluate", { expression, awaitPromise: true, returnByValue: true }); if (value.exceptionDetails) throw Error(value.exceptionDetails.exception?.description ?? value.exceptionDetails.text); return value.result.value; }
const waitUI = expression => until(() => evaluate(expression), expression);
async function key(key) { const codes = { ArrowLeft: 37, ArrowRight: 39, ArrowDown: 40, ArrowUp: 38, Enter: 13, " ": 32, Home: 36, End: 35 }; await send("Input.dispatchKeyEvent", { type: "keyDown", key, windowsVirtualKeyCode: codes[key] }); await send("Input.dispatchKeyEvent", { type: "keyUp", key, windowsVirtualKeyCode: codes[key] }); }
async function check(name, run) { await run(); report.tests.push({ name, result: "PASS" }); report.completed_checks++; console.log("PASS " + name); }
async function screenshot(name) { const result = await send("Page.captureScreenshot", { format: "png", captureBeyondViewport: true }); await writeFile(path.join(artifacts, name), Buffer.from(result.data, "base64")); }
try {
  browser = spawn(executable, ["--headless=new", "--disable-gpu", "--no-first-run", "--no-default-browser-check", "--disable-background-networking", "--disable-component-update", "--disable-sync", "--remote-debugging-address=127.0.0.1", "--remote-debugging-port=0", "--user-data-dir=" + profile, "about:blank"], { windowsHide: true, stdio: ["ignore", "ignore", "pipe"] });
  browser.on("error", error => { stderr += error.message; }); browser.stderr.on("data", bytes => { stderr += bytes; });
  let port; await until(async () => { try { port = Number((await readFile(path.join(profile, "DevToolsActivePort"), "utf8")).split("\n")[0]); return Boolean(port); } catch { if (browser.exitCode !== null) throw Error("Browser exited before DevTools"); return false; } }, "DevTools port");
  const tabs = await fetch("http://127.0.0.1:" + port + "/json/list").then(r => r.json());
  socket = new WebSocket(tabs.find(tab => tab.type === "page").webSocketDebuggerUrl);
  await new Promise((resolve, reject) => { socket.addEventListener("open", resolve, { once: true }); socket.addEventListener("error", reject, { once: true }); });
  socket.addEventListener("message", event => { const message = JSON.parse(event.data); if (message.id) { const request = pending.get(message.id); if (!request) return; clearTimeout(request.timer); pending.delete(message.id); if (message.error) request.reject(Error(message.error.message)); else request.resolve(message.result); } else if (message.method === "Runtime.exceptionThrown") exceptions.push(message.params); else if (message.method === "Network.requestWillBeSent") requests.push(message.params.request); });
  report.browser = await send("Browser.getVersion"); await send("Page.enable"); await send("Runtime.enable"); await send("Network.enable"); await send("Accessibility.enable");
  await send("Emulation.setDeviceMetricsOverride", { width: 1280, height: 900, deviceScaleFactor: 1, mobile: false });
  await send("Page.navigate", { url: origin + "/fiqh" }); await waitUI("!document.getElementById('interactive-catalog').hidden && document.getElementById('tree-region').getAttribute('aria-busy')==='false'");
  await check("real Arabic RTL roots, nested tree, citation and public metadata removal", async () => {
    assert.equal(await evaluate("document.documentElement.dir"), "rtl"); assert.equal(await evaluate("document.querySelectorAll('#books a').length"), 30); assert.equal(await evaluate("document.querySelectorAll('#introductions a').length"), 2);
    assert.equal(await evaluate("document.querySelectorAll('[role=treeitem][tabindex=\"0\"]').length"), 1); assert.ok(await evaluate("document.querySelectorAll('[role=treeitem]').length") > 1);
    assert.equal(await evaluate("document.querySelectorAll('select[name=edition]').length"), 0); assert.doesNotMatch(await evaluate("document.body.innerText"), /معرّف|sha256|GATES_HOLD/); assert.match(await evaluate("document.getElementById('reference-content').innerText"), /وزارة العدل.*الجزء/s);
  });
  await check("actual RTL keyboard collapse/expand, child/parent, Home/End and activation", async () => {
    await evaluate("document.querySelector('[role=treeitem]').focus()"); await key("ArrowRight"); assert.equal(await evaluate("document.querySelectorAll('[role=treeitem]').length"), 1);
    await key("ArrowLeft"); await waitUI("document.getElementById('tree-region').getAttribute('aria-busy')==='false' && document.querySelectorAll('[role=treeitem]').length>1"); await key("ArrowLeft"); assert.equal(await evaluate("document.activeElement.getAttribute('aria-level')"), "2"); await key("ArrowRight"); assert.equal(await evaluate("document.activeElement.getAttribute('aria-level')"), "1");
    await key("End"); assert.equal(await evaluate("document.activeElement=== [...document.querySelectorAll('[role=treeitem]')].at(-1)"), true); await key("Home"); await key("Enter"); assert.equal(await evaluate("document.querySelectorAll('[role=treeitem]').length"), 1); await key(" "); await waitUI("document.querySelectorAll('[role=treeitem]').length>1");
    const ax = await send("Accessibility.getFullAXTree"); assert.ok(ax.nodes.some(node => !node.ignored && node.role?.value === "treeitem"));
  });
  await check("real search reveal beyond first page, breadcrumb pathway and back/forward", async () => {
    await evaluate("document.getElementById('search-query').value='النوع الثاني: تفويض المهر'; document.getElementById('search-mode').value='exact'; document.getElementById('search-form').requestSubmit()"); await waitUI("document.querySelector('#search-results a')!==null");
    await evaluate("document.querySelector('#search-results a').click()"); await waitUI("location.pathname.endsWith('/8668') && document.getElementById('tree-region').getAttribute('aria-busy')==='false'");
    assert.equal(await evaluate("document.activeElement.dataset.id"), "8668"); assert.equal(await evaluate("document.querySelectorAll('#breadcrumbs li').length"), 6); assert.ok(await evaluate("document.querySelectorAll('[role=treeitem]').length") <= 81);
    await evaluate("document.querySelector('#introductions a').click()"); await waitUI("location.pathname.endsWith('/1') && document.getElementById('tree-region').getAttribute('aria-busy')==='false'"); await evaluate("history.back()"); await waitUI("location.pathname.endsWith('/8668') && document.querySelector('[data-id=\"8668\"]')!==null"); await evaluate("history.forward()"); await waitUI("location.pathname.endsWith('/1')");
  });
  await check("reloadable direct deep link, mobile widths and no horizontal overflow", async () => {
    await send("Page.navigate", { url: origin + "/fiqh/nodes/8668?edition=1" }); await waitUI("!document.getElementById('interactive-catalog').hidden"); assert.equal(await evaluate("document.querySelector('[data-id=\"8668\"]').getAttribute('aria-level')"), "5");
    await screenshot("browser-desktop.png"); for (const width of [390, 320]) { await send("Emulation.setDeviceMetricsOverride", { width, height: 844, deviceScaleFactor: 1, mobile: true }); assert.equal(await evaluate("document.documentElement.scrollWidth<=innerWidth"), true); }
    await screenshot("browser-mobile.png"); assert.equal(exceptions.length, 0); assert.ok(requests.filter(request => request.url.startsWith("http")).every(request => request.method === "GET" && new URL(request.url).origin === origin));
  });
  report.result = "PASS";
} catch (error) { report.result = report.completed_checks ? "FAIL" : "NOT_RUN"; report.blocker = error.message; report.browser_stderr = stderr.slice(-1500); process.exitCode = report.completed_checks ? 1 : 2; }
finally {
  socket?.close(); for (const request of pending.values()) { clearTimeout(request.timer); request.reject(Error("Browser closed")); } pending.clear();
  if (browser && browser.exitCode === null) { browser.kill(); await Promise.race([new Promise(resolve => browser.once("exit", resolve)), pause(3000)]); }
  await new Promise(resolve => server.close(resolve));
  const resolved = path.resolve(profile); assert.equal(path.dirname(resolved), path.resolve(artifacts)); assert.ok(path.basename(resolved).startsWith(".browser-profile-"));
  await rm(resolved, { recursive: true, force: true, maxRetries: 3, retryDelay: 100 }).catch(error => { report.cleanup = error.message; });
  await writeFile(path.join(artifacts, "browser-result.json"), JSON.stringify(report, null, 2) + "\n");
}
console.log(JSON.stringify(report, null, 2));
