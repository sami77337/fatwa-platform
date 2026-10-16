import test from "node:test";
import assert from "node:assert/strict";
import { createPreviewServer } from "../server.mjs";

test("local preview serves only public kit assets and denies mutations", async () => {
  const server = createPreviewServer();
  await new Promise(resolve => server.listen(0, "127.0.0.1", resolve));
  const base = "http://127.0.0.1:" + server.address().port;
  try {
    const html = await fetch(base);
    assert.equal(html.status, 200);
    assert.match(await html.text(), /lang="ar" dir="rtl"/);
    assert.match(html.headers.get("content-security-policy"), /frame-ancestors 'none'/);
    assert.equal(html.headers.get("x-content-type-options"), "nosniff");
    for (const method of ["POST", "PUT", "PATCH", "DELETE"]) {
      const result = await fetch(base, { method });
      assert.equal(result.status, 405);
      assert.equal(result.headers.get("allow"), "GET, HEAD");
    }
    for (const route of ["/AGENTS.md", "/tests/api.test.mjs", "/package.json", "/api/users", "/api/fatwas", "/%2e%2e/AGENTS.md"]) assert.equal((await fetch(base + route)).status, 404);
    assert.equal((await fetch(base + "/app.js", { method: "HEAD" })).status, 200);
  } finally { await new Promise(resolve => server.close(resolve)); }
});
