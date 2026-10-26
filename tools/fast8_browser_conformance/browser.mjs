// Only the existing Django WSGI server is used. No overlay, invented routes,
// catalog mocks, extra Chrome flags, or retry of failed application checks.
import assert from "node:assert/strict";
import {ProtectedBrowser, failureResult} from "../../tests/acceptance/fastbuild/startup.mjs";
import {CDP, loopbackOrigin} from "../../tests/acceptance/wave7/cdp.mjs";
import {dispatchKey} from "../../tests/acceptance/wave7/keyboard.mjs";
import {widths, permitted, digest, assertPacket, assertBlocked, assertViewport, outcome} from "./policy.mjs";

const origin = loopbackOrigin(process.argv[2]);
let input = "";
for await (const chunk of process.stdin) {
  input += chunk;
  assert.ok(input.length <= 1048576, "fixture contract too large");
}
const contract = JSON.parse(input);
const report = {result:"NOT_RUN", browser:"NOT_RUN", checks:[],
  catalog:{...contract.catalog, result:contract.catalog.result === "READY" ? "NOT_RUN" : contract.catalog.result}};
const browser = new ProtectedBrowser({executable:process.env.FATWA_FASTBUILD_BROWSER ??
  (process.platform === "win32" ? "C:/Program Files/Google/Chrome/Application/chrome.exe" : "/usr/bin/chromium")});
let cdp, phase = "browser-startup", current = "startup", loads = 0;
const errors = [], unexpected = [], blocked = [], responses = new Map(), pending = new Set();
let expectedProbe = null;
let viewportWidth = 1280;
const timer = setTimeout(() => browser.controller.abort(browser.error("RUN_DEADLINE_EXCEEDED")), 75000);
const evaluate = expression => cdp.evaluate(expression);
const quote = JSON.stringify;
async function until(check) {
  const end = Date.now() + 8000;
  while (Date.now() < end) {
    browser.controller.signal.throwIfAborted();
    if (await check()) return;
    await new Promise(resolve => setTimeout(resolve, 25));
  }
  throw Error("CHECK_TIMEOUT");
}
async function check(name, action) {
  current = name;
  await action();
  report.checks.push({name, result:"PASS"});
}
async function navigate(route, status = 200) {
  const url = origin + route;
  assert.ok(permitted({method:"GET", url}, origin, contract.catalog.result === "READY"));
  responses.delete(url.split("#")[0]);
  const before = loads;
  const result = await cdp.send("Page.navigate", {url});
  assert.equal(result.errorText, undefined);
  await until(() => loads > before);
  await until(() => evaluate("document.readyState === 'complete'"));
  assert.equal(responses.get(url.split("#")[0]), status, "HTTP document status");
}
async function activate(selector) {
  const href = await evaluate(`document.querySelector(${quote(selector)})?.href`);
  assert.ok(href, "cross-link missing");
  assert.ok(permitted({method:"GET", url:href}, origin, contract.catalog.result === "READY"));
  await evaluate(`document.querySelector(${quote(selector)}).focus()`);
  const before = loads;
  await dispatchKey(cdp, "Enter", 13);
  await until(() => loads > before);
  await until(() => evaluate("document.readyState === 'complete'"));
  assert.equal(await evaluate("location.href"), href);
  assert.equal(responses.get(href.split("#")[0]), 200);
  const hash = new URL(href).hash;
  if (hash) assert.equal(await evaluate(`!!document.getElementById(${quote(hash.slice(1))})`), true);
}
async function layout() {
  assert.equal(await evaluate("document.documentElement.dir"), "rtl");
  assert.equal(await evaluate("document.documentElement.lang"), "ar");
  await evaluate("document.querySelectorAll('details').forEach(x => x.open = true)");
  assertViewport(await evaluate("({inner:innerWidth,client:document.documentElement.clientWidth,scroll:document.documentElement.scrollWidth})"),viewportWidth);
  assert.equal(await evaluate("document.querySelectorAll('iframe,video,audio').length"), 0);
  assert.equal(await evaluate("[...document.forms].every(f => f.method === 'get')"), true);
}
async function getText(route) {
  assert.ok(permitted({method:"GET",url:origin+route}, origin,contract.catalog.result === "READY"));
  return evaluate(`fetch(${quote(route)}, {redirect:'error',signal:AbortSignal.timeout(8000)})
    .then(async r => ({status:r.status,text:await r.text(),hash:r.headers.get('X-Export-SHA256')}))`);
}
async function journey() {
  await cdp.send("Page.enable");
  await cdp.send("Runtime.enable");
  await cdp.send("Network.enable");
  await cdp.send("Fetch.enable", {patterns:[{urlPattern:"*"}]});
  const packet = contract.packets.history;
  const rev = contract.search.revision;
  const selected = packet.snapshots.find(row => row.number === rev);
  for (const width of widths) {
    viewportWidth = width;
    await cdp.send("Emulation.setDeviceMetricsOverride", {width,height:900,deviceScaleFactor:1,mobile:width < 500});
    await check(`${width}: queue keyboard/source/revision to workbench`, async () => {
      await navigate("/dev/editorial-queue/history");
      await layout();
      await dispatchKey(cdp,"Tab",9);
      assert.equal(await evaluate("document.activeElement.getAttribute('href')"), "#main-content");
      await dispatchKey(cdp,"Enter",13);
      assert.equal(await evaluate("document.activeElement.id"), "main-content");
      const codes = await evaluate("[...document.querySelectorAll('#provenance code')].map(x=>x.textContent)");
      assert.ok(codes.includes(packet.source.input_sha256));
      assert.ok(codes.includes(packet.source.text_sha256));
      await activate(`a[href="/dev/editorial-workbench/history?revision=${rev}#snapshot"]`);
      assert.equal(await evaluate("document.querySelector('#snapshot strong').textContent"), String(rev));
      assert.equal(await evaluate("document.querySelector('#snapshot pre').textContent"), selected.title);
      await layout();
      const response = await getText(`/dev/editorial-workbench/history?revision=${rev}&packet=json`);
      assert.equal(response.status,200);
      assertPacket(JSON.parse(response.text),packet,rev);
    });
    await check(`${width}: search keyboard submission/exact historical identity`, async () => {
      await navigate("/dev/editorial-search");
      await evaluate(`document.querySelector('#q').value=${quote(contract.query)};
        document.querySelector('#source').value='draft'; document.querySelector('button[type=submit]').focus()`);
      const before = loads;
      await dispatchKey(cdp,"Enter",13);
      await until(() => loads > before);
      await layout();
      const selector = `article a[href="/dev/editorial-workbench/history?revision=${rev}#snapshot"]`;
      const fields = await evaluate(`[...document.querySelector(${quote(selector)}).closest('article').querySelectorAll('pre code')].map(x=>x.textContent)`);
      assert.deepEqual(fields,contract.search.fields.map(field => field.text));
      const identity = await evaluate(`document.querySelector(${quote(selector)}).closest('article').querySelector('details').textContent`);
      assert.ok(identity.includes(packet.source.text_sha256));
      await activate(selector);
      assert.equal(await evaluate("document.querySelector('#snapshot strong').textContent"),String(rev));
    });
    await check(`${width}: search/research/triage/workbench cross-links`, async () => {
      await navigate("/dev/editorial-search");
      await activate('a[href="/dev/research-bridge"]');
      await layout();
      await activate('a[href="/dev/research-bridge/history"]');
      await layout();
      assert.equal(await evaluate("document.querySelectorAll('a[href^=\"/fiqh/nodes/\"]').length"),0);
      await activate('a[href="/dev/reference-triage/history#reference-1"]');
      await layout();
      await activate('a[href="/dev/editorial-workbench/history#references"]');
      await layout();
    });
    await check(`${width}: export cross-link and exact CRLF source packet`, async () => {
      await navigate("/dev/editorial-search");
      await activate('a[href="/dev/editorial-export"]');
      await layout();
      await activate('a[href="/dev/editorial-workbench/batch-synthetic-csv-1?packet=html"]');
      await layout();
      const href = await evaluate("document.querySelector('a[href*=\"packet=json\"]').getAttribute('href')");
      const response = await getText(href);
      assert.equal(response.status,200);
      const expected = contract.packets["batch-synthetic-csv-1"];
      assertPacket(JSON.parse(response.text),expected,expected.selection.revision);
    });
    await check(`${width}: missing-case and missing-revision recovery`, async () => {
      for (const root of ["editorial-queue","research-bridge","editorial-workbench"]) {
        await navigate(`/dev/${root}/fast8-missing-case`,404);
        await layout();
        await activate(`main a[href="/dev/${root}"]`);
        await layout();
      }
      await navigate("/dev/editorial-workbench/history?revision=999",404);
      assert.equal(await evaluate("document.querySelectorAll('#snapshot').length"),0);
      await activate('main a[href="/dev/editorial-workbench"]');
    });
  }
  await check("export bytes/hash and full revision identity", async () => {
    for (const [name,hash] of Object.entries(contract.files)) {
      const response = await getText("/dev/editorial-export/"+name);
      assert.equal(response.status,200);
      assert.equal(response.hash,hash);
      assert.equal(digest(response.text),hash);
      if (name === "report.json") {
        const entry = JSON.parse(response.text).cases.find(row=>row.packet.identity.case_key === "history");
        assertPacket(entry.packet,packet,packet.selection.revision);
      }
    }
  });
  await check("browser guard rejects writes and foreign origins before network", async () => {
    for (const method of ["POST","PUT","PATCH","DELETE"]) {
      const request = {method,url:origin+"/dev/editorial-workbench/history"};
      expectedProbe = request;
      assert.equal(await evaluate(`fetch(${quote(request.url)}, {method:${quote(method)}}).then(()=>false,()=>true)`),true);
      assertBlocked(blocked,request);
    }
    // Top-level navigation bypasses connect-src CSP, proving Fetch itself denies
    // a foreign-origin request. The .invalid destination is never transmitted.
    expectedProbe = {method:"GET",url:"http://fast8-foreign.invalid/probe"};
    await cdp.send("Page.navigate",{url:expectedProbe.url});
    await until(()=>blocked.some(item=>item.url === expectedProbe.url));
    assertBlocked(blocked,expectedProbe);
    expectedProbe = null;
  });
  if (contract.catalog.result === "READY") {
    await check("owned PostgreSQL research-to-source exact identity", async () => {
      for (const width of widths) {
        viewportWidth = width;
        await cdp.send("Emulation.setDeviceMetricsOverride",{width,height:900,deviceScaleFactor:1,mobile:width < 500});
        await navigate("/dev/research-bridge/intake-1");
        await layout();
        await activate('a[href="/fiqh/nodes/1?edition=7001"]');
        await until(()=>evaluate("!document.querySelector('#interactive-catalog').hidden && document.querySelector('#tree-region').getAttribute('aria-busy') === 'false'"));
        await layout();
        assert.equal(await evaluate("document.querySelector('#interactive-catalog').dataset.edition"),"7001");
        assert.ok((await evaluate("document.querySelector('#reference-content').textContent")).includes(contract.catalog.nodes[0].title));
        const response = await getText("/api/v1/fiqh/nodes/1?edition=7001");
        assert.equal(response.status,200);
        const data = JSON.parse(response.text);
        assert.deepEqual(data.edition,contract.catalog.edition);
        assert.deepEqual(data.node,contract.catalog.nodes[0]);
      }
    });
    report.catalog.result = "PASS";
  }
  await Promise.all([...pending]);
  assert.deepEqual(errors,[]);
  assert.deepEqual(unexpected,[]);
}
try {
  const socket = await browser.start();
  phase = "interactions";
  cdp = new CDP(socket,message => {
    if (message.method === "Page.loadEventFired") loads++;
    if (message.method === "Runtime.exceptionThrown") errors.push("RUNTIME_EXCEPTION");
    if (message.method === "Runtime.consoleAPICalled" && message.params.type === "error")
      errors.push("CONSOLE_ERROR");
    if (message.method === "Network.responseReceived") {
      const r = message.params.response;
      responses.set(r.url,r.status);
      if (r.status >= 400 && message.params.type !== "Document") errors.push("SUBRESOURCE_HTTP_ERROR");
    }
    if (message.method !== "Fetch.requestPaused") return;
    const {requestId,request} = message.params;
    const favicon = request.url === origin+"/favicon.ico" && request.method === "GET";
    const allowed = permitted(request,origin,contract.catalog.result === "READY");
    if (!allowed && !favicon) {
      blocked.push({method:request.method,url:request.url});
      if (!expectedProbe || expectedProbe.url !== request.url || expectedProbe.method !== request.method)
        unexpected.push("UNEXPECTED_BLOCKED_REQUEST");
    }
    const task = favicon ? cdp.send("Fetch.fulfillRequest",{requestId,responseCode:204}) :
      cdp.send(allowed ? "Fetch.continueRequest" : "Fetch.failRequest",
        allowed ? {requestId} : {requestId,errorReason:"BlockedByClient"});
    pending.add(task);
    task.then(()=>pending.delete(task),()=>{errors.push("INTERCEPTION_FAILED"); pending.delete(task);});
  });
  await browser.bounded(journey());
  report.browser = "PASS";
} catch (error) {
  report.browser = error.code === "RUN_DEADLINE_EXCEEDED" ? "FAIL" : failureResult(phase);
  // No browser stderr, local file paths, URLs or arbitrary exception payloads.
  report.failure = {check:current,code:error.code ?? "CONFORMANCE_FAILED"};
  if (phase === "interactions") report.checks.push({name:current,result:"FAIL"});
} finally {
  clearTimeout(timer);
  cdp?.close();
  report.cleanup = await browser.close();
  if (report.cleanup.result !== "PASS") report.browser = "FAIL";
  report.result = outcome(report.browser,report.catalog.result);
}
console.log(JSON.stringify(report));
process.exitCode = {PASS:0,FAIL:1,NOT_RUN:2}[report.result];
