import assert from "node:assert/strict";
import {test} from "node:test";
import {allowedRequest, aggregateResult, catalogIdentity} from "./policy.mjs";

test("read-only interception denies foreign origins, media, writes and unknown routes", () => {
  const origin = "http://127.0.0.1:8123";
  const request = (path, method = "GET") => ({url: origin + path, method});
  for (const path of ["/dev/editorial-workbench", "/dev/editorial-workbench/history?revision=7", "/dev/editorial-queue", "/dev/editorial-queue/history", "/dev/editorial-queue/style.css", "/fiqh", "/api/v1/fiqh/search?q=x", "/assets/reference/catalog.js", "/assets/django_htmx/htmx-2.min.js"])
    assert.equal(allowedRequest(request(path), origin), true, path);
  for (const item of [request("/fiqh", "POST"), request("/dev/editorial-workbench", "PATCH"), request("/dev/editorial-queue/history", "POST"), request("/dev/editorial-queue/history/approve"), request("/assets/django_htmx/other.js"), request("/admin"), request("/clip.mp4"), {url: "https://example.invalid/", method:"GET"}, {url:"http://127.0.0.1:8124/fiqh",method:"GET"}, {url:"file:///tmp/input",method:"GET"}])
    assert.equal(allowedRequest(item, origin), false, item.url);
});

test("partial execution never becomes PASS and an assertion failure takes precedence", () => {
  assert.equal(aggregateResult([{result:"PASS"}, {result:"NOT_RUN"}]), "NOT_RUN");
  assert.equal(aggregateResult([{result:"FAIL"}, {result:"NOT_RUN"}]), "FAIL");
  assert.equal(aggregateResult([{result:"PASS"}]), "PASS");
  assert.equal(aggregateResult([]), "NOT_RUN");
});

test("catalog refuses non-synthetic or mismatched inventories before browser navigation", () => {
  const edition = {work:{source_namespace:"wave7-synthetic-toc",source_book_id:"622"},heading_count:3,
    source_archive_sha256:"b".repeat(64),source_input_sha256:"a".repeat(64),edition_key:"wave7-synthetic-edition-v1"};
  assert.equal(catalogIdentity({items:[edition]}), true);
  for (const inventory of [{items:[]}, {items:[edition,edition]}, {items:[{...edition,heading_count:11397}]},
    {items:[{...edition,source_input_sha256:"c".repeat(64)}]}, {items:[{...edition,work:{source_namespace:"owner-source"}}]}])
    assert.equal(catalogIdentity(inventory), false);
});
