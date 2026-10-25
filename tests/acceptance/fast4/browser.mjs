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
const expected = JSON.parse(await readFile(process.argv[3], "utf8"));
const routes = ["editorial-dashboard", "editorial-search", "editorial-followup", "editorial-export"];
const allowedRoutes = [...routes, "editorial-queue", "editorial-workbench", "reference-triage"];
const temp = path.resolve(os.tmpdir()), prefix = "fatwa-fast4-browser-";
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
  throw Error("FAST4 browser timed out: " + label);
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
  const exact = "  سُؤَالٌ اصطناعي\r\nبسطرٍ وتشكيل e\u0301  ";
  for (const width of [1280, 375, 320]) {
    await cdp.send("Emulation.setDeviceMetricsOverride", {width, height: 900,
      deviceScaleFactor: 1, mobile: width < 500});
    for (const route of routes) {
      await navigate(`/dev/${route}`);
      assert.equal(await evaluate("document.documentElement.dir"), "rtl");
      assert.equal(await evaluate("document.documentElement.lang"), "ar");
      assert.equal(await evaluate("document.querySelectorAll('h1').length"), 1);
      assert.deepEqual(await evaluate("Array.from(document.querySelectorAll('nav[aria-label=\"أدوات FAST4\"] a'), a=>a.pathname)"),
        routes.map(name => `/dev/${name}`));
      await evaluate("document.querySelectorAll('details').forEach(x=>x.open=true)");
      assert.equal(await evaluate("document.documentElement.scrollWidth <= innerWidth"), true, `${route} ${width}px`);
      await dispatchKey(cdp, "Tab", 9);
      assert.equal(await evaluate("document.activeElement.matches('a[href^=\"#main\"]')"), true);
      await dispatchKey(cdp, "Enter", 13);
      assert.equal(await evaluate("document.activeElement.tagName"), "MAIN", route + " skip target");
    }
  }
  checks.push("four pages RTL 1280/375/320px, no overflow, native Tab/Enter skip links");
  for (const route of [...routes, routes[0]]) {
    await activate(`nav[aria-label="أدوات FAST4"] a[href="/dev/${route}"]`);
    assert.equal(await evaluate("location.pathname"), `/dev/${route}`);
  }
  checks.push("keyboard navigation connects all four pages");

  const cards = await evaluate(`Array.from(document.querySelectorAll('[data-case-key]'), card => ({
    key: card.dataset.caseKey, links: Array.from(card.querySelectorAll('a[href]'), a => a.getAttribute('href'))
  }))`);
  assert.deepEqual(cards.map(card => card.key), expected.keys);
  assert.equal(cards.length, 20);
  assert.ok((await evaluate("Array.from(document.querySelectorAll('pre code'), x=>x.textContent)")).includes(exact));
  for (const card of cards) {
    assert.ok(card.links.some(link => new URL(link, origin).pathname === `/dev/editorial-queue/${card.key}`));
  }
  await activate('[data-case-key="batch-synthetic-csv-1"] a[href^="/dev/editorial-queue/"]');
  assert.equal(await evaluate("location.pathname"), "/dev/editorial-queue/batch-synthetic-csv-1");
  assert.ok(await evaluate("document.body.textContent.includes('SYN-CSV-1')"));
  checks.push("20 dashboard identities match queue; exact Arabic CRLF and combining characters");

  await navigate("/dev/editorial-search");
  await evaluate("document.querySelector('#q').focus()");
  await cdp.send("Input.insertText", {text: "منقح"});
  await evaluate("document.querySelector('#source').value='draft'");
  await activate('button[type="submit"]');
  const revisionLinks = await evaluate("Array.from(document.querySelectorAll('article h3 a'), a=>a.getAttribute('href'))");
  assert.deepEqual(revisionLinks.map(link => Number(new URL(link, origin).searchParams.get('revision'))), [2, 4, 7, 9, 11]);
  for (const link of revisionLinks) {
    const url = new URL(link, origin);
    assert.equal(url.pathname, "/dev/editorial-workbench/history");
    assert.equal(url.hash, "#snapshot");
    await navigate(link);
    assert.equal(await evaluate("document.querySelector('#snapshot strong').textContent"), url.searchParams.get('revision'));
  }
  checks.push("Arabic search opens exact immutable revisions 2/4/7/9/11");

  await navigate("/dev/editorial-followup");
  assert.equal(await evaluate("document.querySelectorAll('.case-card').length"), 17);
  await evaluate("document.querySelector('#reason').value='missing_receipt'; document.querySelector('#batch').value='synthetic-csv'; document.querySelector('#status').value='blocked'");
  await activate('button[type="submit"]');
  assert.equal(await evaluate("document.querySelectorAll('.case-card').length"), 2);
  await activate('.case-card h3 a');
  assert.equal(await evaluate("location.pathname"), "/dev/editorial-followup/batch-synthetic-csv-2");
  assert.equal(await evaluate("document.querySelector('a[rel=prev]')"), null);
  const filterQuery = await evaluate("location.search");
  await activate('a[rel="next"]');
  assert.equal(await evaluate("location.pathname"), "/dev/editorial-followup/batch-synthetic-csv-4");
  assert.equal(await evaluate("location.search"), filterQuery);
  assert.equal(await evaluate("document.querySelector('a[rel=next]')"), null);
  await activate('a[rel="prev"]');
  assert.equal(await evaluate("location.pathname"), "/dev/editorial-followup/batch-synthetic-csv-2");
  await activate('.detail-nav a');
  assert.equal(await evaluate("document.querySelectorAll('.case-card').length"), 2);
  await navigate("/dev/editorial-followup/history");
  await activate('a[href="/dev/reference-triage/history#reference-1"]');
  assert.equal(await evaluate("location.hash"), "#reference-1");
  assert.equal(await evaluate("document.querySelector('#reference-1') !== null"), true);
  await navigate("/dev/editorial-followup/batch-synthetic-csv-1");
  assert.equal(await evaluate("document.querySelector('[aria-labelledby=record-heading] pre code').textContent"), exact);
  await navigate("/dev/editorial-followup?batch=synthetic-malformed");
  assert.equal(await evaluate("document.querySelectorAll('.case-card').length"), 0);
  assert.ok(await evaluate("document.body.textContent.includes('MALFORMED_INPUT')"));
  checks.push("follow-up combined filters, previous/next/return, exact reference ordinal and failed batch");

  await navigate("/dev/editorial-export");
  const downloads = await evaluate("Array.from(document.querySelectorAll('a[download]'), a=>a.getAttribute('href'))");
  assert.deepEqual(downloads.map(link => link.split('/').at(-1)), Object.keys(expected.files));
  const fetched = {};
  for (const link of downloads) {
    const response = await evaluate(`fetch(${JSON.stringify(link)}).then(async r=>({status:r.status,
      cache:r.headers.get('cache-control'), hash:r.headers.get('x-export-sha256'),
      disposition:r.headers.get('content-disposition'), bytes:Array.from(new Uint8Array(await r.arrayBuffer()))}))`);
    const filename = link.split('/').at(-1), raw = Buffer.from(response.bytes);
    assert.equal(response.status, 200);
    assert.equal(response.cache, "no-store");
    assert.equal(response.disposition, `attachment; filename="${filename}"`);
    assert.equal(raw.toString('base64'), expected.files[filename].base64, filename + " exact service bytes");
    assert.equal(raw.length, expected.files[filename].bytes);
    assert.equal(createHash('sha256').update(raw).digest('hex'), expected.files[filename].sha256);
    assert.equal(response.hash, expected.files[filename].sha256);
    fetched[filename] = raw;
  }
  const report = JSON.parse(fetched['report.json']), manifest = JSON.parse(fetched['manifest.json']);
  assert.deepEqual(report.cases.map(item=>item.navigation.case_key).sort(), [...expected.keys].sort());
  assert.equal(report.batches.length, 4);
  assert.ok(JSON.stringify(report).includes(JSON.stringify(exact).slice(1,-1)));
  assert.equal(manifest.batch_inputs.find(b=>b.batch_id==='synthetic-csv').input_sha256,
    "0e5d1bfe94c5f9abf5652a065b57212fcaa143abd738f95f2b233df5b68410f8");
  for (const [filename, identity] of Object.entries(manifest.files)) {
    assert.equal(fetched[filename].length, identity.bytes);
    assert.equal(createHash('sha256').update(fetched[filename]).digest('hex'), identity.sha256);
  }
  checks.push("four browser downloads exactly match service bytes, SHA256, 20 identities and original text");
  await Promise.all([...pending]);
  assert.deepEqual(errors, []); assert.deepEqual(violations, []); assert.deepEqual(failedResponses, []);
  assert.ok(requests.length > 0);
  checks.push("GET/HEAD-only loopback policy; zero runtime, network or HTTP errors");
  const summary = {result: "PASS", sha: execFileSync('git', ['rev-parse', 'HEAD'], {encoding:'utf8'}).trim(),
    dirty: !!execFileSync('git', ['status', '--porcelain'], {encoding:'utf8'}).trim(),
    browser: await cdp.send('Browser.getVersion'), checks, requests: requests.length,
    errors, violations, failedResponses, exportHashes: Object.fromEntries(Object.entries(expected.files).map(([name,file])=>[name,file.sha256]))};
  const output = path.resolve(process.env.FATWA_FAST4_REPORT ?? '.local/qa/fast4/browser.json');
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
