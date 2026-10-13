// Dependency-free Chrome DevTools browser acceptance tests.
// A fresh, temporary headless profile is used; no existing browser session is touched.
import assert from "node:assert/strict";
import { spawn } from "node:child_process";
import { mkdtemp, readFile, writeFile, mkdir, rm, access } from "node:fs/promises";
import { fileURLToPath } from "node:url";
import path from "node:path";
import { createPreviewServer } from "../server.mjs";

const kit = fileURLToPath(new URL("../", import.meta.url));
const artifacts = path.join(kit, "artifacts");
await mkdir(artifacts, { recursive: true });
const candidates = [
  process.env.FIQH_BROWSER_PATH,
  "C:/Program Files/Google/Chrome/Application/chrome.exe",
  "C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe",
  "/usr/bin/google-chrome", "/usr/bin/chromium", "/usr/bin/chromium-browser",
].filter(Boolean);
let executable;
for (const candidate of candidates) if (await access(candidate).then(() => true).catch(() => false)) { executable = candidate; break; }
if (!executable) { console.error("NOT_RUN: Chrome/Chromium unavailable. Set FIQH_BROWSER_PATH."); process.exit(2); }
const profile = await mkdtemp(path.join(artifacts, ".chrome-profile-"));
const server = createPreviewServer();
let browser, socket;
let browserError = "";
const pending = new Map();
const exceptions = [];
const requests = [];
let serial = 0;
const results = [];
const pause = ms => new Promise(resolve => setTimeout(resolve, ms));
async function waitFor(check, label, timeout = 8000) {
  const deadline = Date.now() + timeout;
  while (Date.now() < deadline) { if (await check()) return; await pause(30); }
  throw new Error("Timed out: " + label);
}
function send(method, params = {}) {
  const id = ++serial;
  return new Promise((resolve, reject) => {
    const timer = setTimeout(() => { pending.delete(id); reject(new Error("CDP timeout: " + method)); }, 10000);
    pending.set(id, { resolve, reject, timer });
    socket.send(JSON.stringify({ id, method, params }));
  });
}
async function evaluate(expression) {
  const result = await send("Runtime.evaluate", { expression, awaitPromise: true, returnByValue: true });
  if (result.exceptionDetails) throw new Error(result.exceptionDetails.text + ": " + (result.exceptionDetails.exception?.description ?? ""));
  return result.result.value;
}
const count = selector => evaluate("document.querySelectorAll(" + JSON.stringify(selector) + ").length");
const until = (expression, label) => waitFor(() => evaluate(expression), label);
async function click(selector) {
  const point = await evaluate("(() => { const e = document.querySelector(" + JSON.stringify(selector) + "); if (!e) throw Error('Missing click target'); e.scrollIntoView({block:'center'}); const r=e.getBoundingClientRect(); return {x:r.x+r.width/2,y:r.y+r.height/2}; })()");
  await send("Input.dispatchMouseEvent", { type: "mousePressed", ...point, button: "left", clickCount: 1 });
  await send("Input.dispatchMouseEvent", { type: "mouseReleased", ...point, button: "left", clickCount: 1 });
}
async function key(key) {
  const mapping = { Enter: 13, " ": 32, ArrowDown: 40, ArrowUp: 38, ArrowLeft: 37, ArrowRight: 39, Home: 36, End: 35, Tab: 9 };
  await send("Input.dispatchKeyEvent", { type: "keyDown", key, windowsVirtualKeyCode: mapping[key] });
  await send("Input.dispatchKeyEvent", { type: "keyUp", key, windowsVirtualKeyCode: mapping[key] });
}
async function search(text) {
  await evaluate("document.getElementById('query').value=''; document.getElementById('query').focus()");
  await send("Input.insertText", { text });
  await key("Enter");
  await until("document.getElementById('search-results').getAttribute('aria-busy')==='false'", "search completion");
}
async function check(name, work) {
  const start = Date.now();
  await work();
  const result = { name, result: "PASS", duration_ms: Date.now() - start };
  results.push(result);
  console.log("PASS " + name);
}
async function screenshot(filename) {
  const image = await send("Page.captureScreenshot", { format: "png", captureBeyondViewport: true });
  await writeFile(path.join(artifacts, filename), Buffer.from(image.data, "base64"));
}
let failed;
let closing = false;
try {
  await new Promise(resolve => server.listen(0, "127.0.0.1", resolve));
  const origin = "http://127.0.0.1:" + server.address().port;
  browser = spawn(executable, [
    "--headless=new", "--disable-gpu", "--in-process-gpu", "--no-first-run", "--no-default-browser-check",
    "--disable-background-networking", "--disable-component-update", "--disable-sync",
    "--remote-debugging-address=127.0.0.1", "--remote-debugging-port=0",
    "--user-data-dir=" + profile, "about:blank",
  ], { windowsHide: true, stdio: ["ignore", "ignore", "pipe"] });
  browser.on("error", error => { browserError += error.message; });
  browser.stderr.on("data", chunk => { browserError += chunk.toString(); });
  let debugPort;
  await waitFor(async () => {
    try { debugPort = Number((await readFile(path.join(profile, "DevToolsActivePort"), "utf8")).split("\n")[0]); return !!debugPort; }
    catch { if (browser.exitCode !== null) throw new Error("Chrome exited: " + browserError.slice(-1000)); return false; }
  }, "Chrome debugging port");
  const tabs = await fetch("http://127.0.0.1:" + debugPort + "/json/list").then(r => r.json());
  const tab = tabs.find(t => t.type === "page");
  socket = new WebSocket(tab.webSocketDebuggerUrl);
  await new Promise((resolve, reject) => { socket.addEventListener("open", resolve, { once: true }); socket.addEventListener("error", reject, { once: true }); });
  socket.addEventListener("close", event => { if (!closing) console.error("CDP closed: " + event.code + " " + event.reason); for (const request of pending.values()) { clearTimeout(request.timer); request.reject(new Error("CDP closed: " + event.code)); } pending.clear(); });
  socket.addEventListener("message", event => {
    const message = JSON.parse(event.data);
    if (message.id) {
      const request = pending.get(message.id);
      if (!request) return;
      clearTimeout(request.timer); pending.delete(message.id);
      if (message.error) request.reject(new Error(message.error.message));
      else request.resolve(message.result);
    } else if (message.method === "Runtime.exceptionThrown") exceptions.push(message.params.exceptionDetails);
    else if (message.method === "Network.requestWillBeSent") requests.push(message.params.request);
  });
  console.log("DevTools browser: " + JSON.stringify(await send("Browser.getVersion")));
  await send("Page.enable");
  await send("Runtime.enable");
  await send("Network.enable");
  await send("Accessibility.enable");
  await send("Emulation.setDeviceMetricsOverride", { width: 1280, height: 900, deviceScaleFactor: 1, mobile: false });
  await send("Page.navigate", { url: origin + "/" });
  await until("document.querySelectorAll('#books button').length===30 && document.getElementById('tree-region').getAttribute('aria-busy')==='false'", "initial catalog");

  await check("Arabic RTL catalog / 30 books / 2 introductions / lazy initial DOM", async () => {
    assert.equal(await evaluate("document.documentElement.lang"), "ar");
    assert.equal(await evaluate("document.documentElement.dir"), "rtl");
    assert.equal(await count("#books button"), 30);
    assert.equal(await count("#introductions button"), 2);
    assert.equal(await count('[role="treeitem"]'), 21);
    assert.equal(await count('[role="treeitem"][tabindex="0"]'), 1);
    assert.equal(await evaluate("document.querySelector('[role=treeitem]').getAttribute('aria-posinset')"), "1");
    assert.equal(await evaluate("document.querySelector('[role=treeitem]').getAttribute('aria-setsize')"), "1");
    assert.match(await evaluate("document.body.innerText"), /ليست فتاوى/);
  });
  await check("RTL keyboard collapse, expand, enter, space, arrows, home and end", async () => {
    await evaluate("document.querySelector('[role=treeitem]').focus()");
    await key("ArrowRight");
    assert.equal(await count('[role="treeitem"]'), 1);
    await key("ArrowLeft");
    await until("document.querySelectorAll('[role=treeitem]').length===21", "keyboard expansion");
    assert.equal(await evaluate("document.activeElement.getAttribute('aria-expanded')"), "true");
    await key("ArrowDown");
    assert.equal(await evaluate("document.activeElement.getAttribute('aria-level')"), "2");
    await key("End");
    assert.equal(await evaluate("document.activeElement.getAttribute('aria-posinset')"), "20");
    await key("Home");
    assert.equal(await evaluate("document.activeElement.getAttribute('aria-level')"), "1");
    await key("Enter");
    assert.equal(await count('[role="treeitem"]'), 1);
    await key(" ");
    await until("document.querySelectorAll('[role=treeitem]').length===21", "space expansion");
    await key("ArrowDown");
    await key("ArrowUp");
    assert.equal(await evaluate("document.activeElement.getAttribute('aria-level')"), "1");
  });
  await check("pointer paging replaces sibling DOM and preserves focus / ARIA positions", async () => {
    await click("#tree-pagination button");
    await until("document.querySelectorAll('[role=treeitem]').length===5", "second sibling page");
    assert.equal(await evaluate("document.querySelector('[role=group] [role=treeitem]').getAttribute('aria-posinset')"), "21");
    assert.equal(await evaluate("document.querySelector('[role=group] [role=treeitem]').getAttribute('aria-setsize')"), "24");
    assert.equal(await evaluate("document.activeElement.getAttribute('aria-level')"), "1");
    await click("#tree-pagination button");
    await until("document.querySelectorAll('[role=treeitem]').length===21", "previous sibling page");
  });
  await check("one expanded sibling path / depth 5 / tree DOM budget", async () => {
    for (let depth = 2; depth <= 4; depth++) {
      await click('[role="treeitem"][aria-level="' + depth + '"]');
      await until("document.getElementById('tree-region').getAttribute('aria-busy')==='false'", "depth expansion");
    }
    assert.ok(await count('[role="treeitem"][aria-level="5"]') > 0);
    assert.ok(await count('[role="treeitem"]') <= 81);
    assert.equal(await count('[role="treeitem"][tabindex="0"]'), 1);
    await click('[role="treeitem"][aria-level="2"][aria-expanded="false"]');
    await until("document.getElementById('tree-region').getAttribute('aria-busy')==='false'", "sibling expansion");
    assert.equal(await count('[role="treeitem"][aria-level="2"][aria-expanded="true"]'), 1);
    assert.equal(await count('[role="treeitem"][aria-level="5"]'), 0);
    const ax = await send("Accessibility.getFullAXTree");
    const tree = ax.nodes.find(n => !n.ignored && n.role?.value === "tree");
    assert.ok(tree);
    assert.equal(tree.name.value, "شجرة عناوين الكتاب");
    assert.ok(ax.nodes.some(n => !n.ignored && n.role?.value === "treeitem"));
  });
  await check("invalid query has an Arabic error and ARIA-invalid state", async () => {
    await search("س");
    assert.equal(await evaluate("document.getElementById('query').getAttribute('aria-invalid')"), "true");
    assert.match(await evaluate("document.getElementById('error').innerText"), /أدخل من حرفين/);
    await click("#clear-search");
    assert.equal(await evaluate("document.getElementById('query').hasAttribute('aria-invalid')"), false);
  });
  await check("source-badged Arabic search / bounded pages / printed part and page", async () => {
    await search("كِتَاب");
    assert.equal(await count("#search-results .result-list li"), 20);
    assert.match(await evaluate("document.getElementById('search-results').innerText"), /الصفحة المطبوعة/);
    assert.match(await evaluate("document.getElementById('search-results').innerText"), /ليس فتوى/);
    assert.match(await evaluate("document.getElementById('search-results').innerText"), /مصطنعة/);
    await click("#search-results .pagination button");
    await until("document.getElementById('search-results').getAttribute('aria-busy')==='false'", "next search page");
    assert.equal(await count("#search-results .result-list li"), 20);
    assert.equal(await evaluate("document.activeElement.tagName"), "H3");
    assert.equal(await count("#search-results .pagination button"), 2);
  });
  await check("search-result reveal beyond first sibling page / exact breadcrumb and citation", async () => {
    await evaluate("document.getElementById('search-scope').value = document.querySelector('#books button').dataset.id");
    await search("باب تجريبي ٢٤");
    assert.equal(await count("#search-results .result-list li"), 1);
    await click("#search-results .result-list button");
    await until("document.getElementById('tree-region').getAttribute('aria-busy')==='false'", "reveal result");
    assert.equal(await evaluate("document.activeElement.getAttribute('aria-posinset')"), "24");
    assert.equal(await count("#breadcrumbs li"), 2);
    assert.equal(await count('[role="treeitem"]'), 5);
    assert.match(await evaluate("document.getElementById('reference-content').innerText"), /الجزء/);
    await click("#breadcrumbs button");
    assert.equal(await evaluate("document.activeElement.getAttribute('aria-level')"), "1");
  });
  await check("empty search and introduction leaf / clear restores input focus", async () => {
    await search("لايوجدعنوانمطابقلهذهالعبارة");
    assert.equal(await count("#search-results .result-list li"), 0);
    assert.match(await evaluate("document.getElementById('search-results').innerText"), /لم نعثر/);
    await click("#clear-search");
    assert.equal(await evaluate("document.activeElement.id"), "query");
    assert.equal(await evaluate("document.getElementById('search-results').innerText"), "");
    await click("#introductions button");
    assert.equal(await count('[role="treeitem"]'), 1);
    assert.equal(await count('[role="treeitem"][aria-expanded]'), 0);
  });
  await check("loading, failed child request and explicit retry retain usable navigation", async () => {
    await evaluate("import('./app.js').then(m => { window.testChildren = m.mockAdapter.children; m.mockAdapter.children = () => Promise.reject(new Error('synthetic failure')); })");
    await click("#books button");
    await until("document.querySelector('#error button') !== null", "child error");
    assert.equal(await evaluate("document.getElementById('tree-region').getAttribute('aria-busy')"), "false");
    assert.equal(await count('[role="treeitem"]'), 1);
    await evaluate("import('./app.js').then(m => m.mockAdapter.children = window.testChildren)");
    await click("#error button");
    assert.equal(await evaluate("document.getElementById('tree-region').getAttribute('aria-busy')"), "true");
    await until("document.querySelectorAll('[role=treeitem]').length===21 && document.getElementById('tree-region').getAttribute('aria-busy')==='false'", "retry completion");
    assert.equal(await count("#error button"), 0);
  });
  await check("rapid root switches ignore a stale response even when transport ignores abort", async () => {
    await evaluate("import('./app.js').then(m => { m.mockAdapter.children = async (id, options) => { const result = await window.testChildren(id, {...options,signal:undefined}); await new Promise(r => setTimeout(r, 200)); return result; }; })");
    await click("#books button");
    await click("#introductions button");
    await pause(400);
    assert.equal(await count('[role="treeitem"]'), 1);
    assert.match(await evaluate("document.querySelector('[role=treeitem]').getAttribute('aria-label')"), /مقدمة/);
    await evaluate("import('./app.js').then(m => m.mockAdapter.children = window.testChildren)");
  });
  await check("stale searches and clear cancellation cannot replace newer results", async () => {
    await evaluate("import('./app.js').then(m => { window.testSearch = m.mockAdapter.search; m.mockAdapter.search = async (q,options) => { const result = await window.testSearch(q,{...options,signal:undefined}); await new Promise(r => setTimeout(r,q==='كتاب'?300:10)); return result; }; })");
    await evaluate("document.getElementById('search-scope').value=''; document.getElementById('query').value='كتاب'; document.getElementById('search-form').requestSubmit(); document.getElementById('query').value='لامطابقةمطلقا'; document.getElementById('search-form').requestSubmit()");
    await pause(450);
    assert.match(await evaluate("document.getElementById('search-results').innerText"), /لم نعثر/);
    await evaluate("document.getElementById('query').value='كتاب'; document.getElementById('search-form').requestSubmit()");
    await click("#clear-search");
    await pause(450);
    assert.equal(await evaluate("document.getElementById('search-results').innerText"), "");
    await evaluate("import('./app.js').then(m => m.mockAdapter.search = window.testSearch)");
  });
  await check("search failure / retry and literal HTML headings cannot execute markup", async () => {
    await evaluate("import('./app.js').then(m => m.mockAdapter.search = () => Promise.reject(new Error('synthetic failure')))");
    await search("كتاب");
    assert.equal(await count("#error button"), 1);
    await evaluate("import('./app.js').then(m => m.mockAdapter.search = window.testSearch)");
    await click("#error button");
    await until("document.getElementById('search-results').getAttribute('aria-busy')==='false'", "search retry");
    assert.equal(await count("#search-results .result-list li"), 20);
    await evaluate("import('./app.js').then(m => { m.mockAdapter.search = async () => { const page=await window.testSearch('كتاب'); page.items[0].title='<img src=x onerror=alert(1)>'; return page; }; })");
    await search("كتاب");
    assert.match(await evaluate("document.querySelector('#search-results .result-list button').textContent"), /<img/);
    assert.equal(await count("#search-results img"), 0);
    await evaluate("import('./app.js').then(m => m.mockAdapter.search = window.testSearch)");
  });
  await check("desktop visual evidence / named focus targets / no page errors", async () => {
    await click("#clear-search");
    await click("#books button");
    await until("document.getElementById('tree-region').getAttribute('aria-busy')==='false'", "desktop ready");
    assert.equal(await evaluate("document.documentElement.scrollWidth <= innerWidth"), true);
    assert.equal(await evaluate("[...document.querySelectorAll('button,input,select,[role=treeitem]')].every(e => e.getAttribute('aria-label') || e.textContent.trim() || e.labels?.length)"), true);
    assert.equal(exceptions.length, 0);
    await screenshot("desktop.png");
  });
  await check("390px mobile layout / touch-sized controls / keyboard and DOM bound", async () => {
    await send("Emulation.setDeviceMetricsOverride", { width: 390, height: 844, deviceScaleFactor: 1, mobile: true });
    await send("Emulation.setTouchEmulationEnabled", { enabled: true });
    assert.equal(await evaluate("document.documentElement.scrollWidth <= innerWidth"), true);
    assert.equal(await evaluate("[...document.querySelectorAll('button,input,select,.tree-row')].every(e => e.getBoundingClientRect().height>=43)"), true);
    await evaluate("document.querySelector('[role=treeitem]').focus()");
    await key("ArrowRight");
    await key("ArrowLeft");
    await until("document.querySelectorAll('[role=treeitem]').length===21", "mobile expansion");
    assert.equal(await count('[role="treeitem"][tabindex="0"]'), 1);
    assert.ok(await count('[role="treeitem"]') <= 81);
    await evaluate("scrollTo(0,0)");
    await screenshot("mobile.png");
  });
  await check("narrow 320px mobile viewport has no horizontal overflow", async () => {
    await send("Emulation.setDeviceMetricsOverride", { width: 320, height: 720, deviceScaleFactor: 1, mobile: true });
    assert.equal(await evaluate("document.documentElement.scrollWidth <= innerWidth"), true);
  });
  await check("kit issues no external requests or mutating requests", async () => {
    assert.ok(requests.filter(r => r.url.startsWith("http")).every(r => new URL(r.url).origin === origin));
    assert.ok(requests.every(r => r.method === "GET"));
    assert.equal(exceptions.length, 0);
  });
  const version = await send("Browser.getVersion");
  console.log("Browser: " + version.product);
  await writeFile(path.join(artifacts, "browser-results.json"), JSON.stringify({ browser: version.product, fixture_id: "s2-synthetic-11397-v1", tests: results, page_exceptions: exceptions.length }, null, 2) + "\n");
  console.log(results.length + " browser checks passed.");
} catch (error) {
  failed = error;
  console.error("FAIL " + error.stack);
  console.error(browserError.slice(-3000));
  if (socket?.readyState === WebSocket.OPEN) await screenshot("failure.png").catch(() => {});
  await writeFile(path.join(artifacts, "browser-results.json"), JSON.stringify({ fixture_id: "s2-synthetic-11397-v1", status: results.length ? "FAIL" : "BLOCKED_BEFORE_UI_INITIALIZATION", completed_checks: results.length, tests: results, failure: String(error) }, null, 2) + "\n");
} finally {
  closing = true;
  socket?.close();
  for (const request of pending.values()) { clearTimeout(request.timer); request.reject(new Error("Browser test ended")); }
  pending.clear();
  if (failed) console.error("Browser exit: " + browser?.exitCode);
  if (browser && browser.exitCode === null) {
    browser.kill();
    await Promise.race([new Promise(resolve => browser.once("exit", resolve)), pause(4000)]);
  }
  await new Promise(resolve => server.close(resolve));
  // Resolve and check the exact ephemeral profile before recursive removal.
  const resolved = path.resolve(profile);
  if (path.dirname(resolved) !== path.resolve(artifacts) || !path.basename(resolved).startsWith(".chrome-profile-")) throw new Error("Unsafe profile cleanup path");
  await rm(resolved, { recursive: true, force: true, maxRetries: 5, retryDelay: 200 });
}
if (failed) process.exitCode = 1;
