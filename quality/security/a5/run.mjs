// Independent runner. Writes evidence only under docs/dev/a5; no DB or Docker commands.
import { execFile } from 'node:child_process';
import { promisify } from 'node:util';
import { mkdir, readFile, writeFile } from 'node:fs/promises';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { createHash } from 'node:crypto';
const execute=promisify(execFile);
const root=fileURLToPath(new URL('../../../',import.meta.url));
const output=path.join(root,'docs/dev/a5'); await mkdir(output,{recursive:true});
const git=async args=>(await execute('git',args,{cwd:root,windowsHide:true})).stdout.trim();
const report={timestamp:new Date().toISOString(),head:await git(['rev-parse','HEAD']),
  branch:await git(['branch','--show-current']),working_tree_modified:Boolean(await git(['status','--porcelain=v1'])),node:process.version,
  scope:'INDEPENDENT_QA_ONLY',gates:'B_NOT_PASSED_C_D_E_HOLD',suites:[],
  direct_database_tests:'NOT_RUN',browser_execution:'NOT_RUN',source_archive_rehash:'NOT_RUN'};
for(const group of ['static','adapter','http']) {
  const args=['--test','--test-timeout=30000','--test-concurrency=1','--test-reporter=tap','quality/security/a5/'+group+'.test.mjs'];
  let stdout='',stderr='',exitCode=0;
  try {const task=execute(process.execPath,args,{cwd:root,windowsHide:true,
    timeout:90000,maxBuffer:8*1024*1024});
    task.child.stdout.on('data',bytes=>{for(const line of bytes.toString().split(/\r?\n/))
      if(line.startsWith('# Subtest:')) console.log(JSON.stringify({group,running:line.slice(11)}));});
    ({stdout,stderr}=await task);}
  catch(error) {stdout=error.stdout??'';stderr=error.stderr??'';exitCode=error.code??1;}
  await writeFile(path.join(output,group+'.tap'),stdout+'\n'+stderr);
  const number=key=>Number([...stdout.matchAll(new RegExp('^# '+key+' ([0-9]+)$','gm'))].at(-1)?.[1]??0);
  const suite={group,command:'node '+args.join(' '),exit_code:exitCode,tests:number('tests'),
    passed:number('pass'),failed:number('fail'),skipped:number('skipped'),cancelled:number('cancelled'),
    evidence:'docs/dev/a5/'+group+'.tap'};
  report.suites.push(suite); console.log(JSON.stringify(suite));
}
report.totals=Object.fromEntries(['tests','passed','failed','skipped','cancelled'].map(key=>
  [key,report.suites.reduce((n,s)=>n+s[key],0)]));
const baseline=JSON.parse(await readFile(path.join(output,'baseline.json'),'utf8'));
report.implementation_changes=[];
for(const [name,sha] of Object.entries(baseline.implementation_sha256)) {
  const current=createHash('sha256').update(await readFile(path.join(root,name))).digest('hex');
  if(current!==sha) report.implementation_changes.push(name);
}
const status=await git(['status','--porcelain=v1','-uall']);
const initial=new Set(baseline.initial_git_status.trim().split(/\r?\n/));
report.new_git_status_lines=status.split(/\r?\n/).filter(line=>!initial.has(line));
// baseline's trailing/leading whitespace is significant to porcelain; normalize only the first line.
report.ownership_violations=report.new_git_status_lines.filter(line=>
  !/^(?:quality\/|tests\/security\/|docs\/security-review\/|docs\/dev\/a5\/)/.test(line.slice(3)) &&
  !baseline.initial_git_status.split(/\r?\n/).includes(line));
await writeFile(path.join(output,'results.json'),JSON.stringify(report,null,2)+'\n');
console.log(JSON.stringify({totals:report.totals,implementation_changes:report.implementation_changes,
  ownership_violations:report.ownership_violations}));
process.exitCode=report.suites.some(s=>s.exit_code!==0)||report.implementation_changes.length||report.ownership_violations.length?1:0;
