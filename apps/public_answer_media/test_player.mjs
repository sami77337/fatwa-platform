import assert from "node:assert/strict";
import test from "node:test";
import {initializeSegment} from "./static/public_answer_media/player.mjs";

class NativeMedia extends EventTarget {
  constructor(changes = {}) {
    super();
    this.dataset = {startMs:"1000", endMs:"2500"};
    this.ownerDocument = {baseURI:"http://127.0.0.1:8000/library-preview/recordings/11111111-1111-1111-1111-111111111111/segments/0/"};
    this.src = "/library-preview/recordings/11111111-1111-1111-1111-111111111111/audio/#t=1,2.5";
    this.status = {textContent:""};
    this.parentElement = {querySelector: () => this.status};
    this.readyState = 0; this.duration = NaN; this.seeking = false;
    this.paused = true; this.error = null; this.position = 0;
    this.assignments = []; this.blocked = false;
    Object.assign(this, changes);
  }
  getAttribute(name) { assert.equal(name, "src"); return this.src; }
  get currentTime() { return this.position; }
  set currentTime(value) {
    this.assignments.push(value);
    if (this.blocked) throw Error("metadata not ready to seek");
    this.position = value;
  }
  play() { throw Error("autoplay is prohibited"); }
  emit(name) { this.dispatchEvent(new Event(name)); }
}

test("waits for real metadata then initializes exact documented time without playback", () => {
  const audio = new NativeMedia(); initializeSegment(audio);
  assert.deepEqual(audio.assignments, []);
  audio.duration = 6; audio.readyState = 1; audio.emit("loadedmetadata");
  assert.equal(audio.currentTime, 1);
  audio.readyState = 4; audio.emit("canplay");
  assert.equal(audio.dataset.segmentState, "ready");
  assert.equal(audio.paused, true);
  assert.deepEqual(audio.assignments, [1]);
  audio.currentTime = 4; audio.emit("seeked"); audio.emit("canplay");
  assert.equal(audio.currentTime, 4, "finished initialization must preserve a later user seek");
});

test("repairs an ignored fragment on an already loaded original using server timing", () => {
  const audio = new NativeMedia({readyState:4, duration:6});
  audio.src = audio.src.replace("#t=1,2.5", "#t=4,5");
  initializeSegment(audio); audio.emit("seeked");
  assert.deepEqual(audio.assignments, [1]);
  assert.equal(audio.dataset.segmentState, "ready");
  assert.equal(audio.paused, true);
});

test("rejects malformed and out-of-duration timing without inventing an alternative", () => {
  for (const timing of [
    {startMs:"-1",endMs:"2500"}, {startMs:"1.5",endMs:"2500"},
    {startMs:"2500",endMs:"1000"}, {startMs:"1000",endMs:"7000"},
  ]) {
    const audio = new NativeMedia({readyState:4, duration:6, dataset:timing});
    initializeSegment(audio);
    assert.equal(audio.dataset.segmentState, "unavailable");
    assert.deepEqual(audio.assignments, []);
  }
});

test("requires a same-origin exact original route and never fetches a replacement", () => {
  for (const src of ["https://example.invalid/audio.wav", "javascript:void(0)", "/library-preview/other.wav", "/casework/staff/recording-transcripts/11111111-1111-1111-1111-111111111111/audio/?start=1"]) {
    const audio = new NativeMedia({readyState:4, duration:6, src});
    initializeSegment(audio);
    assert.equal(audio.dataset.segmentState, "unavailable");
    assert.deepEqual(audio.assignments, []);
  }
});

test("a not-yet-seekable native player may retry when its actual data becomes ready", () => {
  const audio = new NativeMedia({readyState:1, duration:6, blocked:true});
  initializeSegment(audio); assert.equal(audio.currentTime, 0);
  audio.blocked = false; audio.readyState = 4; audio.emit("loadeddata"); audio.emit("seeked");
  assert.equal(audio.currentTime, 1);
  assert.equal(audio.dataset.segmentState, "ready");
  assert.equal(audio.paused, true);
});

test("native failures stop initialization and retain an honest unavailable message", () => {
  const audio = new NativeMedia(); initializeSegment(audio);
  audio.error = {code:4}; audio.emit("error");
  audio.error = null; audio.duration = 6; audio.readyState = 4; audio.emit("loadedmetadata");
  assert.equal(audio.dataset.segmentState, "unavailable");
  assert.deepEqual(audio.assignments, []);
});

test("repeated native seek refusal stops at its finite attempt limit", () => {
  const audio = new NativeMedia({readyState:4, duration:6, blocked:true});
  initializeSegment(audio);
  for (let index = 0; index < 30; index += 1) audio.emit("canplay");
  assert.equal(audio.assignments.length, 20);
  assert.equal(audio.dataset.segmentState, "unavailable");
  assert.equal(audio.paused, true);
});
