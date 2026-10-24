import assert from "node:assert/strict";

export const base = "/dev/editorial-workbench";
// Nine original samples plus eleven prepared rows; malformed input adds no row.
const worklistCount = 20;
export function editorialCases(h) {
  const {navigate, evaluate: e, wait, key, focus, activate, type, select, viewport, noOverflow} = h;
  return [
    ["Arabic RTL worklist exposes original and prepared synthetic cases and development limits", async () => {
      await navigate(base);
      assert.equal(await e("document.documentElement.lang"), "ar");
      assert.equal(await e("document.documentElement.dir"), "rtl");
      assert.equal(await e("document.querySelectorAll('.case-card').length"), worklistCount);
      assert.match(await e("document.querySelector('footer').innerText"), /NOT_DEPLOYED.*Gate B NOT_PASSED/);
      assert.deepEqual(await e("[...document.forms].map(f=>f.method)"), ["get"]);
    }],
    ["native Tab and skip-link move visible keyboard focus into main", async () => {
      await navigate(base);
      await key("Tab", 9);
      assert.equal(await e("document.activeElement.classList.contains('skip-link')"), true);
      assert.equal(await e("document.activeElement.getBoundingClientRect().top>=0"), true);
      assert.ok(await e("parseFloat(getComputedStyle(document.activeElement).outlineWidth)>=2"));
      await key("Enter", 13);
      await wait("document.activeElement.id==='main-content'");
      const ax = await h.cdp.send("Accessibility.getFullAXTree");
      assert.ok(ax.nodes.some(n => !n.ignored && n.role?.value === "main"));
      assert.ok(ax.nodes.some(n => !n.ignored && n.role?.value === "searchbox"));
    }],
    ["keyboard search and status filter survive detail and return navigation", async () => {
      await navigate(base);
      await type("#q", "SYN-REVISION");
      await key("Tab", 9);
      assert.equal(await e("document.activeElement.id"), "status");
      await select("#status", 2);
      await key("Tab", 9);
      assert.equal(await e("document.activeElement.id"), "batch");
      await key("Tab", 9);
      assert.equal(await e("document.activeElement.type"), "submit");
      await key("Enter", 13);
      await wait("new URLSearchParams(location.search).get('status')==='review' && document.querySelectorAll('.case-card').length===1");
      await activate(".case-card h2 a");
      await wait("location.pathname.endsWith('/history')");
      await activate("main>p>a");
      await wait("location.pathname==='/dev/editorial-workbench' && document.querySelector('#q')?.value==='SYN-REVISION'");
      assert.equal(await e("document.querySelector('#status').value"), "review");
      assert.equal(await e("document.querySelectorAll('.case-card').length"), 1);
    }],
    ["prepared batches preserve selection, source identity and row-specific history", async () => {
      await navigate(base);
      await select("#batch", 1);
      await key("Tab", 9);
      assert.equal(await e("document.activeElement.type"), "submit");
      await key("Enter", 13);
      await wait("new URLSearchParams(location.search).get('batch')==='synthetic-csv' && document.querySelectorAll('.case-card').length===4");
      assert.match(await e("document.querySelector('[aria-labelledby=batches-heading]').innerText"), /0e5d1bfe94c5f9abf5652a065b57212fcaa143abd738f95f2b233df5b68410f8/);
      await activate(".case-card h2 a");
      await wait("location.pathname.endsWith('/batch-synthetic-csv-1')");
      assert.equal(await e("document.querySelector('#snapshot strong').textContent"), "1");
      await activate("[aria-labelledby=batches-heading] nav a");
      await wait("location.pathname.endsWith('/batch-synthetic-csv-2')");
      assert.equal(await e("new URLSearchParams(location.search).get('batch')"), "synthetic-csv");
      assert.equal(await e("document.querySelectorAll('#history li[id], #comparison select').length"), 0);
      assert.match(await e("document.querySelector('[aria-labelledby=batches-heading]').innerText"), /duplicate_id/);
      await activate("main>p>a");
      await wait("document.querySelector('#batch')?.value==='synthetic-csv' && document.querySelectorAll('.case-card').length===4");
      for (const [batch, count, hash] of [
        ["synthetic-json",4,"d96eaabe7207a71ccdc1bc0426bf486f8448651ec34bf59e3ae96599b71c5aec"],
        ["synthetic-jsonl",3,"e8caaf496a756df9a7867f6a8ff9f4b9074d85eb0374f51d5e4c742803456363"],
        ["synthetic-malformed",0,"d4360bc841807dbc8d40aa57d52210c8b12413a8940b57310a8b3d14d1ca7086"]]) {
        await navigate(base + "?batch=" + batch);
        assert.equal(await e("document.querySelectorAll('.case-card').length"), count);
        assert.ok((await e("document.querySelector('[aria-labelledby=batches-heading]').innerText")).includes(hash));
      }
    }],
    ["review queue opens the same exact revision in the combined workbench", async () => {
      await navigate("/dev/editorial-queue");
      assert.equal(await e("document.querySelectorAll('.case-list>li').length"), 9);
      await type("#q", "SYN-REVISION");
      await key("Enter", 13);
      await wait("document.querySelectorAll('.case-list>li').length===1");
      await activate(".case-list h2 a");
      await wait("location.pathname==='/dev/editorial-queue/history'");
      assert.equal(await e("new URLSearchParams(location.search).get('q')"), "SYN-REVISION");
      await activate('#revisions a[href*="revision=7"]');
      await wait("location.pathname==='/dev/editorial-workbench/history' && document.querySelector('#snapshot strong')?.textContent==='7'");
      assert.equal(await e("document.documentElement.dir"), "rtl");
      await e("history.back()");
      await wait("location.pathname==='/dev/editorial-queue/history'");
      await activate("main>p>a");
      await wait("document.querySelector('#q')?.value==='SYN-REVISION' && document.querySelectorAll('.case-list>li').length===1");
      for (const width of [320,375]) {
        await viewport(width);
        for (const route of ["/dev/editorial-queue/history", base+"?batch=synthetic-csv", base+"/batch-synthetic-csv-1?batch=synthetic-csv"]) {
          await navigate(route);
          await noOverflow();
        }
      }
      await viewport(1280);
    }],
    ["native revision selectors resolve sparse IDs and reverse comparison", async () => {
      await navigate(base + "/history");
      assert.deepEqual(await e("[...document.querySelector('#revision').options].map(o=>o.value)"), ["1","2","4","7","9","11"]);
      await select("#revision", 3);
      await key("Tab", 9);
      assert.equal(await e("document.activeElement.id"), "before");
      await select("#before", 5);
      await key("Tab", 9);
      assert.equal(await e("document.activeElement.id"), "after");
      await select("#after", 2);
      await key("Tab", 9);
      await key("Enter", 13);
      await wait("location.search.includes('revision=7') && location.search.includes('before=11') && location.search.includes('after=4') && location.hash==='#comparison'");
      assert.equal(await e("document.querySelector('#snapshot strong').textContent"), "7");
      assert.match(await e("document.querySelector('#comparison>h3').innerText"), /11.*4/);
      assert.match(await e("document.querySelector('#comparison').innerText"), /عكس ترتيب السجل/);
      assert.ok(await e("document.querySelectorAll('#change-reviewer_notes ins, #change-reviewer_notes del, #change-reviewer-notes ins, #change-reviewer-notes del').length>0"));
      assert.equal(await e("[...document.querySelectorAll('#changes a')].every(a=>document.getElementById(a.hash.slice(1)))"), true);
    }],
    ["same revision comparison has no content differences", async () => {
      await navigate(base + "/history?revision=7&before=7&after=7#comparison");
      assert.match(await e("document.querySelector('#comparison').innerText"), /لا توجد فروق في محتوى المقارنة/);
      assert.equal(await e("document.querySelectorAll('#comparison section ins, #comparison section del').length"), 0);
      assert.equal(await e("document.querySelectorAll('#changes a').length"), 0);
    }],
    ["history link focuses snapshot and browser back/forward restore selection", async () => {
      await navigate(base + "/history?revision=7&before=11&after=4");
      await activate("#revision-1 nav a");
      await wait("document.querySelector('#snapshot strong')?.textContent==='1' && document.activeElement.id==='snapshot'");
      assert.equal(await e("document.querySelectorAll('#snapshot>pre')[1].textContent"), "  نص اختبار تحريري فقط.\n\tموضع تجريبي للمراجعة.\n");
      await e("history.back()");
      await wait("document.querySelector('#snapshot strong')?.textContent==='7'");
      await e("history.forward()");
      await wait("document.querySelector('#snapshot strong')?.textContent==='1'");
    }],
    ["empty search offers keyboard recovery to the complete worklist", async () => {
      await navigate(base);
      await type("#q", "SYN-NO-MATCH-999");
      await key("Enter", 13);
      await wait("location.search.includes('SYN-NO-MATCH-999')");
      assert.equal(await e("document.querySelectorAll('.case-card').length"), 0);
      assert.match(await e("document.querySelector('.case-list').innerText"), /لا توجد سجلات/);
      await activate(".case-list .empty a");
      await wait(`document.querySelectorAll('.case-card').length===${worklistCount}`);
    }],
    ["invalid record, absent sparse revision and malformed selection recover safely", async () => {
      for (const [route, status] of [["/missing-synthetic",404], ["/history?revision=3",404], ["/history?revision=07",400], ["/history?before=1",400]]) {
        await navigate(base + route, status);
        assert.ok(await e("document.querySelector('[role=alert]').innerText.length>0"));
        assert.equal(await e("document.querySelector('#snapshot')"), null);
        await activate("main .button-link");
        await wait(`document.querySelectorAll('.case-card').length===${worklistCount}`);
      }
    }],
    ["missing draft retains its source and never borrows another case history", async () => {
      await navigate(base + "/intake-2");
      assert.match(await e("document.querySelector('#snapshot').innerText"), /لا توجد لقطة/);
      assert.equal(await e("document.querySelectorAll('#history li[id], #comparison select').length"), 0);
      assert.ok(await e("document.querySelector('#intake pre').textContent.length>0"));
      await navigate(base + "/intake-2?revision=1", 400);
      await activate("main .button-link");
      await wait(`document.querySelectorAll('.case-card').length===${worklistCount}`);
    }],
    ["unresolved and technically verified references display their limits", async () => {
      await navigate(base + "/history");
      assert.equal(await e("document.querySelectorAll('#references .reference-item').length"), 3);
      assert.match(await e("document.querySelector('#references').innerText"), /unresolved/);
      assert.match(await e("document.querySelector('#references').innerText"), /UNVERIFIED/);
      await navigate(base + "/intake-7");
      assert.match(await e("document.querySelector('#references').innerText"), /verified/);
      assert.match(await e("document.querySelector('#references').innerText"), /لا تثبت/);
      assert.equal(await e("document.querySelectorAll('a[href^=\"https://\"],audio,video,iframe').length"), 0);
      await navigate(base + "/intake-2");
      assert.match(await e("document.querySelector('#references').innerText"), /لا توجد مؤشرات مراجع/);
    }],
    ["320px and 375px keep source, expanded whitespace and comparisons inside viewport", async () => {
      for (const width of [320,375]) {
        await viewport(width);
        for (const route of ["", "/history?revision=7&before=11&after=4", "/intake-2", "/missing-synthetic"]) {
          await navigate(base + route, route.includes("missing") ? 404 : 200);
          if (route.includes("history")) {
            await activate("#intake summary");
            await activate("#change-answer summary");
            await wait("document.querySelector('#change-answer details').open");
            assert.match(await e("document.querySelector('#change-answer details').innerText"), /⇥|␊/);
          }
          await noOverflow();
        }
        await h.screenshot(`editorial-${width}.png`);
      }
      await viewport(1280);
    }],
  ];
}
