import http from 'node:http';
import https from 'node:https';
import { check, ContractError } from '../api_contract/catalog.ts';
export type Request = { method: string; path: string; headers?: Record<string,string>; body?: string };
export type Response = { status: number; headers: Record<string,string>; body: string };
export type Transport = (request: Request) => Promise<Response>;
export function localOrigin(base: string): URL {
  let url: URL;
  try { url = new URL(base); } catch { throw new ContractError('LOCAL_TARGET','Expected a local origin.'); }
  check(['http:','https:'].includes(url.protocol) && ['127.0.0.1','[::1]','localhost'].includes(url.hostname), 'LOCAL_TARGET', 'Only explicit loopback hosts are accepted.');
  check(!url.username && !url.password && !url.search && !url.hash && url.pathname === '/', 'LOCAL_TARGET', 'Use an origin without credentials, paths, queries or fragments.');
  return url;
}
export function requestUrl(origin: URL, relative: string): URL {
  check(relative.startsWith('/') && !relative.startsWith('//') && !relative.includes('\\') && !/[\u0000-\u0020\u007f]/u.test(relative), 'REQUEST_PATH', 'Request must use a safe local absolute path.');
  const url = new URL(relative,origin);
  check(url.origin === origin.origin && !url.username && !url.password && !url.hash, 'REQUEST_PATH', 'Cross-origin requests and fragments are prohibited.');
  return url;
}
export function createTransport(base: string, timeoutMs: number, maxBytes: number): Transport {
  const origin = localOrigin(base);
  return async (input: Request) => {
    const url = requestUrl(origin,input.path);
    check(['GET','HEAD','POST','PUT','PATCH','DELETE','OPTIONS'].includes(input.method), 'REQUEST_METHOD', 'Unsupported probe method.');
    const headers: Record<string,string> = { accept:'application/json, text/html', 'user-agent':'S4-local-synthetic-QA/1', ...input.headers };
    for (const key of Object.keys(headers)) check(!['authorization','cookie','host','proxy-authorization'].includes(key.toLowerCase()), 'REQUEST_CREDENTIALS', 'Credentials and host overrides are prohibited.');
    if (input.body !== undefined) { headers['content-type']='application/json'; headers['content-length']=String(Buffer.byteLength(input.body)); }
    // Pin localhost to loopback rather than relying on DNS or proxy environment variables.
    const hostname = origin.hostname === '[::1]' ? '::1' : '127.0.0.1';
    const client = origin.protocol === 'https:' ? https : http;
    return await new Promise<Response>((resolve,reject) => {
      let settled = false;
      const finish = (error: Error | null, result?: Response) => { if(settled) return; settled=true; clearTimeout(timer); if(error) reject(error); else resolve(result); };
      const req = client.request({protocol:origin.protocol,hostname,port:origin.port || undefined,path:url.pathname+url.search,method:input.method,headers:{...headers,host:origin.host},agent:false,maxHeaderSize:16384}, res => {
        const chunks: Buffer[] = []; let length=0;
        res.on('data',chunk=>{
          length+=chunk.length;
          if(length>maxBytes) { const error=new ContractError('RESPONSE_LIMIT','Response exceeded the byte limit.'); finish(error); req.destroy(); res.destroy(); }
          else chunks.push(chunk);
        });
        res.on('aborted',()=>finish(new ContractError('RESPONSE_ABORTED','Response ended prematurely.')));
        res.on('error',()=>finish(new ContractError('RESPONSE_ERROR','Response could not be read.')));
        res.on('end',()=>{
          const outputHeaders: Record<string,string>={};
          for(const [key,value] of Object.entries(res.headers)) if(value!==undefined) outputHeaders[key.toLowerCase()]=Array.isArray(value)?value.join('\n'):value;
          finish(null,{status:res.statusCode ?? 0,headers:outputHeaders,body:Buffer.concat(chunks).toString('utf8')});
        });
      });
      const timer=setTimeout(()=>{ finish(new ContractError('REQUEST_TIMEOUT','Local request exceeded the deadline.')); req.destroy(); },timeoutMs);
      req.on('error',()=>finish(new ContractError('SERVER_NOT_AVAILABLE','Local target connection failed.')));
      req.end(input.body);
    });
  };
}
