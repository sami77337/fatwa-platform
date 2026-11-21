import {ROOT, FORMAT, COPIES, SHELL, MAX_COPIES, packetURL, validatePacket, readPacketResponse, reconcilePacket} from "./core.mjs";

const shellPaths = [ROOT, ...["app.mjs", "core.mjs", "offline.css", "manifest.webmanifest", "icon.svg", "icon-192.png", "icon-512.png"].map(name => ROOT + name)];
self.addEventListener("install", event => event.waitUntil((async () => {
  const cache = await caches.open(SHELL);
  for (const path of shellPaths) {
    const response = await fetch(path, {credentials: "omit", cache: "no-store"});
    if (!response.ok || response.headers.get("X-Offline-Asset") !== FORMAT) throw new Error("offline_shell_unavailable");
    await cache.put(path, response);
  }
  await self.skipWaiting();
})()));
self.addEventListener("activate", event => event.waitUntil(self.clients.claim()));
self.addEventListener("fetch", event => {
  const url = new URL(event.request.url);
  // Private routes, catalogs, packets and unselected material pages are never cached.
  if (event.request.method !== "GET" || url.origin !== self.location.origin || url.search || !shellPaths.includes(url.pathname)) return;
  event.respondWith((async () => {
    try { return await fetch(event.request); }
    catch { return (await caches.open(SHELL)).match(url.pathname); }
  })());
});
async function existing(cache, id) {
  const path = packetURL(id), response = await cache.match(path);
  if (!response) throw new Error("offline_copy_missing");
  try { return await validatePacket(await response.json()); }
  catch (error) { await cache.delete(path); throw error; }
}
async function dispatch(message) {
  if (!message || typeof message.command !== "string") throw new Error("offline_command_invalid");
  const cache = await caches.open(COPIES);
  if (message.command === "SAVE") {
    const path = packetURL(message.id);
    if (!(await cache.match(path)) && (await cache.keys()).length >= MAX_COPIES) throw new Error("offline_capacity");
    const value = await readPacketResponse(await fetch(path, {credentials: "omit", cache: "no-store", redirect: "error"}));
    if (value.material.version_id !== message.id) throw new Error("offline_copy_invalid");
    await cache.put(path, new Response(JSON.stringify(value), {headers: {"Content-Type": "application/json"}}));
    return {saved: value.material.version_id};
  }
  if (message.command === "READ") return existing(cache, message.id);
  if (message.command === "REMOVE") { await cache.delete(packetURL(message.id)); return {removed: true}; }
  if (message.command === "CLEAR") { await caches.delete(COPIES); return {removed: true}; }
  if (message.command === "LIST" || message.command === "SYNC") {
    const rows = [];
    for (const key of await cache.keys()) {
      const id = new URL(key.url).pathname.split("/").filter(Boolean).at(-1);
      try {
        let value = await existing(cache, id);
        if (message.command === "SYNC") {
          let response;
          try {
            response = await fetch(packetURL(id), {credentials: "omit", cache: "no-store", redirect: "error"});
          } catch { /* Network loss retains only the previously permitted, unexpired copy. */ }
          if (response && [400, 403, 404, 410].includes(response.status)) { await cache.delete(key); continue; }
          if (response?.ok) {
            try {
              const fresh = await readPacketResponse(response);
              value = await reconcilePacket(value, fresh);
              await cache.put(key, new Response(JSON.stringify(value), {headers: {"Content-Type": "application/json"}}));
            } catch { await cache.delete(key); continue; }
          }
        }
        rows.push({id, title: value.material.title, number: value.material.number, expires_at: value.expires_at});
      } catch { await cache.delete(key); }
    }
    return rows;
  }
  throw new Error("offline_command_invalid");
}
let operation = Promise.resolve();
self.addEventListener("message", event => {
  if (!event.ports[0] || !event.source || !event.source.url) return;
  const source = new URL(event.source.url);
  if (source.origin !== self.location.origin || !source.pathname.startsWith(ROOT)) return;
  operation = operation.catch(() => {}).then(() => dispatch(event.data));
  event.waitUntil(operation.then(result => event.ports[0].postMessage({ok: true, result}), () => event.ports[0].postMessage({ok: false, error: "offline_operation_unavailable"})));
});
