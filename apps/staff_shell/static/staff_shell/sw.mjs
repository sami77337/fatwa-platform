// Installation never caches a case, response, cookie, token or credential.
const SCOPE = "/casework/staff/";
const OFFLINE = `<!doctype html><html lang="ar" dir="rtl"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>الاتصال مطلوب لمكتب الشيخ</title></head><body><main><h1>يلزم الاتصال للعمل على القضايا</h1><p>لم تُحفظ بيانات القضية أو الجواب على هذا الجهاز. أعد الاتصال لتتحقق المنصة من صلاحيتك الحالية قبل عرض البيانات أو تنفيذ أي عملية.</p><p><a href="/casework/staff/">إعادة فتح المكتب عند الاتصال</a></p></main></body></html>`;
self.addEventListener("install", event => event.waitUntil(self.skipWaiting()));
self.addEventListener("activate", event => event.waitUntil(self.clients.claim()));
self.addEventListener("fetch", event => {
  const request = event.request, url = new URL(request.url);
  if (request.method !== "GET" || request.mode !== "navigate" || url.origin !== self.location.origin || !url.pathname.startsWith(SCOPE)) return;
  // Preserve the native navigation and its current credentials. The server
  // returns private/no-store responses; nothing is cached or replayed here.
  event.respondWith(fetch(request).catch(() => new Response(OFFLINE, {
    status: 503,
    headers: {"Content-Type": "text/html; charset=utf-8", "Cache-Control": "no-store",
      "Content-Security-Policy": "default-src 'none'; base-uri 'none'; frame-ancestors 'none'",
      "X-Content-Type-Options": "nosniff", "X-Staff-Offline": "network-required"}
  })));
});
