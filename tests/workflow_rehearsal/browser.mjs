// Actual Chrome with its sandbox enabled; application traffic is loopback GET/HEAD only.
import assert from "node:assert/strict";
import {spawn, execFileSync} from "node:child_process";
import {createHash} from "node:crypto";
import {mkdtemp, readFile, rm} from "node:fs/promises";
import os from "node:os";
import path from "node:path";
import {CDP, loopbackOrigin} from "../acceptance/wave7/cdp.mjs";
import {dispatchKey} from "../acceptance/wave7/keyboard.mjs";

const origin = loopbackOrigin(process.argv[2]);
const originals = JSON.parse(await readFile(process.argv[3], "utf8"));
const keys = ["history", "intake-1", "intake-2", "intake-3", "intake-4", "intake-5",
  "intake-6", "intake-7", "intake-8"];
const route = "/dev/workflow-rehearsal";
const allowedRoutes = [route, "/dev/editorial-workbench", "/dev/reference-triage"];
const temp = path.resolve(os.tmpdir()), prefix = "fatwa-workflow-rehearsal-browser-";
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
const pending = new Set();
const pause = ms => new Promise(resolve => setTimeout(resolve, ms));
async function until(check, label) {
  const deadline = Date.now() + 10000;
  while (Date.now() < deadline) { if (await check()) return; await pause(30); }
  throw Error("Workflow browser timed out: " + label);
}
const watchdog = setTimeout(() => { socket?.close(); browser.kill(); }, 130000);
try {
  let port;
  await until(async () => {
    if (launchError) throw launchError;
    try { port = Number((await readFile(path.join(profile, "DevToolsActivePort"), "utf8")).split("\n")[0]); return !!port; }
    catch { return false; }
  }, "Chrome startup");
  const tabs = await fetch(`http://127.0.0.1:${port}/json/list`).then(response => response.json());
  socket = new WebSocket(tabs.find(tab => tab.type === "page").webSocketDebuggerUrl);
  await until(() => socket.readyState === WebSocket.OPEN, "DevTools connection");
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
        (favicon || allowedRoutes.some(base => url.pathname === base || url.pathname.startsWith(base + "/")));
      requests.push({method: request.method, path: url.pathname, search: url.search});
      if (!allowed) violations.push({method: request.method, url: request.url});
      // Only the automatic local favicon probe is suppressed, never application requests.
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
    await until(() => evaluate("document.readyState === 'complete'"), "complete document");
  }
  async function navigate(relative) {
    const before = loads;
    await cdp.send("Page.navigate", {url: origin + relative});
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
  async function noOverflow(label) {
    await evaluate("document.querySelectorAll('details').forEach(element=>element.open=true)");
    assert.equal(await evaluate("document.documentElement.scrollWidth <= innerWidth"), true, label);
  }
  async function originalContent(key) {
    const source = await evaluate("document.querySelector('#source code').textContent");
    assert.equal(source, originals[key].source, key + " exact original source");
    assert.equal(createHash("sha256").update(source).digest("hex"), originals[key].source_sha256);
    if (originals[key].question !== null) {
      assert.equal(await evaluate("document.querySelector('#question code').textContent"),
        originals[key].question, key + " exact original question");
    }
    assert.ok(await evaluate(`document.body.textContent.includes(${JSON.stringify(originals[key].payload_sha256)})`),
      key + " original payload identity");
  }
  for (const width of [1280, 375, 320]) {
    await cdp.send("Emulation.setDeviceMetricsOverride", {width, height: 900,
      deviceScaleFactor: 1, mobile: width < 500});
    for (const relative of [route, route + "/history", route + "/intake-7"]) {
      await navigate(relative);
      assert.equal(await evaluate("document.documentElement.dir"), "rtl");
      assert.equal(await evaluate("document.documentElement.lang"), "ar");
      assert.equal(await evaluate("document.querySelectorAll('h1').length"), 1);
      assert.equal(await evaluate("document.querySelectorAll('script,iframe,video,audio').length"), 0);
      assert.equal(await evaluate("document.querySelector('#main-content').getAttribute('tabindex')"), "-1");
      assert.equal(await evaluate(`document.querySelector('link[rel="stylesheet"]').getAttribute('href')`), route + "/style.css");
      await noOverflow(relative + " " + width + "px");
      await dispatchKey(cdp, "Tab", 9);
      assert.equal(await evaluate(`document.activeElement.matches('a[href="#main-content"]')`), true);
      await dispatchKey(cdp, "Enter", 13);
      assert.equal(await evaluate("document.activeElement.id"), "main-content", "native keyboard skip link");
    }
  }
  checks.push("RTL at 1280/375/320px with expanded content, no overflow, native Tab/Enter skip links");

  await navigate(route);
  const cards = await evaluate(`Array.from(document.querySelectorAll('[data-case-key]'), card=>({
    key:card.dataset.caseKey, links:Array.from(card.querySelectorAll('a[href]'), a=>a.getAttribute('href'))
  }))`);
  assert.deepEqual(cards.map(card => card.key), keys);
  for (const {key, links} of cards) {
    assert.ok(links.includes(`${route}/${key}`), key + " exact case link");
    await navigate(`${route}/${key}`);
    await originalContent(key);
    await noOverflow(key + " expanded narrow detail");
    for (const base of ["/dev/editorial-workbench", "/dev/reference-triage"]) {
      assert.equal(await evaluate(`document.querySelector(${JSON.stringify(`a[href="${base}/${key}"]`)}) !== null`), true,
        key + " matching tool identity");
    }
  }
  checks.push("nine fixed case identities preserve original question/source bytes and tool links");

  await navigate(route);
  await activate(`[data-case-key="intake-7"] a[href="${route}/intake-7"]`);
  assert.equal(await evaluate("location.pathname"), route + "/intake-7");
  assert.equal(await evaluate("document.querySelector('#question code').textContent"),
    "  سُؤَالٌ اصطناعي\tبِعلاماته\nوسطره  ");
  const steps = await evaluate(`Array.from(document.querySelectorAll('[data-step]'), step=>({
    number:step.dataset.step, accepted:step.dataset.accepted, text:step.textContent,
    links:Array.from(step.querySelectorAll('a[href]'), a=>a.getAttribute('href'))
  }))`);
  assert.deepEqual(steps.map(step => step.accepted),
    ["false", "true", "false", "true", "true", "true", "true", "false"],
    "fixed accepted and rejected attempts are distinguished");
  for (const state of ["received", "draft_preparation", "IN_REVIEW", "NEEDS_CHANGES", "REVIEWED_INTERNAL"]) {
    assert.ok(steps.some(step => step.text.includes(state)), state + " in replay timeline");
  }
  assert.ok(await evaluate(`document.querySelector('a[href="?step=0"]').textContent.includes('RECEIVED')`));
  const disclaimer = await evaluate("document.querySelector('#review-disclaimer').textContent");
  assert.ok(disclaimer.includes("REVIEWED_INTERNAL"));
  assert.ok(disclaimer.includes("ليست اعتماداً علمياً ولا إذناً بالنشر"), "Arabic human review limitation");
  const originalTimeline = steps.map(({number, accepted, text}) => ({number, accepted, text}));
  // Each GET selects an immutable prefix. Descending navigation keeps the next
  // target visible and never asks the application to perform a transition.
  for (const step of [...steps].reverse()) {
    const permalink = step.links.find(link => {
      const url = new URL(link, origin + route + "/intake-7");
      return url.origin === origin && url.pathname === route + "/intake-7" &&
        url.searchParams.get("step") === step.number;
    });
    assert.ok(permalink, "replay step permalink " + step.number);
    await activate(`a[href=${JSON.stringify(permalink)}]`);
    assert.equal(await evaluate("new URL(location.href).searchParams.get('step')"), step.number);
    assert.equal(await evaluate(`document.querySelector('[data-step][aria-current="step"]').dataset.step`), step.number);
    await originalContent("intake-7");
    assert.deepEqual(await evaluate(`Array.from(document.querySelectorAll('[data-step]'), step=>({
      number:step.dataset.step, accepted:step.dataset.accepted, text:step.textContent
    }))`), originalTimeline.slice(0, Number(step.number)), "selected prefix retains immutable replay rows");
  }
  await activate('a[href="?step=0"]');
  assert.equal(await evaluate("document.querySelectorAll('[data-step]').length"), 0);
  await originalContent("intake-7");
  await activate(`a[href="${route}/intake-7"]`);
  assert.deepEqual(await evaluate(`Array.from(document.querySelectorAll('[data-step]'), step=>({
    number:step.dataset.step, accepted:step.dataset.accepted, text:step.textContent
  }))`), originalTimeline, "returning to full replay reproduces original timeline");
  checks.push("native keyboard case/step navigation; accepted and rejected attempts; immutable replay and source");

  await navigate(route + "/history");
  const historyTexts = await evaluate("Array.from(document.querySelectorAll('#original-history pre code'), element=>element.textContent)");
  assert.ok(historyTexts.includes("  نص اختبار تحريري فقط.\r\n\tموضع تجريبي للمراجعة.\n"),
    "original revision preserves Arabic, leading whitespace, CRLF, tab and trailing LF");
  assert.ok(await evaluate("document.querySelector('#audit').textContent.trim().length > 0"), "audit remains visible");
  await activate('a[href="/dev/editorial-workbench/history"]');
  assert.equal(await evaluate("location.pathname"), "/dev/editorial-workbench/history");
  await navigate(route + "/intake-7");
  await activate('a[href="/dev/reference-triage/intake-7"]');
  assert.equal(await evaluate("location.pathname"), "/dev/reference-triage/intake-7");
  checks.push("exact CRLF revision and Arabic combining marks; original audit; connected workbench/triage navigation");

  await Promise.all([...pending]);
  assert.deepEqual(errors, []);
  assert.deepEqual(violations, []);
  assert.deepEqual(failedResponses, []);
  assert.ok(requests.some(request => request.path === route + "/style.css"));
  assert.ok(requests.every(request => ["GET", "HEAD"].includes(request.method)));
  checks.push("GET/HEAD-only loopback request policy; zero runtime/network/HTTP errors");
  console.log(JSON.stringify({result: "PASS",
    sha: execFileSync("git", ["rev-parse", "HEAD"], {encoding: "utf8"}).trim(),
    dirty: !!execFileSync("git", ["status", "--porcelain"], {encoding: "utf8"}).trim(),
    browser: await cdp.send("Browser.getVersion"), checks, requests: requests.length,
    fixture: "fixed synthetic build_cases: history, intake-1..intake-8; no owner source files",
    inputHashes: Object.fromEntries(Object.entries(originals).map(([key, value]) => [key, value.payload_sha256])),
    errors, violations, failedResponses}));
} finally {
  clearTimeout(watchdog); socket?.close(); cdp?.close();
  const ended = new Promise(resolve => browser.once("exit", resolve));
  if (browser.exitCode === null && !launchError) { browser.kill(); await ended; }
  const target = path.resolve(profile);
  assert.equal(path.dirname(target), temp);
  assert.ok(path.basename(target).startsWith(prefix));
  await rm(target, {recursive: true, force: true, maxRetries: 5, retryDelay: 100});
}
