import test from 'node:test';
import assert from 'node:assert/strict';
import process from 'node:process';
import { execFile } from 'node:child_process';
import { fileURLToPath } from 'node:url';
const root=fileURLToPath(new URL('../../../',import.meta.url));
const run=(args:string[])=>new Promise<{code:number;stdout:string;stderr:string}>(resolve=>execFile(process.execPath,['quality/security/cli.ts',...args],{cwd:root,windowsHide:true,maxBuffer:1048576},(error,stdout,stderr)=>resolve({code:Number(error?.code??0),stdout,stderr})));
test('CLI documents local-only arguments without contacting a server',async()=>{
  const result=await run(['--help']);assert.equal(result.code,0);assert.ok(result.stdout.includes('--disposable-synthetic-target'));assert.equal(result.stderr,'');
});
test('CLI rejects external target origins and does not echo credentials',async()=>{
  for(const base of ['https://example.invalid','http://s4-secret@127.0.0.1:8000']) {
    const result=await run(['--base-url',base]);assert.equal(result.code,1);const body=JSON.parse(result.stdout);assert.equal(body.code,'LOCAL_TARGET');assert.ok(!result.stdout.includes('s4-secret'));
  }
});
test('CLI rejects ambiguous or missing configuration arguments',async()=>{
  for(const args of [['--base-url'],['--base-url','http://127.0.0.1','--base-url','http://127.0.0.1'],['--unexpected']]) {
    const result=await run(args);assert.equal(result.code,1);assert.equal(JSON.parse(result.stdout).code,'CLI_ARGUMENT');
  }
});

test('CLI rejects outputs outside S4 before probing a server',async()=>{
  for(const output of ['README.md','docs/coordination/probe.json','docs/security-review/evidence/../outside.json']) {
    const result=await run(['--output',output]);assert.equal(result.code,1);assert.equal(JSON.parse(result.stdout).code,'EVIDENCE_PATH');
  }
});
