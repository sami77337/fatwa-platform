import assert from "node:assert/strict";

export function loopbackOrigin(value) {
  const url = new URL(value);
  assert.equal(url.protocol, "http:", "E6 accepts loopback HTTP only");
  assert.ok(["127.0.0.1", "[::1]"].includes(url.hostname), "E6 refuses non-literal loopback hosts");
  assert.equal(url.username + url.password + url.search + url.hash, "");
  assert.equal(url.pathname, "/");
  return url.origin;
}

export function permittedRequest(request, origin) {
  if (!["GET", "HEAD"].includes(request.method)) return false;
  if (request.url === "about:blank") return true;
  const url = new URL(request.url);
  return url.origin === origin && !/[.](mp4|mp3|webm|ogg|wav|m4a|m3u8)$/i.test(url.pathname);
}

export class CDP {
  constructor(socket, onEvent = () => {}) {
    this.socket = socket;
    this.pending = new Map();
    this.serial = 0;
    socket.addEventListener("message", ({data}) => {
      const message = JSON.parse(data);
      if (!message.id) { onEvent(message); return; }
      const item = this.pending.get(message.id);
      if (!item) return;
      this.pending.delete(message.id); clearTimeout(item.timer);
      if (message.error) item.reject(Error(message.error.message));
      else item.resolve(message.result);
    });
    socket.addEventListener("close", () => this.close());
  }
  send(method, params = {}) {
    return new Promise((resolve, reject) => {
      const id = ++this.serial;
      const timer = setTimeout(() => {
        this.pending.delete(id); reject(Error("CDP timeout: " + method));
      }, 10000);
      this.pending.set(id, {resolve, reject, timer});
      try { this.socket.send(JSON.stringify({id, method, params})); }
      catch (error) { clearTimeout(timer); this.pending.delete(id); reject(error); }
    });
  }
  async evaluate(expression) {
    const response = await this.send("Runtime.evaluate", {expression, awaitPromise: true, returnByValue: true});
    if (response.exceptionDetails) throw Error(response.exceptionDetails.text);
    return response.result.value;
  }
  close() {
    for (const item of this.pending.values()) { clearTimeout(item.timer); item.reject(Error("CDP closed")); }
    this.pending.clear();
  }
}
