// Real Chrome with its sandbox enabled; all application requests are local reads.
import assert from "node:assert/strict";
import {spawn} from "node:child_process";
import {mkdtemp, readFile, writeFile, rm} from "node:fs/promises";
import os from "node:os";
import path from "node:path";
import {CDP, loopbackOrigin} from "../acceptance/wave7/cdp.mjs";
import {dispatchKey} from "../acceptance/wave7/keyboard.mjs";

const origin = loopbackOrigin(process.argv[2]);
const temp = path.resolve(os.tmpdir());
const prefix = "fatwa-editorial-dashboard-browser-";
const profile = await mkdtemp(path.join(temp, prefix));
const executable = process.env.FATWA_FASTBUILD_BROWSER ??
  (process.platform === "win32" ? "C:/Program Files/Google/Chrome/Application/chrome.exe" : "/usr/bin/chromium");
const browser = spawn(executable, ["--headless=new", "--no-first-run", "--no-default-browser-check",
  "--disable-background-networking", "--disable-component-update", "--disable-sync",
  "--remote-debugging-address=127.0.0.1", "--remote-debugging-port=0", "--user-data-dir=" + profile,
  "about:blank"], {windowsHide: true, stdio: "ignore"});
let launchError, socket, cdp, loads = 0;
browser.on("error", error => { launchError = error; });
const errors = [], violations = [], requests = [], failedResponses = [];
const pending = new Set();
const pause = ms => new Promise(resolve => setTimeout(resolve, ms));
async function until(check) {
  const deadline = Date.now() + 10000;
  while (Date.now() < deadline) { if (await check()) return; await pause(30); }
  throw Error("Dashboard browser check timed out");
}
const watchdog = setTimeout(() => { socket?.close(); browser.kill(); }, 100000);
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
    if (message.method === "Runtime.consoleAPICalled" && message.params.type === "error") {
      errors.push("console: " + JSON.stringify(message.params.args));
    }
    if (message.method === "Network.loadingFailed") errors.push(message.params.errorText);
    if (message.method === "Network.responseReceived" && message.params.response.status >= 400) {
      failedResponses.push({url: message.params.response.url, status: message.params.response.status});
    }
    if (message.method === "Fetch.requestPaused") {
      const {requestId, request} = message.params;
      const url = new URL(request.url);
      const favicon = url.origin === origin && url.pathname === "/favicon.ico" && request.method === "GET";
      const allowed = ["GET", "HEAD"].includes(request.method) && url.origin === origin &&
        (favicon || ["/dev/editorial-dashboard", "/dev/editorial-queue", "/dev/editorial-workbench",
          "/dev/reference-triage"].some(route => url.pathname === route || url.pathname.startsWith(route + "/")));
      requests.push({method: request.method, path: url.pathname});
      if (!allowed) violations.push(request.url);
      // No favicon route exists; suppress only the automatic local browser probe.
      const task = favicon ? cdp.send("Fetch.fulfillRequest", {requestId, responseCode: 204}) :
        cdp.send(allowed ? "Fetch.continueRequest" : "Fetch.failRequest",
          allowed ? {requestId} : {requestId, errorReason: "BlockedByClient"});
      pending.add(task); task.finally(() => pending.delete(task));
    }
  });
  for (const domain of ["Page", "Runtime", "Network"]) await cdp.send(domain + ".enable");
  await cdp.send("Fetch.enable", {patterns: [{urlPattern: "*"}]});
  const evaluate = expression => cdp.evaluate(expression);
  async function navigate(route) {
    const before = loads;
    await cdp.send("Page.navigate", {url: origin + route});
    await until(() => loads > before);
    await until(() => evaluate("document.readyState === 'complete'"));
  }
  async function noOverflow() {
    assert.equal(await evaluate("document.documentElement.scrollWidth <= innerWidth"), true,
      "document must fit viewport width");
  }
  const exact = "  سُؤَالٌ اصطناعي\r\nبسطرٍ وتشكيل e\u0301  ";
  let screenshot;
  for (const width of [1280, 375, 320]) {
    await cdp.send("Emulation.setDeviceMetricsOverride", {width, height: 900,
      deviceScaleFactor: 1, mobile: width < 500});
    await navigate("/dev/editorial-dashboard");
    assert.equal(await evaluate("document.documentElement.dir"), "rtl");
    assert.equal(await evaluate("document.documentElement.lang"), "ar");
    assert.equal(await evaluate("document.querySelectorAll('[data-case-key]').length"), 20);
    assert.ok((await evaluate("Array.from(document.querySelectorAll('pre code'), x=>x.textContent)")).includes(exact));
    assert.equal(await evaluate("document.querySelectorAll('script,iframe,video,audio').length"), 0);
    await evaluate("document.querySelectorAll('details').forEach(x=>x.open=true)");
    await noOverflow();
    if (width === 375) {
      screenshot = path.join(temp, "fatwa-editorial-dashboard-mobile.png");
      const {data} = await cdp.send("Page.captureScreenshot", {format: "png", captureBeyondViewport: false});
      await writeFile(screenshot, Buffer.from(data, "base64"));
    }
  }
  const cards = await evaluate(`Array.from(document.querySelectorAll('[data-case-key]'), card => ({
    key: card.dataset.caseKey, links: Array.from(card.querySelectorAll('a[href]'), a => a.getAttribute('href'))
  }))`);
  for (const {key, links} of cards) {
    for (const [route, packet] of [["editorial-queue", false], ["editorial-workbench", false],
      ["reference-triage", false], ["editorial-workbench", true]]) {
      assert.ok(links.some(link => {
        const url = new URL(link, origin);
        return url.origin === origin && url.pathname === `/dev/${route}/${key}` &&
          (packet ? url.searchParams.get("packet") === "html" : !url.searchParams.has("packet"));
      }), `Missing exact ${route} ${packet ? "packet " : ""}link for ${key}`);
    }
  }
  await evaluate("document.querySelector('#batch').focus()");
  await dispatchKey(cdp, "Home", 36);
  await dispatchKey(cdp, "ArrowDown", 40);
  assert.equal(await evaluate("document.activeElement.id"), "batch");
  const selectedBatch = await evaluate("document.querySelector('#batch').value");
  assert.equal(selectedBatch, "original");
  await dispatchKey(cdp, "Tab", 9);
  assert.equal(await evaluate("document.activeElement.matches('button[type=submit]')"), true);
  const before = loads;
  await dispatchKey(cdp, "Enter", 13);
  await until(() => loads > before);
  assert.equal(await evaluate("new URL(location.href).searchParams.get('batch')"), selectedBatch);
  assert.equal(await evaluate("document.querySelectorAll('[data-case-key]').length"), 9);
  await noOverflow();

  const csv = cards.find(card => card.key === "batch-synthetic-csv-1");
  for (const link of csv.links.filter(link => link.startsWith("/dev/"))) {
    await navigate(link);
    assert.ok(await evaluate("document.body.textContent.includes('SYN-CSV-1')"), link);
    assert.equal(await evaluate("location.pathname"), new URL(link, origin).pathname);
  }
  await navigate("/dev/editorial-dashboard?batch=synthetic-malformed");
  assert.equal(await evaluate("document.querySelectorAll('[data-case-key]').length"), 0);
  assert.ok(await evaluate("document.body.textContent.includes('MALFORMED_INPUT')"));
  assert.ok(await evaluate("document.querySelector('main').textContent.includes('لا توجد')"));
  await noOverflow();
  assert.equal(await evaluate("fetch('/dev/editorial-dashboard', {method:'HEAD'}).then(r=>r.status)"), 200);
  await Promise.all([...pending]);
  assert.deepEqual(errors, []);
  assert.deepEqual(violations, []);
  assert.deepEqual(failedResponses, []);
  assert.ok(requests.length > 0);
  console.log(JSON.stringify({result: "PASS", checks: ["1280/375/320px RTL without overflow",
    "keyboard batch filtering", "exact Arabic CRLF and combining accent", "20 exact case link sets",
    "queue/workbench/investigation/packet navigation", "malformed batch empty state",
    "GET/HEAD local only", "no runtime/network/HTTP errors"], screenshot}));
} finally {
  clearTimeout(watchdog); socket?.close(); cdp?.close();
  const ended = new Promise(resolve => browser.once("exit", resolve));
  if (browser.exitCode === null && !launchError) { browser.kill(); await ended; }
  const target = path.resolve(profile);
  assert.equal(path.dirname(target), temp);
  assert.ok(path.basename(target).startsWith(prefix));
  await rm(target, {recursive: true, force: true, maxRetries: 5, retryDelay: 100});
}
