// Local preview only; no framework, private data or product endpoints.
import http from "node:http";
import { readFile } from "node:fs/promises";
import { fileURLToPath } from "node:url";
const root = new URL("./", import.meta.url);
const allowed = new Map([
  ["/", ["index.html", "text/html; charset=utf-8"]],
  ["/index.html", ["index.html", "text/html; charset=utf-8"]],
  ["/styles.css", ["styles.css", "text/css; charset=utf-8"]],
  ["/app.js", ["app.js", "text/javascript; charset=utf-8"]],
  ["/api.js", ["api.js", "text/javascript; charset=utf-8"]],
  ["/fixture.js", ["fixture.js", "text/javascript; charset=utf-8"]],
]);
export function createPreviewServer() {
  return http.createServer(async (request, response) => {
    response.setHeader("Cache-Control", "no-store");
    response.setHeader("X-Content-Type-Options", "nosniff");
    response.setHeader("Referrer-Policy", "no-referrer");
    response.setHeader("Content-Security-Policy", "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self'; connect-src 'self'; object-src 'none'; base-uri 'none'; form-action 'none'; frame-ancestors 'none'");
    if (!["GET", "HEAD"].includes(request.method)) {
      response.writeHead(405, { Allow: "GET, HEAD" }); response.end("Read-only preview"); return;
    }
    const resource = allowed.get(new URL(request.url, "http://127.0.0.1").pathname);
    if (!resource) { response.writeHead(404); response.end("Not found"); return; }
    try {
      const body = await readFile(new URL(resource[0], root));
      response.writeHead(200, { "Content-Type": resource[1] });
      response.end(request.method === "HEAD" ? undefined : body);
    } catch { response.writeHead(500); response.end("Preview unavailable"); }
  });
}
if (process.argv[1] === fileURLToPath(import.meta.url)) {
  const port = Number(process.env.FIQH_PREVIEW_PORT ?? 4173);
  if (!Number.isInteger(port) || port < 1 || port > 65535) throw new Error("Invalid preview port");
  createPreviewServer().listen(port, "127.0.0.1", () => console.log("Local S2 preview: http://127.0.0.1:" + port));
}
