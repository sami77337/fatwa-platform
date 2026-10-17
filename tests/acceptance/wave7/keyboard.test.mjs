import {test} from "node:test";
import assert from "node:assert/strict";
import {CDP} from "./cdp.mjs";
import {dispatchKey} from "./keyboard.mjs";

class RecordingSocket extends EventTarget {
  frames=[];
  send(data) {
    const frame=JSON.parse(data);this.frames.push(frame);
    queueMicrotask(()=>this.dispatchEvent(new MessageEvent("message",{
      data:JSON.stringify({id:frame.id,result:{}})
    })));
  }
}

test("Enter sends native form-submit text through actual CDP serialization", async()=>{
  const socket=new RecordingSocket(),cdp=new CDP(socket);
  await dispatchKey(cdp,"Enter",13);
  assert.deepEqual(socket.frames.map(frame=>frame.method),["Input.dispatchKeyEvent","Input.dispatchKeyEvent"]);
  assert.deepEqual(socket.frames.map(frame=>frame.params),[
    {type:"keyDown",key:"Enter",code:"Enter",windowsVirtualKeyCode:13,text:"\r",unmodifiedText:"\r"},
    {type:"keyUp",key:"Enter",code:"Enter",windowsVirtualKeyCode:13},
  ]);
  assert.equal(cdp.pending.size,0);
});

test("navigation keys never inject Enter text", async()=>{
  const socket=new RecordingSocket(),cdp=new CDP(socket);
  await dispatchKey(cdp,"ArrowLeft",37);
  assert.deepEqual(socket.frames.map(frame=>frame.params),[
    {type:"keyDown",key:"ArrowLeft",windowsVirtualKeyCode:37},
    {type:"keyUp",key:"ArrowLeft",windowsVirtualKeyCode:37},
  ]);
});
