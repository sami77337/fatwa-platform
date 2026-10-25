// Actual sandboxed Chrome; only explicitly listed loopback GET/HEAD requests.
import assert from "node:assert/strict";
import {spawn, execFileSync} from "node:child_process";
import {createHash} from "node:crypto";
import {mkdtemp, readFile, writeFile, mkdir, rm} from "node:fs/promises";
import os from "node:os";
import path from "node:path";
import {CDP, loopbackOrigin} from "../wave7/cdp.mjs";
import {dispatchKey} from "../wave7/keyboard.mjs";

const origin = loopbackOrigin(process.argv[2]);
const routes = ["editorial-dashboard", "editorial-search", "editorial-followup", "editorial-export", "workflow-rehearsal", "research-bridge", "permission-lab"];
const allowedRoutes = [...routes, "editorial-queue", "editorial-workbench", "reference-triage"];
const temp = path.resolve(os.tmpdir()), prefix = "fatwa-fast5-browser-";
const profile = await mkdtemp(path.join(temp, prefix));
const executable = process.env.FATWA_FASTBUILD_BROWSER ??
  (process.platform === "win32" ? "C:/Program Files/Google/Chrome/Application/chrome.exe" : "/usr/bin/chromium");
const browser = spawn(executable, ["--headless=new", "--no-first-run", "--no-default-browser-check",
  "--disable-background-networking", "--disable-component-update", "--disable-sync",
  "--remote-debugging-address=127.0.0.1", "--remote-debugging-port=0", "--user-data-dir=" + profile,
  "about:blank"], {windowsHide: true, stdio: "ignore"});
let launchError, socket, cdp, loads = 0;
browser.on("error", error => { launchError = error; });
const errors = [], violations = [], requests = [], failedResponses = [], checks = [];
const networkRequests = new Map();
const pending = new Set();
const pause = ms => new Promise(resolve => setTimeout(resolve, ms));
async function until(check, label = "condition") {
  const deadline = Date.now() + 10000;
  while (Date.now() < deadline) { if (await check()) return; await pause(30); }
  throw Error("FAST5 browser timed out: " + label);
}
const watchdog = setTimeout(() => { socket?.close(); browser.kill(); }, 150000);
try {
  let port;
  await until(async () => {
    if (launchError) throw launchError;
    try { port = Number((await readFile(path.join(profile, "DevToolsActivePort"), "utf8")).split("\n")[0]); return !!port; }
    catch { return false; }
  }, "Chrome DevTools startup");
  const tabs = await fetch(`http://127.0.0.1:${port}/json/list`).then(r => r.json());
  socket = new WebSocket(tabs.find(tab => tab.type === "page").webSocketDebuggerUrl);
  await until(() => socket.readyState === WebSocket.OPEN, "DevTools socket");
  cdp = new CDP(socket, message => {
    if (message.method === "Page.loadEventFired") loads++;
    if (message.method === "Runtime.exceptionThrown") errors.push(message.params.exceptionDetails.text);
    if (message.method === "Runtime.consoleAPICalled" && message.params.type === "error") {
      errors.push("console: " + JSON.stringify(message.params.args));
    }
    if (message.method === "Network.requestWillBeSent") networkRequests.set(message.params.requestId, message.params.request.url);
    if (message.method === "Network.loadingFailed") errors.push({url:networkRequests.get(message.params.requestId), ...message.params});
    if (message.method === "Network.responseReceived" && message.params.response.status >= 400) {
      failedResponses.push({url: message.params.response.url, status: message.params.response.status});
    }
    if (message.method === "Fetch.requestPaused") {
      const {requestId, request} = message.params;
      const url = new URL(request.url);
      const favicon = url.origin === origin && url.pathname === "/favicon.ico" && request.method === "GET";
      const allowed = ["GET", "HEAD"].includes(request.method) && url.origin === origin &&
        (favicon || allowedRoutes.some(route => url.pathname === `/dev/${route}` || url.pathname.startsWith(`/dev/${route}/`)));
      requests.push({method: request.method, path: url.pathname});
      if (!allowed) violations.push(request.url);
      const task = favicon ? cdp.send("Fetch.fulfillRequest", {requestId, responseCode: 204}) :
        cdp.send(allowed ? "Fetch.continueRequest" : "Fetch.failRequest",
          allowed ? {requestId} : {requestId, errorReason: "BlockedByClient"});
      pending.add(task); task.finally(() => pending.delete(task));
    }
  });
  for (const domain of ["Page", "Runtime", "Network"]) await cdp.send(domain + ".enable");
  await cdp.send("Fetch.enable", {patterns: [{urlPattern: "*"}]});
  const evaluate = expression => cdp.evaluate(expression);
  async function loaded(before) {
    await until(() => loads > before, "page load");
    await until(() => evaluate("document.readyState === 'complete'"), "document complete");
  }
  async function navigate(route) {
    const before = loads;
    await cdp.send("Page.navigate", {url: origin + route});
    await loaded(before);
  }
  async function activate(selector) {
    const target = JSON.stringify(selector);
    assert.equal(await evaluate(`document.querySelector(${target}) !== null`), true, selector);
    await evaluate(`document.querySelector(${target}).focus()`);
    assert.equal(await evaluate(`document.activeElement.matches(${target})`), true, selector);
    const before = loads;
    await dispatchKey(cdp, "Enter", 13);
    await loaded(before);
  }
  const navRoutes = ["editorial-dashboard", "workflow-rehearsal", "research-bridge", "permission-lab"];
  for (const width of [1280, 375, 320]) {
    await cdp.send("Emulation.setDeviceMetricsOverride", {width, height:900, deviceScaleFactor:1, mobile:width < 500});
    for (const route of routes) {
      await navigate(`/dev/${route}`);
      assert.equal(await evaluate("document.documentElement.dir"), "rtl");
      assert.equal(await evaluate("document.documentElement.lang"), "ar");
      assert.deepEqual(await evaluate('Array.from(document.querySelectorAll(\'nav[aria-label="أدوات FAST5"] a\'), a=>a.pathname)'), navRoutes.map(name=>`/dev/${name}`));
      assert.equal(await evaluate("document.documentElement.scrollWidth <= innerWidth"), true, `${route} ${width}px`);
      await dispatchKey(cdp, "Tab", 9);
      assert.equal(await evaluate('document.activeElement.matches(\'a[href^="#main"]\')'), true);
      await dispatchKey(cdp, "Enter", 13);
      assert.equal(await evaluate("document.activeElement.tagName"), "MAIN");
    }
    for (const route of [...navRoutes, navRoutes[0]]) {
      await activate(`nav[aria-label="أدوات FAST5"] a[href="/dev/${route}"]`);
      assert.equal(await evaluate("location.pathname"), `/dev/${route}`);
    }
  }
  checks.push("seven pages RTL at 1280/375/320px; native skip links and shared keyboard navigation");
  await activate('nav[aria-label="أدوات FAST5"] a[href="/dev/workflow-rehearsal"]');
  await activate('a[href="/dev/workflow-rehearsal/intake-7"]');
  const question = await evaluate("document.querySelector('#question code').textContent");
  assert.ok(await evaluate("document.body.textContent.includes('REVIEWED_INTERNAL')"));
  assert.ok(await evaluate("document.querySelectorAll('[data-accepted=false]').length > 0"));
  await activate('a[href="/dev/research-bridge/intake-7#reference-1"]');
  assert.equal(await evaluate("location.hash"), "#reference-1");
  assert.ok(await evaluate("!!document.querySelector(location.hash)"));
  assert.ok((await evaluate("Array.from(document.querySelectorAll('pre code'), x=>x.textContent)")).includes(question));
  assert.equal(await evaluate('document.querySelector(\'a[href^="/fiqh/nodes/"]\').getAttribute("href")'), "/fiqh/nodes/2?edition=7001");
  assert.deepEqual(await evaluate("Array.from(document.querySelectorAll('#reference-1 section ol li'), x=>x.textContent)"), ["كِتَابٌ اصطناعي", "بابٌ اصطناعي أول"]);
  await activate('a[href="/dev/reference-triage/intake-7#reference-1"]');
  assert.ok(await evaluate("!!document.querySelector(location.hash)"));
  checks.push("same-case rehearsal to research and triage; exact synthetic hierarchy and edition-scoped href (no live PostgreSQL)");
  await navigate("/dev/research-bridge/batch-synthetic-csv-1");
  assert.ok((await evaluate("Array.from(document.querySelectorAll('pre code'), x=>x.textContent)")).includes("  سُؤَالٌ اصطناعي\r\nبسطرٍ وتشكيل e\u0301  "));
  await navigate("/dev/research-bridge/history");
  assert.equal(await evaluate('document.querySelectorAll(\'a[href^="/fiqh/nodes/"]\').length'), 0);
  checks.push("exact Arabic CRLF and combining character; incomplete evidence has no catalog link");
  await activate('nav[aria-label="أدوات FAST5"] a[href="/dev/permission-lab"]');
  await navigate("/dev/permission-lab?actor=MUFTI&action=synthetic%3A%3Aanswer.create&resource=synthetic%3A%3Aanswer");
  assert.ok(await evaluate("document.querySelector('#decision').textContent.includes('DENY_DEFAULT')"));
  assert.ok(await evaluate("document.querySelector('#decision').textContent.includes('POLICY_PENDING')"));
  await activate('nav[aria-label="أدوات FAST5"] a[href="/dev/editorial-dashboard"]');
  await activate('nav[aria-label="أدوات FAST4"] a[href="/dev/editorial-export"]');
  checks.push("permission remains DENY/POLICY_PENDING; return to FAST4 exports through native navigation");
  await Promise.all([...pending]);
  assert.deepEqual(errors, []); assert.deepEqual(violations, []); assert.deepEqual(failedResponses, []);
  assert.ok(requests.length > 0);
  checks.push("GET/HEAD-only loopback policy; zero runtime, network or HTTP errors");
  const summary = {result: "PASS", sha: execFileSync('git', ['rev-parse', 'HEAD'], {encoding:'utf8'}).trim(),
    dirty: !!execFileSync('git', ['status', '--porcelain'], {encoding:'utf8'}).trim(),
    browser: await cdp.send('Browser.getVersion'), checks, requests: requests.length,
    errors, violations, failedResponses};
  const output = path.resolve(process.env.FATWA_FAST5_REPORT ?? '.local/qa/fast5/browser.json');
  await mkdir(path.dirname(output), {recursive: true});
  await writeFile(output, JSON.stringify(summary, null, 2) + '\n');
  console.log(JSON.stringify({...summary, report:output}));
} finally {
  clearTimeout(watchdog); socket?.close(); cdp?.close();
  const ended = new Promise(resolve => browser.once("exit", resolve));
  if (browser.exitCode === null && !launchError) { browser.kill(); await ended; }
  const target = path.resolve(profile);
  assert.equal(path.dirname(target), temp); assert.ok(path.basename(target).startsWith(prefix));
  await rm(target, {recursive: true, force: true, maxRetries: 5, retryDelay: 100});
}
