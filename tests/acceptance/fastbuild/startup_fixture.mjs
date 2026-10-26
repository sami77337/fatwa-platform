// Synthetic DevTools peer for lifecycle negatives; never used for acceptance.
import {createServer} from "node:http";
import {createHash} from "node:crypto";
import {closeSync} from "node:fs";
import {mkdir, writeFile} from "node:fs/promises";
import path from "node:path";

const mode = process.argv[2];
const profile = process.argv.find(value => value.startsWith("--user-data-dir=")).split("=").slice(1).join("=");
const activePort = path.join(profile, "DevToolsActivePort");
if (mode === "exit") process.exit(23);
if (mode === "closed-stderr") {
  closeSync(2);
  await writeFile(path.join(profile, "fixture.pid"), String(process.pid));
  setInterval(() => {}, 1000);
} else if (mode === "missing-port") setInterval(() => {}, 1000);
else if (mode === "unreadable-port") {
  await mkdir(activePort);
  setInterval(() => {}, 1000);
} else if (mode === "invalid-port") {
  await writeFile(activePort, "65536\n/devtools/browser/synthetic\n");
  setInterval(() => {}, 1000);
} else {
  let requests = 0;
  const server = createServer((request, response) => {
    requests++;
    if (mode === "http-hang") return;
    if (mode === "http-error") { response.writeHead(500).end(); return; }
    if (mode === "invalid-json") { response.end("invalid"); return; }
    const port = server.address().port;
    const target = {type:"page", webSocketDebuggerUrl:`ws://127.0.0.1:${port}/devtools/page/synthetic`};
    if (mode === "foreign-socket") target.webSocketDebuggerUrl = "ws://example.invalid/devtools/page/synthetic";
    response.setHeader("Content-Type", "application/json");
    response.end(JSON.stringify(mode === "no-target" || (mode === "delayed-target" && requests < 3) ? [] : [target]));
  });
  server.on("upgrade", (request, socket) => {
    if (mode === "socket-hang") return;
    const accept = createHash("sha1").update(request.headers["sec-websocket-key"] + "258EAFA5-E914-47DA-95CA-C5AB0DC85B11").digest("base64");
    socket.write(`HTTP/1.1 101 Switching Protocols\r\nUpgrade: websocket\r\nConnection: Upgrade\r\nSec-WebSocket-Accept: ${accept}\r\n\r\n`);
    socket.on("error", () => {});
  });
  await new Promise(resolve => server.listen(0, "127.0.0.1", resolve));
  await writeFile(activePort, `${server.address().port}\n/devtools/browser/synthetic\n`);
}
