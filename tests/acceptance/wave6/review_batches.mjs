// Hooks verified against actual PR51 UI contract, not guessed selectors.
// Required only with run.py --browser --review-batches after E2 integration.
import assert from "node:assert/strict";

export function reviewBatchCase({navigate, wait, evaluate, click, key, reload, history, text}) {
  return ["PR51 allowlisted batches isolate repeated IDs and preserve filter/page/detail/return", async () => {
    await navigate("/dev/editorial-preview/pipeline");
    assert.deepEqual(await evaluate("[...document.querySelector('#batch').options].map(option=>option.value)"), ["default", "mixed"]);
    await click("article h2 a"); await wait("!!document.querySelector('article .original-text')");
    assert.equal(await evaluate("document.querySelector('article .original-text').textContent"), "  سؤال اصطناعي في الطهارة للمراجعة فقط  ");
    await navigate("/dev/editorial-preview/pipeline");
    await evaluate("document.querySelector('#batch').value='mixed';document.querySelector('#q').focus()");
    await key("Enter", 13); await wait("new URL(location.href).searchParams.get('batch')==='mixed'");
    await click("article h2 a"); await wait("location.pathname.endsWith('/SYN-P01')");
    assert.equal(await evaluate("document.querySelector('article .original-text').textContent"), "  سؤالٌ اصطناعيٌّ آخر\tللمراجعة\nفقط  ");
    assert.match(await text(), /دفعة متنوعة/);
    await navigate("/dev/editorial-preview/pipeline?batch=mixed");
    await evaluate("document.querySelector('#status').value='blocked-invalid';document.querySelector('#issue').value='invalid_input';document.querySelector('#page-size').value='1';document.querySelector('#q').value='اصطناعي';document.querySelector('#q').focus()");
    await key("Enter", 13); await wait("new URL(location.href).searchParams.get('issue')==='invalid_input'");
    await click('a[rel="next"]'); await wait("new URL(location.href).searchParams.get('page')==='2'");
    const saved = await evaluate("location.href");
    const expected = {batch:"mixed",status:"blocked-invalid",issue:"invalid_input",page_size:"1",page:"2",q:"اصطناعي"};
    await click("article h2 a"); await wait("location.pathname.endsWith('/SYN-M03')");
    for (const [name,value] of Object.entries(expected)) assert.equal(await evaluate(`new URL(location.href).searchParams.get(${JSON.stringify(name)})`), value);
    assert.match(await text(), /لم يُنشأ سجل مسودة/);
    await evaluate("[...document.querySelectorAll('a')].find(a=>a.textContent.includes('العودة إلى القائمة المصفاة')).click()");
    await wait("location.pathname.endsWith('/pipeline')"); assert.equal(await evaluate("location.href"), saved);
    await history("back"); await history("forward"); await reload();
    assert.equal(await evaluate("location.href"), saved);
    assert.equal(await evaluate("document.querySelector('#batch').value"), "mixed");
    assert.equal(await evaluate("document.querySelector('article h2 a').textContent"), "SYN-M03");
    await evaluate("[...document.querySelectorAll('form a')].find(a=>a.textContent==='مسح التصفية').click()");
    await wait("new URL(location.href).searchParams.get('batch')==='mixed' && !new URL(location.href).searchParams.has('page')");
    assert.equal(await evaluate("document.querySelectorAll('article').length"), 4);
  }];
}
