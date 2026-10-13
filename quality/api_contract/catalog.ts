/** S4's proposed integration interface; no imports from or changes to S0. */
export type Source = {
  book_id: string; work_title: string; edition: string; school: 'hanbali';
  catalog_kind: 'source_table_of_contents'; fixture_id: string;
};
export type CatalogNode = {
  id: string; parent_id: string | null; title: string; order: number;
  printed_part: number; printed_page: number; has_children: boolean; source: Source;
};
export type Fixture = {
  schema_version: 1; identity: string; synthetic: true; source: Source;
  public_nodes: CatalogNode[];
  private_canaries: { lookup: string; markers: string[]; hidden_node_id: string };
};
export type Profile = {
  schema_version: 1; identity: string; synthetic: true;
  routes: { roots: string; node: string; children: string; search: string; web: string; web_search: string };
  forbidden_paths: string[]; max_page_size: number; max_query_length: number;
  query_parameter: string; page_parameter: string; page_size_parameter: string;
  validation_status: 400; missing_status: 404; forbidden_statuses: number[];
  timeout_ms: number; max_response_bytes: number;
};
export type Page = { count: number; next: string | null; previous: string | null; results: CatalogNode[] };
export class ContractError extends Error {
  code: string;
  constructor(code: string, message: string) { super(message); this.name = 'ContractError'; this.code = code; }
}
export function check(value: unknown, code: string, message: string): asserts value {
  if (!value) throw new ContractError(code, message);
}
export function record(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value);
}
export function exactKeys(value: unknown, keys: string[], code = 'SCHEMA_FIELDS'): asserts value is Record<string, unknown> {
  check(record(value), code, 'Expected an object.');
  const actual = Object.keys(value).sort();
  check(JSON.stringify(actual) === JSON.stringify([...keys].sort()), code, 'Missing or unapproved fields.');
}
function text(value: unknown, limit = 1024): value is string {
  return typeof value === 'string' && value.length > 0 && value.length <= limit && !/[\u0000-\u001f\u007f]/u.test(value);
}
function integer(value: unknown, min = 0, max = Number.MAX_SAFE_INTEGER): value is number {
  return Number.isSafeInteger(value) && Number(value) >= min && Number(value) <= max;
}
export function validateSource(value: unknown): asserts value is Source {
  exactKeys(value, ['book_id','work_title','edition','school','catalog_kind','fixture_id']);
  for (const key of ['book_id','work_title','edition','fixture_id']) check(text(value[key]), 'SOURCE_TYPE', 'Invalid source metadata.');
  check(value.school === 'hanbali' && value.catalog_kind === 'source_table_of_contents', 'SOURCE_SCOPE', 'Expected a Hanbali source table of contents.');
}
export function validateNode(value: unknown, source: Source): asserts value is CatalogNode {
  exactKeys(value, ['id','parent_id','title','order','printed_part','printed_page','has_children','source']);
  check(text(value.id, 80) && /^[a-zA-Z0-9_-]+$/.test(value.id), 'NODE_ID', 'Invalid synthetic identifier.');
  check(value.parent_id === null || (text(value.parent_id,80) && /^[a-zA-Z0-9_-]+$/.test(value.parent_id)), 'PARENT_ID', 'Invalid parent identifier.');
  check(text(value.title), 'TITLE_TYPE', 'Title must preserve a bounded source string.');
  for (const key of ['order','printed_part','printed_page']) check(integer(value[key], key === 'order' ? 0 : 1), 'NODE_NUMBER', 'Invalid ordering or printed citation.');
  check(typeof value.has_children === 'boolean', 'CHILDREN_FLAG', 'Expected a boolean.');
  validateSource(value.source);
  check(Object.keys(source).every(key => value.source[key] === source[key]), 'SOURCE_ATTRIBUTION', 'Source edition or scope changed.');
}
export function validateFixture(value: unknown): asserts value is Fixture {
  exactKeys(value, ['schema_version','identity','synthetic','source','public_nodes','private_canaries']);
  check(value.schema_version === 1 && value.synthetic === true && text(value.identity), 'FIXTURE_IDENTITY', 'Only explicit synthetic fixtures are accepted.');
  validateSource(value.source);
  check(value.source.fixture_id === value.identity, 'FIXTURE_IDENTITY', 'Source and fixture identities differ.');
  check(Array.isArray(value.public_nodes) && value.public_nodes.length >= 4 && value.public_nodes.length <= 100, 'FIXTURE_NODES', 'Expected a small synthetic fixture.');
  const nodes = value.public_nodes;
  nodes.forEach(node => validateNode(node, value.source as Source));
  check(new Set(nodes.map(node => node.id)).size === nodes.length, 'FIXTURE_IDS', 'Duplicate fixture identifiers.');
  check(nodes.every(node => node.parent_id === null || nodes.some(parent => parent.id === node.parent_id)), 'FIXTURE_PARENT', 'Missing parent in fixture.');
  for (const node of nodes) {
    const seen = new Set<string>([node.id]);
    let parent = node.parent_id;
    while (parent !== null) {
      check(!seen.has(parent), 'FIXTURE_CYCLE', 'Cycle in fixture.');
      seen.add(parent); parent = nodes.find(candidate => candidate.id === parent).parent_id;
    }
    check(node.has_children === nodes.some(child => child.parent_id === node.id), 'FIXTURE_CHILDREN', 'Incorrect children flag.');
  }
  exactKeys(value.private_canaries, ['lookup','markers','hidden_node_id']);
  check(text(value.private_canaries.lookup, 32) && text(value.private_canaries.hidden_node_id,80), 'PRIVATE_CANARIES', 'Invalid private canary selector.');
  const markers = value.private_canaries.markers;
  check(Array.isArray(markers) && markers.length >= 3 && markers.length <= 10 && markers.every(marker => text(marker,128)), 'PRIVATE_CANARIES', 'At least three bounded synthetic markers are required.');
  const publicText = JSON.stringify(nodes);
  check(markers.every(marker => !publicText.includes(marker)), 'FIXTURE_PRIVACY', 'Private marker appears in public fixture.');
  check(!publicText.includes(value.private_canaries.lookup) && !nodes.some(node=>node.id===value.private_canaries.hidden_node_id), 'FIXTURE_PRIVACY', 'Private selector collides with public fixture.');
  check(!markers.some(marker => value.private_canaries.lookup.includes(marker) || value.private_canaries.hidden_node_id.includes(marker)), 'FIXTURE_PRIVACY', 'A private marker would be sent as a request selector.');
}
export function validateProfile(value: unknown): asserts value is Profile {
  exactKeys(value, ['schema_version','identity','synthetic','routes','forbidden_paths','max_page_size','max_query_length','query_parameter','page_parameter','page_size_parameter','validation_status','missing_status','forbidden_statuses','timeout_ms','max_response_bytes']);
  check(value.schema_version === 1 && value.synthetic === true && text(value.identity), 'PROFILE_IDENTITY', 'Expected an explicit synthetic integration profile.');
  exactKeys(value.routes, ['roots','node','children','search','web','web_search']);
  const safePath = (route: unknown) => text(route,256) && /^\/(?!\/)[a-zA-Z0-9_/{\}-]*$/.test(route) && !route.includes('..');
  for (const key of ['roots','search','web','web_search']) check(safePath(value.routes[key]) && !value.routes[key].includes('{'), 'PROFILE_ROUTE', 'Invalid collection route.');
  for (const key of ['node','children']) check(safePath(value.routes[key]) && value.routes[key].split('{id}').length === 2 && !value.routes[key].replace('{id}','').match(/[{}]/), 'PROFILE_ROUTE', 'Expected one node identifier placeholder.');
  check(new Set(Object.values(value.routes)).size === 6, 'PROFILE_ROUTE', 'Routes must be distinct.');
  check(Array.isArray(value.forbidden_paths) && value.forbidden_paths.length >= 5 && value.forbidden_paths.length <= 20 && value.forbidden_paths.every(route => safePath(route) && !/[{}]/.test(route)), 'PROFILE_FORBIDDEN', 'Expected bounded forbidden probes.');
  check(new Set(value.forbidden_paths).size === value.forbidden_paths.length && !value.forbidden_paths.some(route=>Object.values(value.routes).includes(route)), 'PROFILE_FORBIDDEN', 'Duplicate or overlapping forbidden routes.');
  check(integer(value.max_page_size,1,100) && integer(value.max_query_length,48,512), 'PROFILE_LIMITS', 'Invalid query or pagination limits.');
  for (const key of ['query_parameter','page_parameter','page_size_parameter']) check(text(value[key],32) && /^[a-z_]+$/.test(value[key]), 'PROFILE_PARAMETER', 'Invalid parameter name.');
  check(new Set([value.query_parameter,value.page_parameter,value.page_size_parameter]).size===3, 'PROFILE_PARAMETER', 'Parameters must be distinct.');
  check(value.validation_status === 400 && value.missing_status === 404, 'PROFILE_STATUS', 'Validation and missing responses must fail closed.');
  check(Array.isArray(value.forbidden_statuses) && value.forbidden_statuses.length > 0 && value.forbidden_statuses.every(status => [403,404,405].includes(status)), 'PROFILE_STATUS', 'Forbidden status cannot permit success or redirect.');
  check(integer(value.timeout_ms,100,10000) && integer(value.max_response_bytes,1024,1048576), 'PROFILE_TRANSPORT', 'Invalid bounded transport limits.');
}
export function ordered(nodes: CatalogNode[]): CatalogNode[] {
  return [...nodes].sort((a,b) => a.order-b.order || a.id.localeCompare(b.id,'en'));
}
