import assert from "node:assert/strict";
import {setTimeout as delay} from "node:timers/promises";
import {ProtectedBrowser} from "../acceptance/fastbuild/startup.mjs";
import {CDP, loopbackOrigin} from "../acceptance/wave7/cdp.mjs";
import {dispatchKey} from "../acceptance/wave7/keyboard.mjs";

const origin = loopbackOrigin(process.argv[2]);
const exact = JSON.parse(process.argv[3]);
const controller = new AbortController();
const browser = new ProtectedBrowser({
  executable: process.env.FATWA_FASTBUILD_BROWSER ?? (process.platform === "win32"
    ? "C:/Program Files/Google/Chrome/Application/chrome.exe" : "/usr/bin/chromium"),
  signal: controller.signal,
});
let cdp, loads = 0, requests = 0;
const failures = [], pending = new Set();
const deadline = setTimeout(() => { controller.abort(); browser.close(); }, 150000);
async function until(check) {
  const end = Date.now() + 10000;
  while (Date.now() < end) { if (await check()) return; await delay(30); }
  throw Error("Operator browser condition timed out");
}
try {
  const socket = await browser.start();
  cdp = new CDP(socket, message => {
    if (message.method === "Page.loadEventFired") loads++;
    if (message.method === "Runtime.exceptionThrown" || message.method === "Network.loadingFailed") failures.push(message);
    if (message.method === "Runtime.consoleAPICalled" && message.params.type === "error") failures.push(message);
    if (message.method === "Network.responseReceived" && message.params.response.status >= 400) failures.push(message);
    if (message.method !== "Fetch.requestPaused") return;
    const {request, requestId} = message.params;
    const url = new URL(request.url);
    const favicon = url.origin === origin && url.pathname === "/favicon.ico" && request.method === "GET";
    const allowed = ["GET", "HEAD"].includes(request.method) && url.origin === origin &&
      (favicon || /^\/operator(?:\/|$)/.test(url.pathname) ||
       /^\/dev\/(editorial-queue|editorial-search|editorial-workbench|research-bridge|editorial-export)(?:\/|$)/.test(url.pathname));
    requests++;
    if (!allowed) failures.push({blocked: request.url, method: request.method});
    const task = favicon ? cdp.send("Fetch.fulfillRequest", {requestId, responseCode: 204}) :
      cdp.send(allowed ? "Fetch.continueRequest" : "Fetch.failRequest",
        allowed ? {requestId} : {requestId, errorReason: "BlockedByClient"});
    pending.add(task);
    task.catch(error => failures.push(String(error))).finally(() => pending.delete(task));
  });
  for (const domain of ["Page", "Runtime", "Network"]) await cdp.send(domain + ".enable");
  await cdp.send("Fetch.enable", {patterns: [{urlPattern: "*"}]});
  const evaluate = expression => cdp.evaluate(expression);
  async function loaded(before) {
    await until(() => loads > before);
    await until(() => evaluate("document.readyState === 'complete'"));
  }
  async function navigate(route) {
    const before = loads;
    await cdp.send("Page.navigate", {url: origin + route});
    await loaded(before);
  }
  async function enter(selector) {
    const literal = JSON.stringify(selector);
    await evaluate(`document.querySelector(${literal}).focus()`);
    assert.equal(await evaluate(`document.activeElement.matches(${literal})`), true);
    const before = loads;
    await dispatchKey(cdp, "Enter", 13);
    await loaded(before);
  }
  async function viewport(width) {
    assert.equal(await evaluate("document.documentElement.dir"), "rtl");
    assert.equal(await evaluate("innerWidth"), width);
    // Desktop Chrome reserves width for its vertical scrollbar; mobile overlays it.
    if (width < 500) assert.equal(await evaluate("document.documentElement.clientWidth"), width);
    assert.equal(await evaluate("document.documentElement.scrollWidth <= document.documentElement.clientWidth"), true, "horizontal overflow");
  }
  for (const width of [320, 375, 1280]) {
    await cdp.send("Emulation.setDeviceMetricsOverride", {width, height: 900, deviceScaleFactor: 1, mobile: width < 500});
    await navigate("/operator");
    await viewport(width);
    await dispatchKey(cdp, "Tab", 9);
    assert.equal(await evaluate("document.activeElement.classList.contains('skip')"), true);
    assert.equal(await evaluate("getComputedStyle(document.activeElement).outlineWidth"), "3px");
    await dispatchKey(cdp, "Enter", 13);
    assert.equal(await evaluate("document.activeElement.id"), "main-content");
    await enter('a[href="/operator/history"]');
    await enter('a[href="/operator/history?revision=4"]');
    assert.equal(await evaluate("document.querySelector('[data-case]').dataset.revision"), "4");
    await viewport(width);
    const serviceLinks = await evaluate("Array.from(document.querySelectorAll('.services a'), a => a.getAttribute('href'))");
    assert.equal(serviceLinks.length, 5);
    for (const href of serviceLinks) {
      await navigate("/operator/history?revision=4");
      await enter(`.services a[href=${JSON.stringify(href)}]`);
      if (href.includes("editorial-workbench")) {
        assert.equal(await evaluate("location.search"), "?revision=4");
        assert.equal(await evaluate("!!document.getElementById('snapshot')"), true);
      }
    }
    await navigate("/operator");
    await evaluate("document.getElementById('q').value = 'اصطناعي'");
    await enter('button[type="submit"]');
    assert.equal(await evaluate("Number(document.querySelector('[data-total]').dataset.total) > 0"), true);
    await viewport(width);
    const hit = await evaluate("Array.from(document.querySelectorAll('main a')).find(a => a.getAttribute('href').includes('/operator/') && a.search.includes('revision=')).getAttribute('href')");
    const expected = new URL(hit, origin);
    await enter(`a[href=${JSON.stringify(hit)}]`);
    assert.equal(await evaluate("document.querySelector('[data-case]').dataset.revision"), expected.searchParams.get("revision"));
    await enter("#return");
    assert.equal(await evaluate("document.querySelector('#q').value"), "اصطناعي");
    await navigate(`/operator/${exact.key}`);
    assert.equal(await evaluate("document.querySelector('.question code').textContent"), exact.question);
    await viewport(width);
  }
  await Promise.all(pending);
  assert.deepEqual(failures, []);
  console.log(JSON.stringify({result: "PASS", viewports: [320, 375, 1280], requests,
    catalog: "explicit unavailable-catalog double; no DB", externalOrWriteRequests: 0}));
} catch (error) {
  console.error(error);
  process.exitCode = 1;
} finally {
  clearTimeout(deadline);
  const cleanup = await browser.close();
  cdp?.close();
  if (cleanup.result !== "PASS") { console.error(cleanup); process.exitCode = 1; }
}
