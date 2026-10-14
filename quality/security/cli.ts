import { readFile, mkdir, writeFile, realpath, lstat, open } from 'node:fs/promises';
import { fileURLToPath } from 'node:url';
import path from 'node:path';
import process from 'node:process';
import { createHash, randomUUID } from 'node:crypto';
import { execFile } from 'node:child_process';
import { check, ContractError, validateFixture, validateProfile } from '../api_contract/catalog.ts';
import { createTransport, localOrigin } from './transport.ts';
import { runSuite } from './suite.ts';
const root=fileURLToPath(new URL('../../',import.meta.url));
const allowedOutput=['quality/security/evidence/','docs/security-review/evidence/'];
async function ownedFile(relative: string,write=false): Promise<string> {
  check(!path.isAbsolute(relative) && !relative.includes('\\') && !relative.split('/').includes('..') && allowedOutput.some(prefix=>relative.startsWith(prefix)), 'EVIDENCE_PATH','Evidence and test logs must be in S4-owned evidence directories.');
  const destination=path.resolve(root,relative);
  if(write) await mkdir(path.dirname(destination),{recursive:true});
  const actual=await realpath(write?path.dirname(destination):destination);
  check(allowedOutput.some(prefix=>{const boundary=path.resolve(root,prefix)+path.sep;return actual===boundary.slice(0,-1)||actual.startsWith(boundary);}), 'EVIDENCE_PATH','Evidence symlinks must remain within an owned evidence directory.');
  if(write) {
    try { check(!(await lstat(destination)).isSymbolicLink(),'EVIDENCE_PATH','An evidence output cannot be a symlink.'); } catch(error) { if(error.code!=='ENOENT') throw error; }
  }
  return destination;
}
async function boundedFile(filename: string): Promise<Buffer> {
  const handle=await open(filename,'r');
  try {
    check((await handle.stat()).size<=1048576,'INPUT_LIMIT','Test input exceeds the byte limit.');
    const data=await handle.readFile();check(data.byteLength<=1048576,'INPUT_LIMIT','Test input exceeded the byte limit while reading.');return data;
  } finally { await handle.close(); }
}
async function jsonFile(filename: string): Promise<{data: unknown; sha256: string}> {
  const data=await boundedFile(filename);
  return {data:JSON.parse(data.toString('utf8')),sha256:createHash('sha256').update(data).digest('hex')};
}
async function harnessHash(): Promise<string> {
  const digest=createHash('sha256');
  for(const file of ['quality/api_contract/catalog.ts','quality/security/cli.ts','quality/security/oracle.ts','quality/security/suite.ts','quality/security/transport.ts']) digest.update(file).update('\0').update(await readFile(path.join(root,file))).update('\0');
  return digest.digest('hex');
}
async function gitValue(args: string[],pattern: RegExp): Promise<string> {
  return new Promise(resolve=>execFile('git',args,{cwd:root,windowsHide:true,maxBuffer:4096},(error,stdout)=>{const value=stdout?.trim();resolve(!error&&pattern.test(value)?value:'UNKNOWN');}));
}
async function main(): Promise<void> {
  const values: Record<string,string>={}; let mutations=false;
  for(let i=2;i<process.argv.length;i++) {
    const key=process.argv[i];
    if(key==='--disposable-synthetic-target') { check(!mutations,'CLI_ARGUMENT','Duplicate flag.'); mutations=true; continue; }
    if(key==='--help') { console.log('node quality/security/cli.ts [--base-url http://127.0.0.1:8000] [--profile quality/api_contract/proposed-profile.json] [--fixture quality/api_contract/synthetic-catalog.json] [--disposable-synthetic-target] [--log-file quality/security/evidence/test-only.log] [--output docs/security-review/evidence/local-probe.json]'); return; }
    check(['--base-url','--profile','--fixture','--log-file','--output'].includes(key) && values[key]===undefined && process.argv[i+1]!==undefined && !process.argv[i+1].startsWith('--'),'CLI_ARGUMENT','Invalid, missing or duplicate CLI argument.'); values[key]=process.argv[++i];
  }
  const outputFile=values['--output']?await ownedFile(values['--output'],true):undefined;
  if(values['--log-file']) { const logFile=await ownedFile(values['--log-file']);check(logFile!==outputFile,'EVIDENCE_PATH','Input log and output report must be distinct.'); }
  const base=localOrigin(values['--base-url'] ?? 'http://127.0.0.1:8000').origin;
  const [profileInput,fixtureInput,revision,branch,harnessSha]=await Promise.all([
    jsonFile(path.resolve(root,values['--profile']??'quality/api_contract/proposed-profile.json')),
    jsonFile(path.resolve(root,values['--fixture']??'quality/api_contract/synthetic-catalog.json')),
    gitValue(['rev-parse','HEAD'],/^[a-f0-9]{40}$/),gitValue(['branch','--show-current'],/^[a-zA-Z0-9_./-]+$/),harnessHash()
  ]);
  validateProfile(profileInput.data); validateFixture(fixtureInput.data);
  const profile=profileInput.data; const fixture=fixtureInput.data;
  const runMarker='S4-QA-'+randomUUID(); let logSha: string | null=null;
  const readLog=values['--log-file'] ? async()=>{
    const filename=await ownedFile(values['--log-file']); const data=await boundedFile(filename);
    logSha=createHash('sha256').update(data).digest('hex'); return data.toString('utf8');
  }:undefined;
  const started=Date.now();
  const result=await runSuite({fixture,profile,base,transport:createTransport(base,profile.timeout_ms,profile.max_response_bytes),enableMutations:mutations,readLog,runMarker});
  const report={schema_version:1,generated_at:new Date().toISOString(),revision,branch,node_version:process.version,base_url:base,
    harness_sha256:harnessSha,fixture_identity:fixture.identity,fixture_sha256:fixtureInput.sha256,profile_identity:profile.identity,profile_sha256:profileInput.sha256,
    run_marker:runMarker,log_sha256:logSha,mutating_probes_enabled:mutations,duration_ms:Date.now()-started,
    safety_state:'NOT_DEPLOYED / GATES_HOLD',gate_b:'NOT_PASSED',gates_c_d_e:'HOLD',phase01:'BLOCKED',...result};
  const output=JSON.stringify(report,null,2)+'\n';
  if(outputFile) await writeFile(outputFile,output,'utf8');
  console.log(output.trimEnd());
  process.exitCode=result.status==='PASS'?0:result.status==='FAIL'?1:2;
}
main().catch(error=>{
  console.log(JSON.stringify({schema_version:1,status:'CONFIG_OR_HARNESS_ERROR',scope:'SYNTHETIC_DEVELOPMENT_ONLY',code:error instanceof ContractError?error.code:'INPUT_OR_HARNESS_ERROR',safety_state:'NOT_DEPLOYED / GATES_HOLD'},null,2));process.exitCode=1;
});
