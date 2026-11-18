// Synthetic loopback lifecycle observations, not Chrome/product acceptance.
import assert from "node:assert/strict";
import {access, mkdtemp, readFile, rm, writeFile} from "node:fs/promises";
import os from "node:os";
import path from "node:path";
import {setTimeout as delay} from "node:timers/promises";
import {fileURLToPath} from "node:url";
import {test} from "node:test";
import {ProtectedBrowser} from "./startup.mjs";
import {runResearchBrowser} from "../../research_bridge/startup.mjs";

const fixtureURL = new URL("./startup_fixture.mjs", import.meta.url);
const fixture = fileURLToPath(fixtureURL);
const researchFixture = fileURLToPath(new URL("../../research_bridge/startup_fixture.mjs", import.meta.url));
const phases = ["profile", "spawn", "port-file", "target-discovery", "websocket"];

function validateTrace(report) {
  const trace = report.startup.observations;
  assert.deepEqual(Object.keys(trace).sort(), ["clock", "phases", "scope", "supervisor", "websocket_events"]);
  assert.equal(trace.clock, "monotonic");
  assert.equal(trace.scope, "startup-only");
  assert.ok(trace.phases.length >= 1 && trace.phases.length <= 5);
  assert.deepEqual(trace.phases.map(row => row.phase), phases.slice(0, trace.phases.length));
  let previous = 0;
  for (const row of trace.phases) {
    assert.deepEqual(Object.keys(row).sort(), ["elapsed_ms", "phase", "remaining_ms", "started_ms"]);
    for (const key of ["elapsed_ms", "remaining_ms", "started_ms"])
      assert.ok(Number.isInteger(row[key]) && row[key] >= 0);
    assert.ok(row.started_ms >= previous);
    assert.ok(row.started_ms + row.elapsed_ms <= report.startup.elapsed_ms + 1);
    assert.ok(Math.abs(row.remaining_ms - Math.max(0,
      report.startup.timeout_ms - row.started_ms - row.elapsed_ms)) <= 2);
    previous = row.started_ms;
  }
  assert.deepEqual(Object.keys(trace.websocket_events).sort(), ["close_ms", "error_ms", "open_ms"]);
  for (const value of Object.values(trace.websocket_events))
    assert.ok(value === null || (Number.isInteger(value) && value >= 0 && value <= report.startup.elapsed_ms));
  assert.deepEqual(Object.keys(trace.supervisor).sort(), ["exited_ms", "spawned_ms", "state", "termination"]);
  assert.ok(["not-created", "created", "running", "spawn-failed", "exited"].includes(trace.supervisor.state));
  assert.ok([null, "zero", "nonzero", "signal", "unknown"].includes(trace.supervisor.termination));
  assert.ok(JSON.stringify(trace).length < 1500, "bounded fixed-field telemetry");
  return trace;
}

test("successful startup records phases without treating cleanup as startup events", async () => {
  let calls = 0;
  const report = await runResearchBrowser(async socket => {
    calls++;
    assert.equal(socket.readyState, WebSocket.OPEN);
  }, {executable:process.execPath, args:[fixture, "delayed-target"], startupTimeoutMs:2000});
  assert.equal(report.result, "PASS");
  assert.equal(calls, 1);
  assert.deepEqual(report.cleanup, {result:"PASS", errors:[]});
  const trace = validateTrace(report);
  assert.equal(trace.phases.length, 5);
  assert.ok(trace.websocket_events.open_ms !== null);
  assert.equal(trace.websocket_events.error_ms, null);
  assert.equal(trace.websocket_events.close_ms, null);
  assert.equal(trace.supervisor.state, "running");
  assert.equal(trace.supervisor.exited_ms, null);
  assert.equal(trace.supervisor.termination, null);
  const frozen = JSON.stringify(trace);
  await delay(40);
  assert.equal(JSON.stringify(trace), frozen, "late close/exit cannot rewrite startup evidence");
});

test("earlier port delay consumes the same deadline before websocket timeout; no journey retry", async () => {
  const temp = await mkdtemp(path.join(os.tmpdir(), "fatwa-v13-diagnostics-"));
  try {
    const peer = path.join(temp, "delayed-peer.mjs");
    await writeFile(peer, `import {setTimeout as delay} from "node:timers/promises";
await delay(400);
await import(${JSON.stringify(fixtureURL.href)});
`);
    let calls = 0;
    const report = await runResearchBrowser(() => { calls++; }, {
      executable:process.execPath, args:[peer, "socket-hang"], startupTimeoutMs:1600,
    });
    assert.equal(calls, 0);
    assert.equal(report.result, "NOT_RUN");
    assert.equal(report.failure.code, "BROWSER_STARTUP_TIMEOUT");
    assert.equal(report.failure.stage, "websocket");
    assert.deepEqual(report.cleanup, {result:"PASS", errors:[]});
    const trace = validateTrace(report);
    const port = trace.phases.find(row => row.phase === "port-file");
    const websocket = trace.phases.find(row => row.phase === "websocket");
    assert.ok(port.elapsed_ms >= 400);
    assert.ok(websocket.started_ms >= port.elapsed_ms);
    assert.ok(websocket.elapsed_ms < report.startup.elapsed_ms - 350);
    assert.equal(websocket.remaining_ms, 0);
    assert.ok(report.startup.elapsed_ms >= 1600 && report.startup.elapsed_ms < 4000);
    assert.deepEqual(trace.websocket_events, {open_ms:null, error_ms:null, close_ms:null});
    assert.equal(JSON.stringify(report).includes(temp), false);
  } finally { await rm(temp, {recursive:true, force:true}); }
});

test("fixed supervisor observations do not expose injected stderr, paths or credentials", async () => {
  const temp = await mkdtemp(path.join(os.tmpdir(), "fatwa-v13-diagnostics-"));
  try {
    const record = path.join(temp, "private-record.json");
    const report = await runResearchBrowser(() => assert.fail("no journey"), {
      executable:process.execPath, args:[researchFixture, "stderr-exit", record], startupTimeoutMs:2000,
    });
    assert.equal(report.result, "NOT_RUN");
    assert.equal(report.failure.code, "BROWSER_EXITED");
    assert.equal(report.failure.cause_code, 23);
    assert.deepEqual(report.diagnostics, {stderr_present:true, stderr_hints:["SANDBOX_UNAVAILABLE"]});
    const trace = validateTrace(report);
    assert.deepEqual(trace.phases.map(row => row.phase), ["profile", "spawn", "port-file"]);
    const launch = JSON.parse(await readFile(record, "utf8"));
    await assert.rejects(access(launch.profile), {code:"ENOENT"});
    const encoded = JSON.stringify(report);
    for (const forbidden of [temp, launch.profile, "private-value", "secret", "example.invalid", "/devtools/", "ws://"])
      assert.equal(encoded.includes(forbidden), false);
  } finally { await rm(temp, {recursive:true, force:true}); }
});

test("a failed supervisor spawn is observable without changing the failure contract", async () => {
  const report = await runResearchBrowser(() => assert.fail("no journey"), {
    executable:process.execPath, args:[fixture, "delayed-target"],
    python:path.join(os.tmpdir(), "fatwa-v13-nonexistent-supervisor-executable"),
  });
  assert.equal(report.result, "NOT_RUN");
  assert.equal(report.failure.code, "SUPERVISOR_SPAWN_FAILED");
  assert.equal(report.failure.stage, "port-file");
  assert.equal(report.failure.cause_code, "ENOENT");
  assert.deepEqual(report.cleanup, {result:"PASS", errors:[]});
  const trace = validateTrace(report);
  assert.equal(trace.supervisor.state, "spawn-failed");
  assert.equal(trace.supervisor.spawned_ms, null);
  assert.equal(trace.supervisor.exited_ms, null);
});

test("loopback handshake rejection records only the fixed websocket error observation", async () => {
  const temp = await mkdtemp(path.join(os.tmpdir(), "fatwa-v13-diagnostics-"));
  try {
    const peer = path.join(temp, "reject-peer.mjs");
    await writeFile(peer, `import {createServer} from "node:http";
import {writeFile} from "node:fs/promises";
import path from "node:path";
const profile = process.argv.find(v => v.startsWith("--user-data-dir=")).slice(16);
const server = createServer((request, response) => {
  response.setHeader("Content-Type", "application/json");
  response.end(JSON.stringify([{type:"page", webSocketDebuggerUrl:
    "ws://127.0.0.1:" + server.address().port + "/devtools/page/v13"}]));
});
server.on("upgrade", (request, socket) => {
  socket.end("HTTP/1.1 403 Forbidden\\r\\nX-Private-Diagnostic: secret-v13\\r\\nContent-Length: 0\\r\\n\\r\\n");
});
await new Promise(resolve => server.listen(0, "127.0.0.1", resolve));
await writeFile(path.join(profile, "DevToolsActivePort"), server.address().port + "\\n/devtools/browser/v13\\n");
`);
    const report = await runResearchBrowser(() => assert.fail("no journey"), {
      executable:process.execPath, args:[peer], startupTimeoutMs:2000,
    });
    assert.equal(report.result, "NOT_RUN");
    assert.equal(report.failure.code, "DEVTOOLS_WEBSOCKET_FAILED");
    assert.equal(report.failure.stage, "websocket");
    assert.deepEqual(report.cleanup, {result:"PASS", errors:[]});
    const trace = validateTrace(report);
    assert.equal(trace.websocket_events.open_ms, null);
    assert.ok(trace.websocket_events.error_ms !== null);
    assert.ok(trace.websocket_events.error_ms >= trace.phases.at(-1).started_ms);
    for (const secret of ["secret-v13", temp, "/devtools/page/", "ws://127.0.0.1:"])
      assert.equal(JSON.stringify(report).includes(secret), false);
  } finally { await rm(temp, {recursive:true, force:true}); }
});

test("supervisor exit classification snapshots a signal without PID or signal text", async () => {
  const browser = new ProtectedBrowser({executable:process.execPath,
    args:[fixture, "missing-port"], startupTimeoutMs:2000});
  const rejected = assert.rejects(browser.start(), {code:"SUPERVISOR_EXITED", stage:"port-file"});
  try {
    const deadline = performance.now() + 1500;
    while (browser.startupSupervisor?.state !== "running" && performance.now() < deadline) await delay(5);
    assert.equal(browser.startupSupervisor.state, "running");
    browser.child.kill("SIGKILL");
    await rejected;
    const trace = validateTrace({startup:{elapsed_ms:browser.elapsedMs,
      timeout_ms:browser.timeoutMs, observations:browser.startupDiagnostics}});
    assert.equal(trace.supervisor.state, "exited");
    assert.equal(trace.supervisor.termination, "signal");
    assert.ok(trace.supervisor.exited_ms !== null);
    assert.equal(JSON.stringify(trace).includes("SIGKILL"), false);
  } finally {
    assert.deepEqual(await browser.close(), {result:"PASS", errors:[]});
    await rejected;
  }
});
