import assert from "node:assert/strict";
import test from "node:test";
import vm from "node:vm";
import {focusCommand, navigationTrace, observation, packetSelector} from "./navigation_trace.mjs";

const origin="http://127.0.0.1:1234", route="/dev/editorial-workbench/batch-synthetic-csv-1";

test("packet and revision URLs remain distinguishable across a document redirect",()=>{
  const trace=navigationTrace(origin);
  for(const [method,params] of [
    ["Network.requestWillBeSent",{request:{url:origin+route+"?revision=1#snapshot"}}],
    ["Network.requestWillBeSent",{request:{url:origin+route+"?packet=html"},redirectResponse:{status:303}}],
    ["Network.responseReceived",{response:{url:origin+route+"?packet=html",status:200}}],
    ["Page.frameNavigated",{frame:{id:"f",loaderId:"l",url:origin+route+"?packet=html"}}],
  ]) trace.cdp({method,params:{requestId:"r",loaderId:"l",frameId:"f",type:"Document",...params}});
  assert.deepEqual(trace.report.events.map(e=>e.seq),[1,2,3,4]);
  const [first,redirect,response,frame]=trace.report.events;
  assert.equal(first.url,route+"?revision=1#snapshot"); assert.equal(redirect.url,route+"?packet=html");
  assert.equal(redirect.redirect_status,303); assert.equal(response.status,200);
  assert.equal(redirect.request,response.request); assert.equal(response.loader,frame.loader);
  assert.equal(response.frame,frame.frame); assert.equal(frame.top,true);
});

test("unrecognized route, query, credentials, headers, bodies and arbitrary IDs stay out of exported evidence",()=>{
  const trace=navigationTrace(origin);
  for(const url of [origin+"/private/SECRET?packet=html",origin+route+"?q=SECRET&revision=SECRET&packet=html#SECRET",
    origin.replace("http://","http://SECRET@")+route,"https://SECRET.example"+route]) {
    trace.cdp({method:"Network.requestWillBeSent",params:{type:"Document",request:{url,headers:{Authorization:"SECRET"},postData:"SECRET"}}});
    trace.dom("focus",{url,href:url,id:"SECRET",tag:"SECRET",ready:"SECRET"});
  }
  assert.ok(!JSON.stringify(trace.report).includes("SECRET"));
  assert.deepEqual(trace.report.events.filter(e=>e.event==="Network.requestWillBeSent").map(e=>e.url),
    ["[redacted]",route+"?packet=html","[redacted]","[redacted]"]);
});

test("failure capture preserves the focus mismatch and packet absence",()=>{
  const trace=navigationTrace(origin);
  const link={href:origin+route+"?packet=html",tagName:"A"};
  const section={tagName:"SECTION",id:"snapshot"};
  const document={readyState:"interactive",activeElement:section,querySelector(selector) {
    return selector===packetSelector ? link : selector==="#snapshot" ? section : null;
  }};
  const snapshot=()=>vm.runInNewContext(observation(packetSelector),{document, location:{href:origin+route+"?revision=1#snapshot"}});
  trace.dom("before_focus",snapshot());
  document.activeElement=link; trace.dom("after_focus",snapshot());
  document.activeElement=section; trace.dom("failure",snapshot());
  assert.deepEqual(trace.report.events.map(e=>e.focused),[false,true,false]);
  assert.equal(trace.report.failure_snapshot.packet,false);
  assert.equal(trace.report.failure_snapshot.id,"snapshot");
});

test("bounded event buffer retains final snapshot and records capture errors",()=>{
  const trace=navigationTrace(origin);
  for(let i=0;i<140;i++) trace.cdp({method:"Page.loadEventFired",params:{}});
  trace.cdp({method:"Network.requestWillBeSent",params:{type:"Document"}});
  trace.dom("before_focus",vm.runInNewContext(observation(packetSelector),{}));
  trace.dom("failure",{ready:"complete",packet:false});
  assert.equal(trace.report.events.length,128);
  assert.equal(trace.report.dropped,13); assert.equal(trace.report.capture_errors,2);
  assert.equal(trace.report.failure_snapshot.ready,"complete");
});

test("subframes and document load failures can be correlated without unrelated network events",()=>{
  const trace=navigationTrace(origin);
  trace.cdp({method:"Page.frameNavigated",params:{frame:{id:"sub",parentId:"top",loaderId:"l",url:origin+route}}});
  trace.cdp({method:"Network.loadingFailed",params:{type:"Document",requestId:"r",canceled:true,errorText:"SECRET"}});
  trace.cdp({method:"Page.navigatedWithinDocument",params:{frameId:"sub",url:origin+route+"#snapshot"}});
  trace.cdp({method:"Network.requestWillBeSent",params:{type:"Image",request:{url:origin+"/image"}}});
  trace.cdp({method:"DOM.documentUpdated"});
  const [sub,fail,hash]=trace.report.events;
  assert.equal(trace.report.events.length,3); assert.equal(sub.top,false); assert.equal(fail.request,"r");
  assert.equal(fail.canceled,true); assert.equal(hash.frame,sub.frame); assert.ok(!JSON.stringify(trace.report).includes("SECRET"));
});

test("instrumented keyboard setup focuses once and preserves original focus exceptions",()=>{
  const failure=Error("native focus failed");
  for(const traced of [true,false]) {
    let calls=0;
    const link={focus(){calls++;}};
    const context={document:{querySelector(){return link;}}}; // no location: diagnostics fail
    const states=vm.runInNewContext(focusCommand(packetSelector,traced),context);
    assert.equal(calls,1);
    if(traced) assert.deepEqual(Array.from(states),[null,null]);
    link.focus=()=>{throw failure;};
    assert.throws(()=>vm.runInNewContext(focusCommand(packetSelector,traced),context),error=>error===failure);
  }
});
