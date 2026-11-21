export const ROOT = "/library-preview/materials/offline/";
export const FORMAT = "fatwa-public-offline-v1";
export const COPIES = "fatwa-library-selected-v1";
export const SHELL = "fatwa-library-shell-v1";
export const MAX_COPIES = 20;
const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/;
const DIGEST = /^[0-9a-f]{64}$/;
const TYPES = new Set(["text/plain", "application/pdf", "image/png", "image/jpeg", "image/webp", "audio/mpeg", "audio/mp4", "audio/wav", "video/webm", "video/mp4"]);
function require(value) { if (!value) throw new Error("offline_copy_invalid"); }
export function packetURL(id) { require(typeof id === "string" && UUID.test(id)); return ROOT + "packets/" + id + "/"; }
export async function digest(raw) { return [...new Uint8Array(await crypto.subtle.digest("SHA-256", raw))].map(b => b.toString(16).padStart(2, "0")).join(""); }
export function bytes(value) {
  require(typeof value === "string" && value.length <= 256000 && /^(?:[A-Za-z0-9+/]{4})*(?:[A-Za-z0-9+/]{2}==|[A-Za-z0-9+/]{3}=)?$/.test(value));
  return Uint8Array.from(atob(value), ch => ch.charCodeAt(0));
}
export async function validatePacket(value, now = Date.now()) {
  require(value && Object.keys(value).sort().join(",") === "expires_at,file_base64,format,material,prepared_at" && value.format === FORMAT);
  const prepared = Date.parse(value.prepared_at), expires = Date.parse(value.expires_at);
  require(Number.isFinite(prepared) && Number.isFinite(expires) && prepared <= now + 30000 && expires > now && expires > prepared && expires - prepared <= 3600000);
  const row = value.material;
  require(row && Object.keys(row).sort().join(",") === "creator,description,digest,edition_label,file,id,kind,language,number,recorded_text,source_locator,title,url,version_id,work_title");
  require(UUID.test(row.id) && UUID.test(row.version_id) && DIGEST.test(row.digest) && Number.isInteger(row.number) && row.number > 0 && row.number <= 64);
  require(["BOOK", "DOCUMENT", "IMAGE", "AUDIO", "VIDEO"].includes(row.kind) && ["ar", "en"].includes(row.language));
  for (const [key, max] of Object.entries({title: 200, work_title: 200, edition_label: 160, creator: 200, description: 2000, source_locator: 1000, recorded_text: 10000})) require(typeof row[key] === "string" && row[key].length <= max);
  require(row.url === `/library-preview/materials/${row.id}/${row.number}/`);
  const raw = bytes(value.file_base64);
  if (row.file === null) require(raw.length === 0);
  else {
    const file = row.file;
    require(file && TYPES.has(file.media_type) && typeof file.filename === "string" && file.filename.length <= 100 && !/[\\/\r\n]/.test(file.filename));
    require(Number.isInteger(file.size) && file.size > 0 && file.size <= 192000 && raw.length === file.size && DIGEST.test(file.sha256));
    require(await digest(raw) === file.sha256);
  }
  return value;
}

export async function readPacketResponse(response) {
  require(response.ok && response.headers.get("X-Offline-Packet") === FORMAT);
  const raw = new Uint8Array(await response.arrayBuffer());
  require(raw.length <= 350000 && await digest(raw) === response.headers.get("X-Content-SHA256"));
  return validatePacket(JSON.parse(new TextDecoder("utf-8", {fatal: true}).decode(raw)));
}

export async function reconcilePacket(retained, fresh, now = Date.now()) {
  await validatePacket(retained, now); await validatePacket(fresh, now);
  require(JSON.stringify(retained.material) === JSON.stringify(fresh.material) && retained.file_base64 === fresh.file_base64);
  return {...retained, expires_at: new Date(Math.min(Date.parse(retained.expires_at), Date.parse(fresh.expires_at))).toISOString()};
}
