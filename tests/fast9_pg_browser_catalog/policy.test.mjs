import assert from "node:assert/strict";
import test from "node:test";
import {permitted} from "../../tools/fast9_pg_browser_catalog/policy.mjs";

const origin = "http://127.0.0.1:45678";
test("actual operator routes allow bounded same-origin reads", () => {
  for (const method of ["GET","HEAD"])
    for (const route of ["", "/history?revision=1", "/style.css"])
      assert.equal(permitted({method,url:origin+"/dev/operator-navigation"+route},origin),true);
});
test("write verbs, foreign origins and credentials denied", () => {
  for (const method of ["POST","PUT","PATCH","DELETE","OPTIONS","TRACE","CONNECT"])
    assert.equal(permitted({method,url:origin+"/dev/operator-navigation"},origin),false);
  for (const url of ["http://foreign.invalid/dev/operator-navigation",
    "http://user@127.0.0.1:45678/dev/operator-navigation", "file:///dev/operator-navigation",
    "http://127.0.0.1:45679/dev/operator-navigation"])
    assert.equal(permitted({method:"GET",url},origin),false);
});
test("encoded and unjoined catalog/workflow destinations denied", () => {
  for (const route of ["/dev/operator-navigation/%68istory", "/dev/operator-navigation/history/extra",
    "/api/v1/fiqh/books", "/dev/editorial-queue/stored", "/fiqh", "/dev/admin"])
    assert.equal(permitted({method:"GET",url:origin+route},origin),false);
});
