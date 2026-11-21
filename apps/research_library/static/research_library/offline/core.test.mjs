import test from "node:test";
import assert from "node:assert/strict";
import {webcrypto} from "node:crypto";
import {FORMAT, packetURL, digest, validatePacket, readPacketResponse, reconcilePacket} from "./core.mjs";
if (!globalThis.crypto) globalThis.crypto = webcrypto;
const id = "00000000-0000-4000-8000-000000000001";
async function fixture() {
  const raw = new TextEncoder().encode("synthetic offline bytes\r\n"), now = Date.now();
  return {format: FORMAT, prepared_at: new Date(now - 1000).toISOString(), expires_at: new Date(now + 60000).toISOString(), file_base64: Buffer.from(raw).toString("base64"), material: {id, version_id: id, number: 1, digest: "a".repeat(64), kind: "BOOK", language: "ar", title: "مصدر", work_title: "عمل", edition_label: "نسخة", creator: "مؤلف اصطناعي", description: "", source_locator: "موضع", recorded_text: "", url: `/library-preview/materials/${id}/1/`, file: {sha256: await digest(raw), size: raw.length, media_type: "text/plain", filename: "fixture.txt"}}};
}
test("exact offline packet validates real content and same-origin version path", async () => {
  const value = await fixture(); assert.equal(await validatePacket(value), value);
  assert.equal(packetURL(id), `/library-preview/materials/offline/packets/${id}/`);
  for (const bad of ["../casework/staff/", "https://outside.example/", id + "?query=1"]) assert.throws(() => packetURL(bad));
  const raw = new TextEncoder().encode(JSON.stringify(value));
  const response = new Response(raw, {headers: {"X-Offline-Packet": FORMAT, "X-Content-SHA256": await digest(raw)}});
  assert.deepEqual(await readPacketResponse(response), value);
});
test("expired, tampered, private-field and redirected source copies are rejected", async () => {
  const value = await fixture();
  for (const change of [
    {expires_at: new Date(Date.now() - 1).toISOString()},
    {file_base64: Buffer.from("changed original").toString("base64")},
    {material: {...value.material, case_id: id}},
    {material: {...value.material, url: "https://outside.example/source"}},
    {material: {...value.material, file: {...value.material.file, filename: "../private.txt"}}},
  ]) await assert.rejects(validatePacket({...value, ...change}));
  await assert.rejects(readPacketResponse(new Response(JSON.stringify(value), {headers: {"X-Offline-Packet": FORMAT, "X-Content-SHA256": "a".repeat(64)}})));
});
test("descriptive copies retain no file bytes and unsafe MIME is rejected", async () => {
  const value = await fixture();
  await validatePacket({...value, file_base64: "", material: {...value.material, file: null}});
  await assert.rejects(validatePacket({...value, material: {...value.material, file: null}}));
  await assert.rejects(validatePacket({...value, material: {...value.material, file: {...value.material.file, media_type: "text/html"}}}));
});

test("online reconciliation caps a lease downward and cannot silently renew it", async () => {
  const value = await fixture(), now = Date.now();
  const shorter = {...value, prepared_at: new Date(now).toISOString(), expires_at: new Date(now + 5000).toISOString()};
  assert.equal((await reconcilePacket(value, shorter)).expires_at, shorter.expires_at);
  const longer = {...value, prepared_at: new Date(now).toISOString(), expires_at: new Date(now + 120000).toISOString()};
  assert.equal((await reconcilePacket(value, longer)).expires_at, value.expires_at);
  await assert.rejects(reconcilePacket(value, {...shorter, material: {...shorter.material, title: "changed metadata"}}));
});
