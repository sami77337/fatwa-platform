/** In-memory test double only. This is not a Django backend or product endpoint. */
import { readFile } from 'node:fs/promises';
import type { Fixture, Profile } from '../../api_contract/catalog.ts';
import type { Request, Response, Transport } from '../transport.ts';
export const fixture: Fixture=JSON.parse(await readFile(new URL('../../api_contract/synthetic-catalog.json',import.meta.url),'utf8'));
export const profile: Profile=JSON.parse(await readFile(new URL('../../api_contract/proposed-profile.json',import.meta.url),'utf8'));
export const base='http://127.0.0.1:8000';
export const headers={
  'content-type':'application/json; charset=utf-8','x-content-type-options':'nosniff','referrer-policy':'same-origin','cache-control':'no-store',
  'x-frame-options':'DENY','content-security-policy':"default-src 'self'; script-src 'self'; object-src 'none'; base-uri 'none'; form-action 'self'; frame-ancestors 'none'"
};
export const reply=(status: number,body: unknown,extra: Record<string,string>={}): Response => ({status,headers:{...headers,...extra},body:typeof body==='string'?body:JSON.stringify(body)});
export const error=(status: number,extra: Record<string,string>={})=>reply(status,{error:{code:'REJECTED',message:'Synthetic request rejected.'}},extra);
export const escape=(text: string)=>text.replaceAll('&','&amp;').replaceAll('<','&lt;').replaceAll('>','&gt;').replaceAll('"','&quot;').replaceAll("'",'&#39;');
export function model(mode='safe'): { transport: Transport; requests: Request[] } {
  const nodes=structuredClone(fixture.public_nodes); const requests: Request[]=[]; let privateHits=0; let mutated=false;
  const transport: Transport=async req=>{
    requests.push(structuredClone(req));
    if(mode==='deny-all') return error(404);
    const url=new URL(req.path,base); const route=url.pathname; const params=url.searchParams;
    if(profile.forbidden_paths.includes(route)) {
      if(mode==='mutates-on-forbidden-get' && req.method==='GET' && route===profile.forbidden_paths.at(-1)) nodes[0].title+=' altered';
      return error(404);
    }
    const single=route.match(/^\/api\/reference\/nodes\/([^/]+)\/$/);
    const children=route.match(/^\/api\/reference\/nodes\/([^/]+)\/children\/$/);
    const known=[profile.routes.roots,profile.routes.search,profile.routes.web,profile.routes.web_search].includes(route) || Boolean(single||children);
    if(!known) return error(404);
    if(!['GET','HEAD'].includes(req.method)) {
      if(mode==='mutates-on-denial' && !mutated) { nodes[0].title+=' altered'; mutated=true; }
      if(mode==='allows-write') return reply(201,{created:true});
      if(mode==='csrf-masks-route') return error(403);
      return error(405,{allow:'GET, HEAD'});
    }
    const q=params.get(profile.query_parameter); const page=params.get(profile.page_parameter)??'1'; const size=params.get(profile.page_size_parameter)??String(profile.max_page_size);
    if(params.has('next')) return mode==='open-redirect'?{...error(302),headers:{...headers,location:params.get('next')}}:error(400);
    if([profile.query_parameter,profile.page_parameter,profile.page_size_parameter].some(key=>params.getAll(key).length>1)) return error(400);
    if(!/^\d+$/.test(page)||!/^\d+$/.test(size)||Number(page)<1||Number(size)<1||Number(size)>profile.max_page_size) return error(400);
    if((route===profile.routes.search||route===profile.routes.web_search) && (q===null||q.trim()===''||q.length>profile.max_query_length)) return error(400);
    let selected=nodes;
    if(single) {
      const expected=nodes.find(node=>node.id===single[1]); if(!expected) return error(404);
      if(req.method==='HEAD') return reply(200,'');
      return reply(200,expected);
    }
    if(children) { if(!nodes.some(node=>node.id===children[1])) return error(404); selected=nodes.filter(node=>node.parent_id===children[1]); }
    if(route===profile.routes.roots) selected=nodes.filter(node=>node.parent_id===null);
    if(q!==null) selected=selected.filter(node=>node.title.includes(q));
    if(mode==='sql-injection' && q?.includes('OR 1=1')) selected=nodes;
    if(q===fixture.private_canaries.lookup) { privateHits++; if(mode==='cache-leak' && privateHits>1) return reply(200,fixture.private_canaries.markers[0]); }
    if(Number(page)>Math.max(1,Math.ceil(selected.length/Number(size)))) return error(404);
    if(req.method==='HEAD') return reply(200,'');
    if(route===profile.routes.web||route===profile.routes.web_search) {
      let content='<html lang="ar" dir="rtl"><body>مرجع فقهي حنبلي '+escape(fixture.source.work_title)+' '+escape(fixture.source.edition);
      content+=selected.map(node=>'<p>'+escape(node.title)+'</p>').join('');
      if(mode==='reflects-xss' && q) content+=q;
      if(mode==='missing-csrf') content+='<form method="post"><button>Submit</button></form>';
      content+='</body></html>';
      return reply(200,content,{'content-type':'text/html; charset=utf-8'});
    }
    const adjacent=(p: number)=>{
      const link=new URLSearchParams({[profile.page_parameter]:String(p),[profile.page_size_parameter]:size}); if(q!==null) link.set(profile.query_parameter,q);
      return route+'?'+link;
    };
    const result={count:selected.length,next:Number(page)*Number(size)<selected.length?adjacent(Number(page)+1):null,previous:Number(page)>1?adjacent(Number(page)-1):null,results:selected.slice((Number(page)-1)*Number(size),Number(page)*Number(size))};
    if(mode==='private-field') result.results=result.results.map(node=>({...node,requester_email:'synthetic@example.invalid'}));
    if(mode==='private-header') return reply(200,result,{'x-debug':fixture.private_canaries.markers[0]});
    if(mode==='wrong-source') result.results=result.results.map(node=>({...node,source:{...node.source,edition:'changed'}}));
    if(mode==='oversized-page') result.results=nodes.slice(0,3);
    if(mode==='cross-origin-page' && result.next) result.next='https://example.invalid/?page=2';
    if(mode==='no-security-headers') return {status:200,body:JSON.stringify(result),headers:{'content-type':'application/json'}};
    return reply(200,result);
  };
  return {transport,requests};
}
