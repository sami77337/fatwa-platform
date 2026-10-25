// Real Chrome, sandbox enabled. All inspected application traffic is local GET/HEAD.
import assert from "node:assert/strict";
import {spawn} from "node:child_process";
import {mkdtemp, readFile, rm} from "node:fs/promises";
import os from "node:os";
import path from "node:path";
import {CDP, loopbackOrigin} from "../acceptance/wave7/cdp.mjs";
import {dispatchKey} from "../acceptance/wave7/keyboard.mjs";

const origin = loopbackOrigin(process.argv[2]);
const temp = path.resolve(os.tmpdir());
const prefix = "fatwa-permission-lab-browser-";
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
  throw Error("Permission laboratory browser check timed out");
}
const watchdog = setTimeout(() => { socket?.close(); browser.kill(); }, 100000);
try {
  let port;
  await until(async () => {
    if (launchError) throw launchError;
    try { port = Number((await readFile(path.join(profile, "DevToolsActivePort"), "utf8")).split("\n")[0]); return !!port; }
    catch { return false; }
  });
  const tabs = await fetch(`http://127.0.0.1:${port}/json/list`).then(response => response.json());
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
        (favicon || ["/dev/permission-lab", "/dev/editorial-dashboard"].some(
          route => url.pathname === route || url.pathname === route + "/style.css"));
      requests.push({method: request.method, path: url.pathname});
      if (!allowed) violations.push(request.url);
      // Suppress only Chrome's automatic favicon probe; the app has no such route.
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
  async function selectWithKeyboard(id, value) {
    const options = await evaluate(`Array.from(document.getElementById(${JSON.stringify(id)}).options, option => ({value: option.value, disabled: option.disabled}))`);
    const enabled = options.filter(option => !option.disabled).map(option => option.value);
    const index = enabled.indexOf(value);
    assert.ok(index >= 0, `Missing ${id} option ${value}`);
    await evaluate(`document.getElementById(${JSON.stringify(id)}).focus()`);
    await dispatchKey(cdp, "Home", 36);
    for (let step = 0; step < index; step++) await dispatchKey(cdp, "ArrowDown", 40);
    assert.equal(await evaluate(`document.getElementById(${JSON.stringify(id)}).value`), value);
  }
  async function submitSelection(resource) {
    await selectWithKeyboard("actor", "MUFTI");
    await selectWithKeyboard("action", "synthetic::answer.create");
    await selectWithKeyboard("resource", resource);
    await dispatchKey(cdp, "Tab", 9);
    assert.equal(await evaluate("document.activeElement.matches('button[type=submit]')"), true);
    const before = loads;
    await dispatchKey(cdp, "Enter", 13);
    await until(() => loads > before);
    await until(() => evaluate("document.readyState === 'complete'"));
    assert.deepEqual(await evaluate("Object.fromEntries(new URL(location.href).searchParams)"), {
      actor: "MUFTI", action: "synthetic::answer.create", resource,
    });
    assert.deepEqual(await evaluate("Array.from(document.querySelectorAll('#decision .selection dd bdi'), node => node.textContent)"),
      ["MUFTI", "synthetic::answer.create", resource]);
    assert.ok(await evaluate("document.querySelector('#decision h2').textContent.includes('DENY')"));
  }
  for (const width of [1280, 375, 320]) {
    await cdp.send("Emulation.setDeviceMetricsOverride", {width, height: 900,
      deviceScaleFactor: 1, mobile: width < 500});
    await navigate("/dev/permission-lab");
    assert.equal(await evaluate("document.documentElement.dir"), "rtl");
    assert.equal(await evaluate("document.documentElement.lang"), "ar");
    assert.equal(await evaluate("document.querySelectorAll('script,iframe,video,audio').length"), 0);
    assert.equal(await evaluate("document.querySelector('form').method"), "get");
    assert.equal(await evaluate("document.querySelector('#decision')"), null);
    await noOverflow();
    // Real keyboard activation of the skip link moves focus into main.
    await evaluate("document.querySelector('.skip-link').focus()");
    assert.equal(await evaluate("document.activeElement.getAttribute('href')"), "#main-content");
    await dispatchKey(cdp, "Enter", 13);
    assert.equal(await evaluate("document.activeElement.id"), "main-content");
    await submitSelection("synthetic::answer");
    assert.ok(await evaluate("document.querySelector('#decision').textContent.includes('POLICY_PENDING')"));
    assert.ok(await evaluate("document.body.textContent.includes('NOT_DEPLOYED')"));
    await noOverflow();
  }
  await submitSelection("synthetic::catalog");
  assert.ok(await evaluate("document.querySelector('#decision').textContent.includes('ACTION_RESOURCE_MISMATCH')"));
  await noOverflow();
  const before = loads;
  await evaluate("document.querySelector('header a[href=\"/dev/editorial-dashboard\"]').click()");
  await until(() => loads > before);
  assert.equal(await evaluate("location.pathname"), "/dev/editorial-dashboard");
  assert.ok(await evaluate("document.querySelector('h1').textContent.includes('لوحة المتابعة')"));
  assert.equal(await evaluate("fetch('/dev/permission-lab', {method:'HEAD'}).then(response=>response.status)"), 200);
  await Promise.all([...pending]);
  assert.deepEqual(errors, []);
  assert.deepEqual(violations, []);
  assert.deepEqual(failedResponses, []);
  assert.ok(requests.some(request => request.path === "/dev/permission-lab/style.css"));
  console.log(JSON.stringify({result: "PASS", checks: ["1280/375/320px RTL without overflow",
    "actual keyboard dropdown submission and exact triple", "DENY plus POLICY_PENDING",
    "wrong-resource ACTION_RESOURCE_MISMATCH", "keyboard skip link", "dashboard return link",
    "GET/HEAD local only", "no console/runtime/network/HTTP errors"]}));
} finally {
  clearTimeout(watchdog); socket?.close(); cdp?.close();
  const ended = new Promise(resolve => browser.once("exit", resolve));
  if (browser.exitCode === null && !launchError) { browser.kill(); await ended; }
  const target = path.resolve(profile);
  assert.equal(path.dirname(target), temp);
  assert.ok(path.basename(target).startsWith(prefix));
  await rm(target, {recursive: true, force: true, maxRetries: 5, retryDelay: 100});
}
