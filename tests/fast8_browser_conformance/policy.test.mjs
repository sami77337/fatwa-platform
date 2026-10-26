import assert from "node:assert/strict";
import {test} from "node:test";
import {permitted, digest, assertPacket, assertBlocked, assertViewport, outcome}
  from "../../tools/fast8_browser_conformance/policy.mjs";

const origin = "http://127.0.0.1:18080";
const request = (path,method="GET") => ({method,url:origin+path});
for (const method of ["POST","PUT","PATCH","DELETE","OPTIONS"]) {
  test(`refuse ${method} even on a guarded route`,()=>{
    assert.equal(permitted(request("/dev/editorial-queue",method),origin),false);
  });
}
test("foreign origins, credentials, invalid URL and scheme are refused",()=>{
  for (const url of ["http://127.0.0.1:18081/dev/editorial-queue",
    "http://localhost:18080/dev/editorial-queue","https://127.0.0.1:18080/dev/editorial-queue",
    "http://user@127.0.0.1:18080/dev/editorial-queue","https://example.invalid/dev/editorial-queue",
    "data:text/html,test","not a URL"]) {
    assert.equal(permitted({method:"GET",url},origin),false,url);
  }
});
test("no route-prefix escapes, stored reads, media or unexpected endpoints",()=>{
  for (const path of ["/dev/editorial-queue-evil","/dev/editorial-workbench/stored",
    "/dev/editorial-workbench/stored/1","/dev/editorial-workbench/workflow-audit","/dev/editorial-queue/%2fadmin",
    "/dev/editorial-queue/../../admin","/admin","/dev/editorial-queue/movie.mp4",
    "/api/v1/fiqh/search","/dev/editorial-queue/history/extra"]) {
    assert.equal(permitted(request(path),origin),false,path);
  }
});
test("catalog requires explicit preflight and known asset/node scope",()=>{
  for (const path of ["/fiqh/nodes/1?edition=7001","/assets/reference/catalog.js","/assets/django_htmx/htmx-2.min.js"]) {
    assert.equal(permitted(request(path),origin),false);
    assert.equal(permitted(request(path),origin,true),true);
  }
  assert.equal(permitted(request("/fiqh/nodes/999"),origin,true),false);
});
test("mobile acceptance rejects the default 980px viewport and overflow",()=>{
  for (const width of [375,320]) {
    assert.throws(()=>assertViewport({inner:980,client:980,scroll:980},width));
    assert.throws(()=>assertViewport({inner:width,client:width,scroll:width+1},width));
    assertViewport({inner:width,client:width,scroll:width},width);
  }
});
test("local guarded reads and historical query identity remain usable",()=>{
  for (const method of ["GET","HEAD"])
    assert.equal(permitted(request("/dev/editorial-workbench/history?revision=1&packet=json",method),origin),true);
});

function packet() {
  const text = "  سُؤَالٌ اصطناعي\r\ne\u0301  ";
  return {synthetic_only:true,identity:{case_key:"synthetic-one",batch_id:"synthetic-batch",row_ordinal:1},
    source:{text,input_text:text,text_sha256:digest(text),input_sha256:digest(text)},
    intake:{question:text},snapshots:[{number:1,reference_links:[{source_input_sha256:"b".repeat(64)}]}],
    persisted_review:{status:"not_loaded",events:null},selection:{revision:1}};
}
for (const [name,mutate] of [
  ["wrong case despite identical text",p=>p.identity.case_key="synthetic-two"],
  ["wrong row",p=>p.identity.row_ordinal=2],
  ["selected latest instead of requested history",p=>p.selection.revision=2],
  ["changed revision reference pin",p=>p.snapshots[0].reference_links[0].source_input_sha256="c".repeat(64)],
  ["CRLF normalization",p=>p.source.text=p.source.text.replaceAll("\r\n","\n")],
  ["Unicode normalization",p=>p.source.text=p.source.text.normalize("NFC")],
  ["invented persisted event",p=>p.persisted_review.events=[]],
]) {
  test(`exact identity rejects ${name}`,()=>{
    const expected=packet(),actual=structuredClone(expected);
    mutate(actual);
    assert.throws(()=>assertPacket(actual,expected,1));
  });
}
test("a false source digest fails even if both representations agree",()=>{
  const p=packet(); p.source.text_sha256="0".repeat(64);
  assert.throws(()=>assertPacket(p,p,1));
});
test("partial/not-run/unknown/failed evidence can never aggregate as PASS",()=>{
  for (const [browser,catalog,expected] of [["PASS","PASS","PASS"],
    ["PASS","NOT_RUN","NOT_RUN"],["NOT_RUN","PASS","NOT_RUN"],
    ["FAIL","NOT_RUN","FAIL"],["PASS","FAIL","FAIL"],["PASS","READY","NOT_RUN"]])
    assert.equal(outcome(browser,catalog),expected);
});
test("a failed fetch is not proof of guard denial without the exact event",()=>{
  const wanted=request("/dev/editorial-queue","POST");
  assert.throws(()=>assertBlocked([],wanted));
  assert.throws(()=>assertBlocked([request("/dev/editorial-queue","GET")],wanted));
  assert.throws(()=>assertBlocked([request("/dev/editorial-workbench","POST")],wanted));
  assertBlocked([wanted],wanted);
});
