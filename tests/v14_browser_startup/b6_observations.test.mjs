import assert from "node:assert/strict";
import test from "node:test";
import {B6StartupObservations} from "./b6_observations.mjs";

test("one launch's phases retain their own durations without a new deadline", () => {
  let now = 100;
  const recorder = new B6StartupObservations({clock:() => now});
  recorder.phase("spawn"); now += 3; recorder.event("spawned");
  recorder.phase("port-file"); now += 12001; recorder.event("port-missing");
  const report = recorder.snapshot("BLOCKED");
  assert.deepEqual(report.phases, [
    {phase:"spawn", started_ms:0, elapsed_ms:3},
    {phase:"port-file", started_ms:3, elapsed_ms:12001},
  ]);
  assert.equal(report.port_poll_limit_ms, 12000);
  assert.equal(report.elapsed_ms, 12004);
  assert.equal(report.root_cause, "ROOT_CAUSE_UNKNOWN");
  assert.equal(report.events["websocket-open"].first_ms, null);
});

test("cleanup and caller mutation cannot contaminate a frozen startup snapshot", () => {
  const recorder = new B6StartupObservations({clock:() => 7});
  for (const phase of ["spawn", "port-file", "target-discovery", "websocket"]) recorder.phase(phase);
  recorder.event("websocket-open");
  const first = recorder.snapshot("READY");
  first.events["process-exit"].count = 99;
  first.phases.push({phase:"private-path"});
  recorder.event("process-exit"); recorder.phase("spawn");
  const second = recorder.snapshot("BLOCKED");
  assert.equal(second.events["process-exit"].count, 0);
  assert.equal(second.result, "READY");
  assert.equal(second.phases.length, 4);
});

test("unknown labels and sensitive values never enter output; counts are bounded", () => {
  const recorder = new B6StartupObservations({clock:() => 0});
  for (const secret of ["https://secret.invalid/?token=private", "__proto__", "constructor", {}, null, undefined]) {
    recorder.phase(secret); recorder.event(secret);
  }
  for (let i = 0; i < 11000; i++) recorder.event("port-read-error");
  const report = recorder.snapshot("secret-error-message");
  assert.equal(report.result, "UNKNOWN");
  assert.equal(report.events["port-read-error"].count, 10000);
  assert.deepEqual(report.phases, []);
  assert.doesNotMatch(JSON.stringify(report), /secret|private|__proto__|constructor/);
});

test("broken clock is unknown, never an invented zero or a launch exception", () => {
  const recorder = new B6StartupObservations({clock:() => { throw Error("private"); }});
  recorder.phase("spawn"); recorder.event("spawn-error");
  const report = recorder.snapshot("BLOCKED");
  assert.equal(report.elapsed_ms, null);
  assert.equal(report.phases[0].elapsed_ms, null);
  assert.equal(report.events["spawn-error"].first_ms, null);
});

test("zero is measured and huge/nonfinite timing is bounded or unknown", () => {
  for (const [finish, expected] of [[0, 0], [Infinity, null], [NaN, null], [1e20, 600000], [-10, 0]]) {
    let now = 0;
    const recorder = new B6StartupObservations({clock:() => now});
    recorder.phase("spawn"); now = finish;
    assert.equal(recorder.snapshot("BLOCKED").elapsed_ms, expected);
  }
});

test("duplicate or out-of-order phases cannot grow storage or relabel a wait", () => {
  const recorder = new B6StartupObservations({clock:() => 0});
  recorder.phase("websocket"); recorder.phase("spawn");
  for (let i = 0; i < 10000; i++) recorder.phase("spawn");
  recorder.phase("port-file");
  assert.deepEqual(recorder.snapshot("BLOCKED").phases.map(p => p.phase), ["spawn", "port-file"]);
});
