import { check, exactKeys, validateNode, ordered } from '../api_contract/catalog.ts';
import type { CatalogNode, Fixture, Page, Profile } from '../api_contract/catalog.ts';
import type { Response } from './transport.ts';
import { requestUrl } from './transport.ts';
export function privateText(text: string, fixture: Fixture, code='PRIVATE_ARTIFACT'): void {
  let visible=text;
  // Decode common transport encodings so an escaped canary cannot evade the oracle.
  for(let step=0;step<3;step++) {
    visible=visible.replace(/\\u([0-9a-f]{4})/gi,(_,digits)=>String.fromCharCode(parseInt(digits,16)))
      .replace(/&#(?:x([0-9a-f]+)|(\d+));/gi,(match,hex,decimal)=>{const code=hex?parseInt(hex,16):Number(decimal);return code<=0x10ffff?String.fromCodePoint(code):match;}).normalize('NFKC');
    try { visible=decodeURIComponent(visible); } catch { /* Preserve malformed text for the raw check. */ }
    check(fixture.private_canaries.markers.every(marker=>!visible.includes(marker)),code,'Synthetic private artifact is visible.');
  }
}
export function privacy(response: Response, fixture: Fixture): void {
  privateText(response.body+JSON.stringify(response.headers),fixture);
}
export function securityHeaders(response: Response, html = false): void {
  const h=response.headers;
  check(h['x-content-type-options']?.toLowerCase()==='nosniff', 'HEADER_NOSNIFF', 'Expected nosniff.');
  check(['no-referrer','same-origin'].includes(h['referrer-policy']?.toLowerCase()), 'HEADER_REFERRER', 'Expected a restrictive referrer policy.');
  check((h['cache-control']??'').toLowerCase().split(',').some(part=>part.trim()==='no-store'), 'HEADER_CACHE', 'Synthetic acceptance responses must prohibit storage.');
  if(!html) return;
  check((h['content-type']??'').toLowerCase().startsWith('text/html'), 'HTML_CONTENT_TYPE', 'Expected an HTML surface.');
  const directives=new Map<string,string[]>();
  for(const part of (h['content-security-policy']??'').split(';')) {
    const tokens=part.trim().split(/\s+/).filter(Boolean); if(!tokens.length) continue;
    const [name,...values]=tokens;
    check(!directives.has(name.toLowerCase()), 'HEADER_CSP', 'Duplicate CSP directives are ambiguous.'); directives.set(name.toLowerCase(),values);
  }
  const same = (name: string,allowed: string[]) => { const values=directives.get(name); return values!==undefined && values.length>0 && values.every(v=>allowed.includes(v)); };
  for(const optional of ['script-src-elem','script-src-attr']) if(directives.has(optional)) check(same(optional,["'self'","'none'"]),'HEADER_CSP','Script overrides must remain restrictive.');
  check(same('default-src',["'self'","'none'"]) && same('script-src',["'self'","'none'"]) && same('object-src',["'none'"]) && same('base-uri',["'none'"]) && same('form-action',["'self'","'none'"]) && same('frame-ancestors',["'none'","'self'"]), 'HEADER_CSP', 'Expected the declared restrictive CSP.');
  check(['DENY','SAMEORIGIN'].includes(h['x-frame-options']?.toUpperCase()), 'HEADER_FRAME', 'Expected frame protection.');
}
export function json(response: Response): unknown {
  check((response.headers['content-type']??'').toLowerCase().split(';')[0].trim()==='application/json', 'JSON_CONTENT_TYPE', 'Expected application/json.');
  try { return JSON.parse(response.body); } catch { check(false,'JSON_PARSE','Malformed JSON response.'); }
}
export function node(response: Response, expected: CatalogNode, fixture: Fixture): void {
  check(response.status===200,'HTTP_STATUS','Expected successful node browsing.'); privacy(response,fixture); securityHeaders(response);
  const actual=json(response); validateNode(actual,fixture.source);
  check(JSON.stringify(canonical(actual))===JSON.stringify(canonical(expected)), 'NODE_CONTENT', 'Node fields differ from the seeded fixture.');
}
export function canonical(value: unknown): unknown {
  if(Array.isArray(value)) return value.map(canonical);
  if(value!==null && typeof value==='object') return Object.fromEntries(Object.entries(value).sort(([a],[b])=>a.localeCompare(b,'en')).map(([key,item])=>[key,canonical(item)]));
  return value;
}
export function page(response: Response, expected: CatalogNode[], fixture: Fixture, profile: Profile, origin: URL, route: string, pageNumber=1, size=profile.max_page_size, query?: string): Page {
  check(response.status===200,'HTTP_STATUS','Expected successful catalog browsing.'); privacy(response,fixture); securityHeaders(response);
  const result=json(response); exactKeys(result,['count','next','previous','results']);
  check(Number.isSafeInteger(result.count) && result.count===expected.length, 'PUBLIC_COUNT', 'Public count must match the synthetic public fixture.');
  check(Array.isArray(result.results) && result.results.length<=size, 'PAGE_BOUND', 'Page exceeds its declared size.');
  for(const item of result.results) validateNode(item,fixture.source);
  const sorted=ordered(expected); const slice=sorted.slice((pageNumber-1)*size,pageNumber*size);
  check(JSON.stringify(canonical(result.results))===JSON.stringify(canonical(slice)), 'PAGE_CONTENT', 'Public page differs from the seeded fixture.');
  function link(value: unknown, number: number | null) {
    if(number===null) { check(value===null,'PAGE_LINK','Expected no adjacent page.'); return; }
    check(typeof value==='string','PAGE_LINK','Expected an adjacent-page URL.');
    let url: URL; try { url=new URL(value,origin); } catch { check(false,'PAGE_LINK','Invalid pagination URL.'); }
    check(url.origin===origin.origin && !url.username && !url.password && !url.hash && !value.includes('\\') && url.pathname===route, 'PAGE_LINK','Pagination must remain on the same local collection.');
    const wanted=new URLSearchParams({[profile.page_parameter]:String(number),[profile.page_size_parameter]:String(size)}); if(query!==undefined) wanted.set(profile.query_parameter,query);
    const actual=[...url.searchParams.entries()].sort(); const expectedParams=[...wanted.entries()].sort();
    check(JSON.stringify(actual)===JSON.stringify(expectedParams),'PAGE_LINK','Pagination query is unbounded or inconsistent.');
    requestUrl(origin,url.pathname+url.search);
  }
  link(result.next, pageNumber*size<expected.length?pageNumber+1:null);
  link(result.previous,pageNumber>1?pageNumber-1:null);
  return result as Page;
}
export function errorResponse(response: Response, statuses: number[], fixture: Fixture): void {
  check(statuses.includes(response.status),'HTTP_STATUS','Expected a rejected request.'); privacy(response,fixture); securityHeaders(response,(response.headers['content-type']??'').toLowerCase().startsWith('text/html'));
  check(!response.headers.location,'REDIRECT_REJECTED','Rejected probes must not redirect.');
  // Public errors may be HTML or JSON, but must not expose debug internals or schemas containing private fields.
  check(!/Traceback \(most recent call last\)|DJANGO_SETTINGS_MODULE|DisallowedHost at|Technical 500 response|SQLSTATE|ProgrammingError|OperationalError/i.test(response.body),'ERROR_DETAIL','Error exposes backend diagnostics.');
  if((response.headers['content-type']??'').toLowerCase().startsWith('application/json')) {
    const body=json(response); exactKeys(body,['error']); exactKeys(body.error,['code','message']);
    check(typeof body.error.code==='string' && /^[A-Z_]{1,64}$/.test(body.error.code) && typeof body.error.message==='string' && body.error.message.length<=256,'ERROR_SCHEMA','Expected a bounded public error.');
  }
}
export function readOnly(response: Response, fixture: Fixture): void {
  errorResponse(response,[405],fixture);
  const allow=(response.headers.allow??'').toUpperCase().split(',').map(part=>part.trim()).filter(Boolean);
  check(allow.includes('GET') && allow.includes('HEAD') && allow.every(method=>['GET','HEAD','OPTIONS'].includes(method)), 'ALLOW_METHODS','Public routes must advertise only read-only methods.');
}
export function html(response: Response, fixture: Fixture, payload?: string): void {
  check(response.status===200,'HTTP_STATUS','Expected successful web browsing.'); privacy(response,fixture); securityHeaders(response,true);
  check(/<html\b[^>]*\blang\s*=\s*["']ar["']/i.test(response.body) && /<html\b[^>]*\bdir\s*=\s*["']rtl["']/i.test(response.body),'HTML_RTL','Expected Arabic RTL HTML.');
  check(!/<(?:img|svg|script|iframe)\b[^>]*S4_XSS/i.test(response.body) && !/<[a-z][^>]*\bon\w+\s*=\s*["']?[^>]*S4_XSS/i.test(response.body) && !/<script\b[^>]*>[^<]*S4_XSS/i.test(response.body),'XSS_EXECUTION','Synthetic payload appears as executable markup.');
  if(payload) check(!response.body.includes(payload),'XSS_ESCAPE','Unescaped synthetic payload appears in HTML.');
  // GET search forms need no CSRF token. Any mutating form must contain a nonempty Django token.
  for(const form of response.body.matchAll(/<form\b([^>]*)>([\s\S]*?)<\/form\s*>/gi)) {
    const method=form[1].match(/\bmethod\s*=\s*(?:["']([^"']+)["']|([^\s>]+))/i);
    if((method && (method[1]??method[2]).toLowerCase()!=='get') || /\bformmethod\s*=\s*(?:["'](?:post|put|patch|delete)["']|(?:post|put|patch|delete)(?:\s|>))/i.test(form[2])) {
      check(/<input\b(?=[^>]*\bname\s*=\s*["']csrfmiddlewaretoken["'])(?=[^>]*\bvalue\s*=\s*["'](?:[A-Za-z0-9]{32}|[A-Za-z0-9]{64})["'])[^>]*>/i.test(form[2]),'CSRF_FORM','Mutating web form lacks a Django CSRF token.');
    }
  }
}
export function unchanged(before: unknown, after: unknown): void {
  check(JSON.stringify(canonical(before))===JSON.stringify(canonical(after)), 'SIDE_EFFECT','Read or rejected mutation changed observable public catalog state.');
}
