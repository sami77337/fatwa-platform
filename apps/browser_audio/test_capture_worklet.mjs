import assert from "node:assert/strict";
import {readFileSync} from "node:fs";
import test from "node:test";
import vm from "node:vm";

const source = readFileSync(new URL("./static/browser_audio/worklet.js", import.meta.url), "utf8");
function capture(rate = 8000) {
  const messages = [];
  let Processor;
  vm.runInNewContext(source, {
    sampleRate: rate, Int16Array,
    AudioWorkletProcessor: class { constructor() { this.port = {postMessage: data => messages.push(data)}; } },
    registerProcessor: (_, value) => { Processor = value; },
  });
  const instance = new Processor();
  return {instance, messages, command: data => instance.port.onmessage({data}),
    process: samples => instance.process([[Float32Array.from(samples)]])};
}

test("paused intervals produce no samples and resumed capture preserves earlier PCM", () => {
  const c = capture();
  assert.equal(c.process([0.5, -0.5]), true);
  c.command("pause");
  assert.equal(c.messages.at(-1).state, "paused");
  const before = c.messages.length;
  for (let i = 0; i < 1000; i++) assert.equal(c.process([1, -1]), true);
  assert.equal(c.messages.length, before);
  c.command("resume");
  assert.equal(c.messages.at(-1).state, "recording");
  c.process([1, -1]);
  const pcm = c.messages.filter(m => m instanceof Int16Array).flatMap(m => [...m]);
  assert.deepEqual(pcm, [16384, -16384, 32767, -32768]);
});

test("multiple pauses cannot extend or reset the ten-second sample bound", () => {
  const c = capture();
  c.process(new Array(40000).fill(0.25));
  c.command("pause"); c.process(new Array(20000).fill(0.9)); c.command("resume");
  c.process(new Array(30000).fill(-0.25));
  c.command("pause"); c.command("resume");
  assert.equal(c.process(new Array(20000).fill(0.5)), false);
  assert.equal(c.process([1]), false);
  c.command("resume");
  assert.equal(c.process([1]), false);
  const chunks = c.messages.filter(m => m instanceof Int16Array);
  assert.deepEqual(chunks.map(m => m.length), [40000, 30000, 10000]);
  assert.equal(chunks.reduce((n, m) => n + m.length, 0), 80000);
});

test("unsupported sample rate and unexpected controls fail closed", () => {
  const wrong = capture(44100);
  wrong.command("resume");
  assert.equal(wrong.process([0.5]), false);
  assert.equal(wrong.messages.length, 0);
  const c = capture();
  c.command("untrusted");
  c.command("resume");
  assert.equal(c.process([0.5]), false);
  assert.equal(c.messages.length, 0);
});
