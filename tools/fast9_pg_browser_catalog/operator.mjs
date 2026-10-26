// Actual FAST8 integrated mount, domain services, protected browser and keyboard.
import assert from "node:assert/strict";
import {ProtectedBrowser, failureResult} from "../../tests/acceptance/fastbuild/startup.mjs";
import {CDP, loopbackOrigin} from "../../tests/acceptance/wave7/cdp.mjs";
import {dispatchKey} from "../../tests/acceptance/wave7/keyboard.mjs";
import {widths, assertViewport, assertBlocked, assertPacket, permitted as upstream} from "../fast8_browser_conformance/policy.mjs";
import {permitted as permit} from "./policy.mjs";

const origin = loopbackOrigin(process.argv[2]);
let input = "";
for await (const chunk of process.stdin) {
  input += chunk;
  assert.ok(input.length <= 1048576);
}
const contract = JSON.parse(input);
const permitted = (request,origin) => permit(request,origin,contract.catalog.result === "READY");
const report = {result:"NOT_RUN", browser:"NOT_RUN", checks:[]};
const browser = new ProtectedBrowser({executable:process.env.FATWA_FASTBUILD_BROWSER ??
  (process.platform === "win32" ? "C:/Program Files/Google/Chrome/Application/chrome.exe" : "/usr/bin/chromium")});
let cdp, loads = 0, phase = "browser-startup", probe = null, current = "startup";
const pending = new Set(), blocked = [], failures = [], responses = new Map();
const timer = setTimeout(() => browser.controller.abort(browser.error("RUN_DEADLINE_EXCEEDED")), 85000);
async function until(check) {
  const end = Date.now() + 8000;
  while (Date.now() < end) {
    browser.controller.signal.throwIfAborted();
    if (await check()) return;
    await new Promise(resolve => setTimeout(resolve, 25));
  }
  throw Error("CHECK_TIMEOUT");
}
const evaluate = expression => cdp.evaluate(expression);
async function loaded(before) {
  await until(() => loads > before);
  await until(() => evaluate("document.readyState === 'complete'"));
}
async function navigate(route) {
  const url = origin + route;
  assert.ok(permitted({method:"GET",url},origin));
  const before = loads;
  await cdp.send("Page.navigate",{url});
  await loaded(before);
  assert.equal(responses.get(url),200);
}
async function enter(selector) {
  const href = await evaluate(`document.querySelector(${JSON.stringify(selector)})?.href`);
  assert.ok(href && permitted({method:"GET",url:href},origin));
  await evaluate(`document.querySelector(${JSON.stringify(selector)}).focus()`);
  const before = loads;
  await dispatchKey(cdp,"Enter",13);
  await loaded(before);
  assert.equal(await evaluate("location.href"),href);
  assert.equal(responses.get(href.split("#")[0]),200);
}
async function layout(width) {
  assert.equal(await evaluate("document.documentElement.dir"),"rtl");
  assert.equal(await evaluate("document.documentElement.lang"),"ar");
  assertViewport(await evaluate("({inner:innerWidth,client:document.documentElement.clientWidth,scroll:document.documentElement.scrollWidth})"),width);
}
try {
  const socket = await browser.start();
  phase = "interactions";
  cdp = new CDP(socket,message => {
    if (message.method === "Page.loadEventFired") loads++;
    if (message.method === "Runtime.exceptionThrown") failures.push("RUNTIME_EXCEPTION");
    if (message.method === "Runtime.consoleAPICalled" && message.params.type === "error") failures.push("CONSOLE_ERROR");
    if (message.method === "Network.responseReceived") {
      responses.set(message.params.response.url,message.params.response.status);
      if (message.params.response.status >= 400) failures.push("HTTP_ERROR");
    }
    if (message.method !== "Fetch.requestPaused") return;
    const {request,requestId} = message.params;
    const favicon = request.url === origin+"/favicon.ico" && request.method === "GET";
    const allowed = permitted(request,origin);
    if (!allowed && !favicon) {
      blocked.push({method:request.method,url:request.url});
      if (!probe || probe.method !== request.method || probe.url !== request.url) failures.push("UNEXPECTED_REQUEST");
    }
    const task = favicon ? cdp.send("Fetch.fulfillRequest",{requestId,responseCode:204}) :
      cdp.send(allowed ? "Fetch.continueRequest" : "Fetch.failRequest",
        allowed ? {requestId} : {requestId,errorReason:"BlockedByClient"});
    pending.add(task);
    task.then(()=>pending.delete(task),()=>{pending.delete(task); failures.push("INTERCEPTION_FAILED");});
  });
  for (const domain of ["Page","Runtime","Network"]) await cdp.send(domain+".enable");
  await cdp.send("Fetch.enable",{patterns:[{urlPattern:"*"}]});
  const packet = contract.packets.history, rev = contract.search.revision;
  for (const width of widths) {
    current = `${width}: operator index and keyboard`;
    await cdp.send("Emulation.setDeviceMetricsOverride",{width,height:900,deviceScaleFactor:1,mobile:width < 500});
    await navigate("/dev/operator-navigation");
    await layout(width);
    await dispatchKey(cdp,"Tab",9);
    assert.equal(await evaluate("document.activeElement.getAttribute('href')"),"#main-content");
    await dispatchKey(cdp,"Enter",13);
    assert.equal(await evaluate("document.activeElement.id"),"main-content");
    current = `${width}: history revision link`;
    await enter('a[href="/dev/operator-navigation/history"]');
    await enter(`a[href="/dev/operator-navigation/history?revision=${rev}"]`);
    await layout(width);
    assert.equal(await evaluate("document.querySelector('[data-case]').dataset.revision"),String(rev));
    const hashes = await evaluate("[...document.querySelectorAll('[data-case] dd')].map(x=>x.textContent)");
    assert.deepEqual(hashes,[packet.source.input_sha256,packet.source.text_sha256]);
    current = `${width}: workbench revision packet`;
    await enter(`a[href="/dev/editorial-workbench/history?revision=${rev}#snapshot"]`);
    await layout(width);
    assert.equal(await evaluate("document.querySelector('#snapshot strong').textContent"),String(rev));
    const route = `/dev/editorial-workbench/history?revision=${rev}&packet=json`;
    assert.ok(upstream({method:"GET",url:origin+route},origin));
    const response = await evaluate(`fetch(${JSON.stringify(route)},{redirect:'error'}).then(async r=>({status:r.status,body:await r.json()}))`);
    assert.equal(response.status,200);
    assertPacket(response.body,packet,rev);
    // This operator-to-research link is case-level, never historical acceptance.
    current = `${width}: operator research connection`;
    const caseKey = contract.catalog.result === "READY" ? "intake-1" : "history";
    await navigate(`/dev/operator-navigation/${caseKey}`);
    await enter(`a[href="/dev/research-bridge/${caseKey}"]`);
    await layout(width);
    assert.equal(await evaluate("document.querySelectorAll('a[href=\"/fiqh/nodes/1?edition=7001\"]').length"),
      contract.catalog.result === "READY" ? 1 : 0);
    if (contract.catalog.result === "READY") {
      current = `${width}: operator to exact PostgreSQL source rows`;
      await enter('a[href="/fiqh/nodes/1?edition=7001"]');
      await until(()=>evaluate("!document.querySelector('#interactive-catalog').hidden && document.querySelector('#tree-region').getAttribute('aria-busy') === 'false'"));
      await layout(width);
      assert.equal(await evaluate("document.querySelector('#interactive-catalog').dataset.edition"),"7001");
      for (const node of contract.catalog.nodes) {
        const route = `/api/v1/fiqh/nodes/${node.id}?edition=7001`;
        assert.ok(permitted({method:"GET",url:origin+route},origin));
        const actual = await evaluate(`fetch(${JSON.stringify(route)},{redirect:'error'}).then(async r=>({status:r.status,body:await r.json()}))`);
        assert.equal(actual.status,200);
        assert.deepEqual(actual.body.edition,contract.catalog.edition);
        assert.deepEqual(actual.body.node,node);
      }
    }
    report.checks.push({width,result:"PASS"});
  }
  for (const method of ["POST","PUT","PATCH","DELETE"]) {
    current = `deny ${method}`;
    probe = {method,url:origin+"/dev/operator-navigation/history"};
    assert.equal(await evaluate(`fetch(${JSON.stringify(probe.url)},{method:${JSON.stringify(method)}}).then(()=>false,()=>true)`),true);
    assertBlocked(blocked,probe);
  }
  probe = {method:"GET",url:"http://fast9-foreign.invalid/probe"};
  current = "deny external";
  await cdp.send("Page.navigate",{url:probe.url});
  await until(()=>blocked.some(row=>row.url === probe.url));
  assertBlocked(blocked,probe);
  await Promise.all([...pending]);
  assert.deepEqual(failures,[]);
  report.browser = "PASS";
} catch (error) {
  report.browser = failureResult(phase);
  report.reason = error.code ?? "OPERATOR_CONFORMANCE_FAILED";
  report.check = current;
} finally {
  clearTimeout(timer);
  cdp?.close();
  report.cleanup = await browser.close();
  if (report.cleanup.result !== "PASS") report.browser = "FAIL";
  report.result = report.browser;
}
console.log(JSON.stringify(report));
process.exitCode = {PASS:0,FAIL:1,NOT_RUN:2}[report.result];
