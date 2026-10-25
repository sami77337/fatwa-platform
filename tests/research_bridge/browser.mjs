// Browser checks use a labeled synthetic read-only catalog double in test_browser.py.
import assert from "node:assert/strict";
import {spawn} from "node:child_process";
import {mkdtemp, readFile, writeFile, rm} from "node:fs/promises";
import os from "node:os";
import path from "node:path";
import {CDP, loopbackOrigin} from "../acceptance/wave7/cdp.mjs";
import {dispatchKey} from "../acceptance/wave7/keyboard.mjs";

const origin = loopbackOrigin(process.argv[2]);
const temp = path.resolve(os.tmpdir());
const profile = await mkdtemp(path.join(temp, "fatwa-research-bridge-browser-"));
const executable = process.env.FATWA_FASTBUILD_BROWSER ??
  (process.platform === "win32" ? "C:/Program Files/Google/Chrome/Application/chrome.exe" : "/usr/bin/chromium");
const browser = spawn(executable, ["--headless=new", "--no-first-run", "--no-default-browser-check",
  "--disable-background-networking", "--disable-component-update", "--disable-sync",
  "--remote-debugging-address=127.0.0.1", "--remote-debugging-port=0", "--user-data-dir=" + profile,
  "about:blank"], {windowsHide: true, stdio: "ignore"});
let launchError, socket, cdp, loads = 0;
browser.on("error", error => { launchError = error; });
const errors = [], violations = [], requests = [];
const pending = new Set();
const pause = ms => new Promise(resolve => setTimeout(resolve, ms));
async function until(check) {
  const deadline = Date.now() + 10000;
  while (Date.now() < deadline) { if (await check()) return; await pause(30); }
  throw Error("Browser check timed out");
}
const watchdog = setTimeout(() => { socket?.close(); browser.kill(); }, 75000);
try {
  let port;
  await until(async () => {
    if (launchError) throw launchError;
    try { port = Number((await readFile(path.join(profile, "DevToolsActivePort"), "utf8")).split("\n")[0]); return !!port; }
    catch { return false; }
  });
  const tabs = await fetch(`http://127.0.0.1:${port}/json/list`).then(r => r.json());
  socket = new WebSocket(tabs.find(tab => tab.type === "page").webSocketDebuggerUrl);
  await until(() => socket.readyState === WebSocket.OPEN);
  cdp = new CDP(socket, message => {
    if (message.method === "Page.loadEventFired") loads++;
    if (message.method === "Runtime.exceptionThrown") errors.push(message.params.exceptionDetails.text);
    if (message.method === "Fetch.requestPaused") {
      const {requestId, request} = message.params;
      const url = new URL(request.url);
      const favicon = url.origin === origin && url.pathname === "/favicon.ico" && request.method === "GET";
      const allowed = ["GET", "HEAD"].includes(request.method) && url.origin === origin &&
        (favicon || ["/dev/research-bridge", "/dev/reference-triage", "/dev/editorial-workbench"]
          .some(prefix => url.pathname.startsWith(prefix)));
      requests.push({method: request.method, path: url.pathname});
      if (!allowed) violations.push(request.url);
      const task = favicon ? cdp.send("Fetch.fulfillRequest", {requestId, responseCode:204}) :
        cdp.send(allowed ? "Fetch.continueRequest" : "Fetch.failRequest",
          allowed ? {requestId} : {requestId, errorReason: "BlockedByClient"});
      pending.add(task); task.finally(() => pending.delete(task));
    }
  });
  await cdp.send("Page.enable");
  await cdp.send("Runtime.enable");
  await cdp.send("Fetch.enable", {patterns: [{urlPattern: "*"}]});
  const evaluate = expression => cdp.evaluate(expression);
  async function navigate(route) {
    const before = loads;
    await cdp.send("Page.navigate", {url: origin + route});
    await until(() => loads > before);
    await until(() => evaluate("document.readyState === 'complete'"));
  }
  async function activate(selector) {
    await evaluate(`document.querySelector(${JSON.stringify(selector)}).focus()`);
    const before = loads;
    await dispatchKey(cdp, "Enter", 13);
    await until(() => loads > before);
  }
  async function noOverflow() {
    assert.equal(await evaluate("document.documentElement.scrollWidth <= innerWidth"), true);
  }
  await cdp.send("Emulation.setDeviceMetricsOverride", {width:1280,height:900,deviceScaleFactor:1,mobile:false});
  await navigate("/dev/research-bridge");
  assert.equal(await evaluate("document.documentElement.dir"), "rtl");
  assert.equal(await evaluate("document.querySelectorAll('.case-card').length"), 20);
  await dispatchKey(cdp, "Tab", 9);
  assert.equal(await evaluate("document.activeElement.className"), "skip-link");
  await dispatchKey(cdp, "Enter", 13);
  assert.equal(await evaluate("document.activeElement.id"), "main-content");
  await noOverflow();
  await activate('a[href="/dev/research-bridge/intake-1"]');
  assert.equal(await evaluate("location.pathname"), "/dev/research-bridge/intake-1");
  assert.equal(await evaluate("document.querySelectorAll('a[href^=\"/fiqh/nodes/\"]').length"), 1);
  assert.ok(await evaluate("document.querySelector('#reference-1').textContent.includes('الصفحة: 7')"));
  await activate('a[rel="next"]');
  assert.equal(await evaluate("location.pathname"), "/dev/research-bridge/intake-2");
  await activate('a[rel="prev"]');
  assert.equal(await evaluate("location.pathname"), "/dev/research-bridge/intake-1");
  await activate('a[href="/dev/reference-triage/intake-1#reference-1"]');
  assert.equal(await evaluate("location.hash"), "#reference-1");
  assert.ok(await evaluate("!!document.querySelector(location.hash)"));
  await navigate("/dev/research-bridge/intake-7");
  assert.equal(await evaluate("document.querySelector('a[href^=\"/fiqh/nodes/\"]').getAttribute('href')"), "/fiqh/nodes/2?edition=7001");
  assert.deepEqual(await evaluate("Array.from(document.querySelectorAll('#reference-1 section ol li'), x=>x.textContent)"), ["كِتَابٌ اصطناعي", "بابٌ اصطناعي أول"]);
  assert.equal(await evaluate("getComputedStyle(document.querySelector('#reference-1 section ol li')).whiteSpace"), "pre-wrap");
  for (const width of [320,375]) {
    await cdp.send("Emulation.setDeviceMetricsOverride", {width,height:844,deviceScaleFactor:1,mobile:true});
    await navigate("/dev/research-bridge/batch-synthetic-csv-1");
    const exact = "  سُؤَالٌ اصطناعي\r\nبسطرٍ وتشكيل e\u0301  ";
    assert.ok((await evaluate("Array.from(document.querySelectorAll('pre code'), x=>x.textContent)")).includes(exact));
    await evaluate("document.querySelectorAll('details').forEach(x=>x.open=true)");
    assert.equal(await evaluate("document.querySelectorAll('script,iframe,video,audio,form').length"), 0);
    await noOverflow();
    await navigate("/dev/research-bridge/history");
    assert.equal(await evaluate("document.querySelectorAll('a[href^=\"/fiqh/nodes/\"]').length"), 0);
    assert.ok(await evaluate("document.body.textContent.includes('الانتقال مغلق')"));
    await noOverflow();
  }
  const screenshot = path.join(temp, "fatwa-research-bridge-mobile.png");
  const {data} = await cdp.send("Page.captureScreenshot", {format:"png",captureBeyondViewport:false});
  await writeFile(screenshot, Buffer.from(data, "base64"));
  await activate('a[href="/dev/editorial-workbench/history#references"]');
  assert.ok(await evaluate("!!document.querySelector('#references')"));
  await navigate("/dev/research-bridge?edition=7001");
  assert.ok(await evaluate("document.body.textContent.includes('لا تقبل هذه الشاشة')"));
  await activate('main a[href="/dev/research-bridge"]');
  assert.equal(await evaluate("document.querySelectorAll('.case-card').length"), 20);
  await noOverflow();
  await Promise.all([...pending]);
  assert.deepEqual(errors, []);
  assert.deepEqual(violations, []);
  assert.ok(requests.length > 0);
  console.log(JSON.stringify({result:"PASS",catalog:"fixed synthetic test double; no database",checks:[
    "desktop RTL", "keyboard skip and previous/next", "320/375px no overflow", "exact Arabic CRLF",
    "verified catalog href", "closed unverified", "triage/workbench anchors", "query recovery",
    "GET/HEAD local only"], screenshot}));
} finally {
  clearTimeout(watchdog); socket?.close(); cdp?.close();
  const ended = new Promise(resolve => browser.once("exit", resolve));
  if (browser.exitCode === null && !launchError) { browser.kill(); await ended; }
  const target = path.resolve(profile);
  assert.equal(path.dirname(target), temp);
  assert.ok(path.basename(target).startsWith("fatwa-research-bridge-browser-"));
  await rm(target, {recursive:true,force:true,maxRetries:5,retryDelay:100});
}
