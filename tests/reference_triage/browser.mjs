// Reuse the protected CDP/keyboard utilities; no browser security bypass.
import assert from "node:assert/strict";
import {spawn} from "node:child_process";
import {mkdtemp, readFile, writeFile, rm} from "node:fs/promises";
import os from "node:os";
import path from "node:path";
import {CDP, loopbackOrigin} from "../acceptance/wave7/cdp.mjs";
import {dispatchKey} from "../acceptance/wave7/keyboard.mjs";

const origin = loopbackOrigin(process.argv[2]);
const temp = path.resolve(os.tmpdir());
const profile = await mkdtemp(path.join(temp, "fatwa-reference-triage-browser-"));
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
        (favicon || url.pathname.startsWith("/dev/reference-triage") || url.pathname.startsWith("/dev/editorial-workbench"));
      requests.push({method: request.method, path: url.pathname});
      if (!allowed) violations.push(request.url);
      // The existing site has no favicon route; suppress Chrome's automatic
      // probe explicitly, without permitting any external request.
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
  async function noOverflow() {
    assert.equal(await evaluate("document.documentElement.scrollWidth <= innerWidth"), true);
  }
  await cdp.send("Emulation.setDeviceMetricsOverride", {width:1280,height:900,deviceScaleFactor:1,mobile:false});
  await navigate("/dev/reference-triage");
  assert.equal(await evaluate("document.documentElement.dir"), "rtl");
  assert.equal(await evaluate("document.querySelectorAll('a[href^=\"/dev/reference-triage/\"]').length"), 20);
  assert.ok(await evaluate("document.body.textContent.includes('synthetic-malformed')"));
  await noOverflow();
  await evaluate("document.querySelector('#status').focus()");
  await dispatchKey(cdp, "Home", 36);
  await dispatchKey(cdp, "ArrowDown", 40);
  await evaluate("document.querySelector('button[type=submit]').focus()");
  const before = loads;
  await dispatchKey(cdp, "Enter", 13);
  await until(() => loads > before);
  assert.equal(await evaluate("new URL(location.href).searchParams.get('status')"), "verified");
  assert.equal(await evaluate("document.querySelectorAll('a[href^=\"/dev/reference-triage/\"]').length"), 8);
  await cdp.send("Emulation.setDeviceMetricsOverride", {width:360,height:844,deviceScaleFactor:1,mobile:true});
  await navigate("/dev/reference-triage/batch-synthetic-csv-1");
  const exact = "  سُؤَالٌ اصطناعي\r\nبسطرٍ وتشكيل e\u0301  ";
  assert.ok((await evaluate("Array.from(document.querySelectorAll('pre code'), x=>x.textContent)")).includes(exact));
  await evaluate("document.querySelectorAll('details').forEach(x=>x.open=true)");
  assert.ok(await evaluate("document.body.textContent.includes('source_input_sha256')"));
  assert.equal(await evaluate("document.querySelectorAll('script,iframe,video,audio').length"), 0);
  await noOverflow();
  const screenshot = path.join(temp, "fatwa-reference-triage-mobile.png");
  const {data} = await cdp.send("Page.captureScreenshot", {format:"png",captureBeyondViewport:false});
  await writeFile(screenshot, Buffer.from(data, "base64"));
  const workbench = await evaluate("document.querySelector('a[href=\"/dev/editorial-workbench/batch-synthetic-csv-1\"]').getAttribute('href')");
  await navigate(workbench);
  assert.ok(await evaluate("document.body.textContent.includes('SYN-CSV-1')"));
  await navigate("/dev/reference-triage?batch=synthetic-malformed");
  assert.ok(await evaluate("document.body.textContent.includes('تعذر تحليل الدفعة')"));
  assert.equal(await evaluate("document.querySelectorAll('a[href^=\"/dev/reference-triage/\"]').length"), 0);
  await noOverflow();
  await Promise.all([...pending]);
  assert.deepEqual(errors, []);
  assert.deepEqual(violations, []);
  assert.ok(requests.length > 0);
  console.log(JSON.stringify({result:"PASS",checks:["desktop RTL", "keyboard filter", "360px no overflow",
    "exact Arabic CRLF", "guarded identity", "workbench link", "failed batch", "GET/HEAD local only"], screenshot}));
} finally {
  clearTimeout(watchdog); socket?.close(); cdp?.close();
  const ended = new Promise(resolve => browser.once("exit", resolve));
  if (browser.exitCode === null && !launchError) { browser.kill(); await ended; }
  // Only remove the exact fresh temporary profile we created under the temp root.
  const target = path.resolve(profile);
  assert.equal(path.dirname(target), temp);
  assert.ok(path.basename(target).startsWith("fatwa-reference-triage-browser-"));
  await rm(target, {recursive:true,force:true,maxRetries:5,retryDelay:100});
}
