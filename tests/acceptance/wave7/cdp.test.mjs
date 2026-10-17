import {test} from "node:test";
import assert from "node:assert/strict";
import {CDP, loopbackOrigin, permittedRequest} from "./cdp.mjs";

test("only literal loopback origins without credentials, query or path", () => {
  assert.equal(loopbackOrigin("http://127.0.0.1:8000"), "http://127.0.0.1:8000");
  assert.equal(loopbackOrigin("http://[::1]:8000/"), "http://[::1]:8000");
  for (const value of ["https://127.0.0.1", "http://example.invalid", "http://localhost", "http://127.0.0.1/foo", "http://x:y@127.0.0.1", "http://127.0.0.1?q=x"]) assert.throws(() => loopbackOrigin(value));
});
test("request policy refuses external origins, media paths and writes", () => {
  const origin = "http://127.0.0.1:8000";
  assert.ok(permittedRequest({url: origin + "/fiqh", method:"GET"}, origin));
  for (const request of [{url: origin, method:"POST"}, {url: "https://example.invalid/clip.mp4", method:"GET"}, {url: origin+"/clip.mp4?token=fabricated", method:"GET"}, {url: "http://127.0.0.1:9000", method:"GET"}]) assert.equal(permittedRequest(request, origin), false);
});

class Socket extends EventTarget {
  sent = [];
  send(value) { this.sent.push(JSON.parse(value)); }
  reply(value) { this.dispatchEvent(new MessageEvent("message", {data:JSON.stringify(value)})); }
}
test("CDP correlates out of order replies and keeps events separate", async () => {
  const socket = new Socket(), events = [], cdp = new CDP(socket, event => events.push(event));
  const first = cdp.send("first"), second = cdp.send("second");
  socket.reply({method:"Runtime.exceptionThrown", params:{}});
  socket.reply({id:2, result:{second:true}}); socket.reply({id:1, result:{first:true}});
  assert.deepEqual(await first, {first:true}); assert.deepEqual(await second, {second:true});
  assert.equal(events.length, 1); assert.equal(cdp.pending.size, 0);
});
test("CDP protocol errors fail assertions rather than succeed", async () => {
  const socket = new Socket(), cdp = new CDP(socket);
  const result = cdp.send("bad"); socket.reply({id:1, error:{message:"bad command"}});
  await assert.rejects(result, /bad command/);
});
test("runtime exceptions reject evaluate", async () => {
  const socket = new Socket(), cdp = new CDP(socket);
  const result = cdp.evaluate("bad()"); socket.reply({id:1, result:{exceptionDetails:{text:"ReferenceError"}}});
  await assert.rejects(result, /ReferenceError/);
});
test("closing transport rejects and clears every pending command", async () => {
  const socket = new Socket(), cdp = new CDP(socket);
  const result = cdp.send("pending"); socket.dispatchEvent(new Event("close"));
  await assert.rejects(result, /CDP closed/); assert.equal(cdp.pending.size, 0);
});
