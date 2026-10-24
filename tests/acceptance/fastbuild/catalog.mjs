import assert from "node:assert/strict";

export function catalogCases(h) {
  const {navigate, evaluate:e, wait, key, focus, activate, type, viewport, noOverflow} = h;
  const ready = () => wait("document.querySelector('#interactive-catalog')?.hidden===false && document.querySelector('#tree-region')?.getAttribute('aria-busy')==='false' && !!document.querySelector('[role=treeitem]')");
  return [
    ["actual catalog RTL tree keyboard expands, traverses and collapses", async () => {
      await navigate("/fiqh"); await ready();
      assert.equal(await e("document.documentElement.dir"), "rtl");
      await focus("[role=treeitem]");
      await key("ArrowRight",39); await key("ArrowLeft",37);
      await wait("document.querySelectorAll('[role=treeitem]').length===3");
      await key("ArrowLeft",37);
      assert.equal(await e("document.activeElement.getAttribute('aria-level')"), "2");
      await key("ArrowRight",39);
      assert.equal(await e("document.activeElement.getAttribute('aria-level')"), "1");
      await key("End",35);
      assert.equal(await e("document.activeElement===[...document.querySelectorAll('[role=treeitem]')].at(-1)"),true);
      await key("Home",36); await key("ArrowRight",39);
      assert.equal(await e("document.querySelectorAll('[role=treeitem]').length"),1);
    }],
    ["Arabic catalog search opens actual heading, breadcrumb and history navigation", async () => {
      await navigate("/fiqh"); await ready();
      await type("#search-query", "باب"); await key("Enter",13);
      await wait("document.querySelectorAll('#search-results li a').length===2");
      await activate("#search-results li a");
      await wait("location.pathname==='/fiqh/nodes/2' && document.querySelectorAll('#breadcrumbs li').length===2");
      assert.match(await e("document.querySelector('#reference-content').innerText"), /بابٌ اصطناعي أول/);
      assert.equal(await e("document.activeElement.dataset.id"), "2");
      await activate("#breadcrumbs a");
      await wait("location.pathname==='/fiqh/nodes/1'");
      await e("history.back()"); await wait("location.pathname==='/fiqh/nodes/2'");
      await e("history.forward()"); await wait("location.pathname==='/fiqh/nodes/1'");
      await navigate("/fiqh/nodes/2"); await ready();
      assert.match(await e("document.querySelector('#reference-content').innerText"), /بابٌ اصطناعي أول/);
    }],
    ["catalog empty search recovers with native clear button", async () => {
      await navigate("/fiqh"); await ready();
      await type("#search-query", "عنوانغيرموجود"); await key("Enter",13);
      await wait("document.querySelector('#search-results').getAttribute('aria-busy')==='false' && document.querySelector('#search-results').innerText.includes('لم نعثر')");
      assert.equal(await e("document.querySelectorAll('#search-results li a').length"),0);
      await activate("#clear-search");
      assert.equal(await e("document.activeElement.id"),"search-query");
      assert.equal(await e("document.querySelector('#search-query').value"),"");
      await type("#search-query","باب"); await key("Enter",13);
      await wait("document.querySelectorAll('#search-results li a').length===2");
    }],
    ["320px and 375px catalog search, breadcrumb and reference have no overflow", async () => {
      for (const width of [320,375]) {
        await viewport(width); await navigate("/fiqh"); await ready(); await noOverflow();
        await type("#search-query","باب"); await key("Enter",13);
        await wait("document.querySelectorAll('#search-results li a').length===2");
        await noOverflow(); await activate("#search-results li a");
        await wait("location.pathname==='/fiqh/nodes/2'"); await ready(); await noOverflow();
        await h.screenshot(`catalog-${width}.png`);
      }
    }],
  ];
}
