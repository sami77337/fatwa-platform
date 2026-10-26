import assert from "node:assert/strict";
import {access, readFile} from "node:fs/promises";
import path from "node:path";
import {fileURLToPath} from "node:url";
import {test} from "node:test";
import {setTimeout as delay} from "node:timers/promises";
import {ProtectedBrowser, failureResult} from "./startup.mjs";

const fixture = fileURLToPath(new URL("./startup_fixture.mjs", import.meta.url));
const browser = mode => new ProtectedBrowser({executable:process.execPath, args:[fixture, mode], startupTimeoutMs:1500});

for (const [mode, code, stage] of [
  ["exit", "BROWSER_EXITED", "port-file"],
  ["missing-port", "BROWSER_STARTUP_TIMEOUT", "port-file"],
  ["unreadable-port", "DEVTOOLS_PORT_READ_FAILED", "port-file"],
  ["invalid-port", "DEVTOOLS_PORT_INVALID", "port-file"],
  ["http-hang", "BROWSER_STARTUP_TIMEOUT", "target-discovery"],
  ["no-target", "BROWSER_STARTUP_TIMEOUT", "target-discovery"],
  ["http-error", "DEVTOOLS_HTTP_FAILED", "target-discovery"],
  ["invalid-json", "DEVTOOLS_PROTOCOL_INVALID", "target-discovery"],
  ["foreign-socket", "DEVTOOLS_ENDPOINT_INVALID", "target-discovery"],
  ["socket-hang", "BROWSER_STARTUP_TIMEOUT", "websocket"],
]) test(`${mode} has a bounded, specific failure and removes its profile`, async () => {
  const session = browser(mode);
  const start = performance.now();
  try {
    await assert.rejects(session.start(), error => error.code === code && error.stage === stage);
  } finally {
    const cleanup = await session.close();
    assert.equal(cleanup.result, "PASS", JSON.stringify(cleanup));
  }
  assert.ok(performance.now() - start < 7000, "startup plus cleanup exceeded bound");
  await assert.rejects(access(session.profile), {code:"ENOENT"});
});

test("missing executable is spawn failure, never a DevTools timeout", async () => {
  const session = new ProtectedBrowser({executable:path.join(path.dirname(fixture), "missing-browser")});
  try { await assert.rejects(session.start(), {code:"BROWSER_SPAWN_FAILED", causeCode:"ENOENT"}); }
  finally { assert.equal((await session.close()).result, "PASS"); }
});

test("page target readiness is polled and concurrent profiles are isolated", async () => {
  const sessions = [browser("delayed-target"), browser("delayed-target")];
  try {
    const sockets = await Promise.all(sessions.map(session => session.start()));
    assert.ok(sockets.every(socket => socket.readyState === WebSocket.OPEN));
    assert.notEqual(sessions[0].profile, sessions[1].profile);
  } finally {
    for (const session of sessions) {
      assert.equal((await session.close()).result, "PASS");
      assert.equal((await session.close()).result, "PASS", "cleanup is idempotent");
      await assert.rejects(access(session.profile), {code:"ENOENT"});
    }
  }
});

test("abort interrupts startup and still permits tree cleanup", async () => {
  const controller = new AbortController();
  const session = new ProtectedBrowser({executable:process.execPath, args:[fixture, "missing-port"], signal:controller.signal});
  const timer = setTimeout(() => controller.abort(Error("runner deadline")), 300);
  try { await assert.rejects(session.start(), {code:"RUN_DEADLINE_EXCEEDED"}); }
  finally { clearTimeout(timer); assert.equal((await session.close()).result, "PASS"); }
});

test("Linux cleanup kills its group after the supervisor and all pipes close", {skip:process.platform !== "linux"}, async () => {
  const session = browser("closed-stderr");
  const failed = assert.rejects(session.start(), {code:"SUPERVISOR_EXITED"});
  let pid;
  const running = async () => {
    try { return (await readFile(`/proc/${pid}/stat`, "utf8")).split(") ")[1][0] !== "Z"; }
    catch (error) { if (error.code === "ENOENT") return false; throw error; }
  };
  try {
    const deadline = performance.now() + 1200;
    while (!pid && performance.now() < deadline) {
      if (session.profile) {
        try { pid = Number(await readFile(path.join(session.profile, "fixture.pid"), "utf8")); }
        catch (error) { if (error.code !== "ENOENT") throw error; }
      }
      if (!pid) await delay(20);
    }
    assert.ok(pid, "synthetic browser must close stderr before supervisor is killed");
    session.child.kill("SIGKILL");
    await failed;
    await session.closed; // No inherited pipe remains to signal a surviving child.
    assert.equal(await running(), true, "regression requires an orphaned browser");
    assert.equal((await session.close()).result, "PASS");
    const stoppedDeadline = performance.now() + 1000;
    while (await running() && performance.now() < stoppedDeadline) await delay(20);
    assert.equal(await running(), false, "browser survived a successful cleanup report");
    await assert.rejects(access(session.profile), {code:"ENOENT"});
  } finally {
    if (session.child?.pid) {
      try { process.kill(-session.child.pid, "SIGKILL"); }
      catch (error) { if (error.code !== "ESRCH") throw error; }
    }
    await session.close();
    await failed.catch(() => {});
  }
});

test("application failures and cleanup failures cannot become NOT_RUN or PASS", () => {
  assert.equal(failureResult("browser-startup", false), "NOT_RUN");
  assert.equal(failureResult("not-run", false), "NOT_RUN");
  assert.equal(failureResult("preflight", false), "FAIL");
  assert.equal(failureResult("interactions", false), "FAIL");
  assert.equal(failureResult("browser-startup", true), "FAIL");
});
