import assert from "node:assert/strict";
import {createHash} from "node:crypto";

export function fast3Cases(h) {
  const {navigate, evaluate: e, wait, key, activate, type, viewport, noOverflow} = h;
  const queue = "/dev/editorial-queue";
  const workbench = "/dev/editorial-workbench";
  return [
    ["FAST3 filtered prepared queue preserves exact record, revision and malformed recovery", async () => {
      await navigate(queue + "?batch=synthetic-csv");
      assert.equal(await e("document.querySelectorAll('.case-list>li').length"), 4);
      await type("#q", "SYN-CSV-1");
      await key("Enter", 13);
      await wait("document.querySelectorAll('.case-list>li').length===1");
      assert.equal(await e("document.querySelector('#batch').value"), "synthetic-csv");
      await activate(".case-list h2 a");
      await wait("location.pathname.endsWith('/batch-synthetic-csv-1')");
      assert.equal(await e("new URLSearchParams(location.search).get('batch')"), "synthetic-csv");
      await activate('#revisions a[href*="revision=1"]');
      await wait("location.pathname==='/dev/editorial-workbench/batch-synthetic-csv-1' && document.querySelector('#snapshot strong')?.textContent==='1'");
      await activate('a[href*="packet=html"]');
      await wait("!!document.querySelector('.case-packet')");
      assert.ok(await e("document.querySelector('#packet-intake').textContent.includes('batch-synthetic-csv-1')"));
      await navigate(queue + "?batch=synthetic-malformed");
      assert.equal(await e("document.querySelectorAll('.case-list>li h2').length"), 0);
      assert.ok(await e("document.body.textContent.includes('d4360bc841807dbc8d40aa57d52210c8b12413a8940b57310a8b3d14d1ca7086')"));
      await activate('.case-list .empty a');
      await wait("document.querySelectorAll('.case-list>li').length===20");
    }],
    ["FAST3 packet keeps sparse reverse selection, deterministic export digest and complete print", async () => {
      await navigate(workbench + "/history?revision=7&before=11&after=4");
      await activate('a[href*="packet=html"]');
      await wait("!!document.querySelector('.case-packet')");
      const exported = await e(`(async () => {
        const url = document.querySelector('.packet-actions a[href*="packet=json"]').href;
        const response = await fetch(url);
        const text = await response.text();
        return {text, status:response.status, digest:response.headers.get('X-Packet-SHA256'), cache:response.headers.get('Cache-Control')};
      })()`);
      assert.equal(exported.status, 200);
      assert.equal(exported.cache, "no-store");
      assert.ok(exported.text.endsWith("\n"));
      const digest = createHash("sha256").update(exported.text, "utf8").digest("hex");
      assert.equal(digest, exported.digest);
      assert.ok((await e("document.querySelector('.case-packet').textContent")).includes(digest));
      const packet = JSON.parse(exported.text);
      assert.deepEqual(packet.selection, {revision:7,before:11,after:4});
      assert.equal(packet.identity.case_key, "history");
      assert.deepEqual(packet.snapshots.map(row => row.number), [1,2,4,7,9,11]);
      for (const snapshot of packet.snapshots) {
        const displayed = await e(`[...document.querySelectorAll('#packet-revision-${snapshot.number} pre')].slice(0,5).map(node=>node.textContent)`);
        assert.deepEqual(displayed, [snapshot.human_editor,snapshot.editorial_note,snapshot.title,snapshot.answer,snapshot.reviewer_notes]);
      }
      assert.equal(packet.persisted_review.status, "not_loaded");
      assert.equal(packet.persisted_review.events, null);
      assert.equal(packet.persisted_review.snapshot_link, "not_established");
      await activate('.packet-actions a[href*="packet=print"]');
      await wait("new URLSearchParams(location.search).get('packet')==='print' && !!document.querySelector('.print-help')");
      assert.equal(await e("[...document.querySelectorAll('details')].every(node=>node.open)"), true);
      assert.equal(await e("document.querySelectorAll('#packet-snapshots>section').length"), 6);
      for (const width of [320,375]) {
        await viewport(width);
        await noOverflow();
      }
      await h.screenshot("fast3-packet-375.png");
      await activate('.packet-actions a:not([href*="packet="])');
      await wait("document.querySelector('#snapshot strong')?.textContent==='7'");
      assert.equal(await e("document.querySelector('#before').value"), "11");
      assert.equal(await e("document.querySelector('#after').value"), "4");
      await viewport(1280);
    }],
    ["FAST3 reference investigation opens the same Arabic prepared record and packet on mobile", async () => {
      await viewport(375);
      await navigate("/dev/reference-triage/batch-synthetic-csv-1");
      assert.equal(await e("document.documentElement.dir"), "rtl");
      const exact = "  سُؤَالٌ اصطناعي\r\nبسطرٍ وتشكيل e\u0301  ";
      assert.ok((await e("[...document.querySelectorAll('pre code')].map(node=>node.textContent)")).includes(exact));
      await noOverflow();
      await activate('a[href="/dev/editorial-workbench/batch-synthetic-csv-1"]');
      await wait("location.pathname==='/dev/editorial-workbench/batch-synthetic-csv-1'");
      await activate('a[href*="packet=html"]');
      await wait("!!document.querySelector('.case-packet')");
      assert.ok((await e("[...document.querySelectorAll('#packet-intake pre')].map(node=>node.textContent)")).includes(exact));
      await noOverflow();
      await navigate("/dev/reference-triage?batch=synthetic-malformed");
      assert.equal(await e("document.querySelectorAll('a[href^=\"/dev/reference-triage/\"]').length"), 0);
      assert.ok(await e("document.body.textContent.includes('تعذر تحليل الدفعة')"));
      await noOverflow();
      await viewport(1280);
    }],
  ];
}
