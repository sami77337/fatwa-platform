"use strict";
(() => {
  const key = "fatwa.public.reader.references.v1";
  const uuid = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/;
  const digest = /^[0-9a-f]{64}$/;
  const status = document.getElementById("reader-tool-status");
  const say = text => { if (status) status.textContent = text; };
  const validPin = item => item && typeof item === "object" && uuid.test(item.publication_id)
    && digest.test(item.content_sha256) && Number.isInteger(item.version)
    && item.version >= 1 && item.version <= 2147483647;
  const pin = item => ({publication_id:item.publication_id, content_sha256:item.content_sha256, version:item.version});
  const stored = () => {
    const raw = localStorage.getItem(key);
    if (!raw) return [];
    if (raw.length > 16000) throw Error("reference_storage_invalid");
    const rows = JSON.parse(raw);
    if (!Array.isArray(rows) || rows.length > 50 || rows.some(row => !validPin(row))) throw Error("reference_storage_invalid");
    return rows.map(pin);
  };
  const write = rows => {
    if (rows.length > 50) throw Error("reference_limit");
    if (rows.length) localStorage.setItem(key, JSON.stringify(rows.map(pin)));
    else localStorage.removeItem(key);
  };
  async function current(url) {
    const target = new URL(url, location.origin);
    if (target.origin !== location.origin || !target.pathname.startsWith("/library-preview/reading/")) throw Error("reference_url_invalid");
    const response = await fetch(target.href, {cache:"no-store",credentials:"omit",headers:{Accept:"application/json"}});
    if (!response.ok || !(response.headers.get("Content-Type") || "").includes("application/json")) throw Error("reference_unavailable");
    const row = await response.json();
    if (!validPin(row) || typeof row.title !== "string" || row.title.length > 160
      || row.url !== `/library-preview/editions/${row.publication_id}/`
      || row.reader_url !== `/library-preview/reading/${row.publication_id}/`) throw Error("reference_response_invalid");
    return row;
  }
  document.querySelectorAll("[data-save-reference]").forEach(button => button.addEventListener("click", async () => {
    button.disabled = true;
    try {
      const item = await current(button.dataset.saveReference);
      const rows = stored().filter(row => row.publication_id !== item.publication_id);
      rows.push(pin(item)); write(rows);
      say("حُفظ المرجع على هذا الجهاز فقط؛ لم يُحفظ النص أو أي ملف.");
    } catch (_) { say("تعذر حفظ المرجع؛ قد تكون الصلاحية أو مساحة التخزين غير متاحة."); }
    finally { button.disabled = false; }
  }));
  document.querySelectorAll("[data-share-link]").forEach(button => button.addEventListener("click", async () => {
    button.disabled = true;
    const output = document.getElementById("share-output");
    const input = document.getElementById("share-url");
    if (output) output.hidden = true;
    if (input) input.value = "";
    try {
      const item = await current(button.dataset.shareLink);
      const url = new URL(item.url, location.origin).href;
      input.value = url; output.hidden = false; input.focus(); input.select();
      try { await navigator.clipboard.writeText(url); say("نُسخ رابط النسخة العامة. يبقى وصول المستلم خاضعًا لإتاحتها الحالية."); }
      catch (_) { say("الرابط العام جاهز؛ حدده وانسخه. لم تُرسل رسالة إلى أي شخص."); }
    } catch (_) { say("لم يعد رابط المشاركة متاحًا ضمن الإذن الحالي."); }
    finally { button.disabled = false; }
  }));
  document.querySelectorAll("[data-print-current]").forEach(button => button.addEventListener("click", async () => {
    button.disabled = true;
    try {
      const item = await current(button.dataset.printCurrent);
      if (item.content_sha256 !== button.dataset.contentSha256) throw Error("print_version_changed");
      say("تم التحقق من الإذن الحالي لهذه النسخة.");
      window.print();
    } catch (_) {
      const content = document.getElementById("print-content");
      if (content) content.replaceChildren();
      say("تعذرت طباعة النسخة؛ تغيّرت الإتاحة أو الصلاحية الحالية.");
    } finally { button.disabled = false; }
  }));
  const list = document.getElementById("saved-references");
  if (list) (async () => {
    let rows;
    try { rows = stored(); }
    catch (_) { say("تعذر قراءة المراجع المحلية؛ لا توجد نسخة محفوظة على الخادم."); return; }
    if (!rows.length) { say("لم تحفظ مراجع على هذا الجهاز بعد."); return; }
    for (const saved of rows) {
      const article = document.createElement("article");
      article.dataset.publicationId = saved.publication_id;
      const label = document.createElement("p");
      try {
        const item = await current(`/library-preview/reading/${saved.publication_id}/save-reference/`);
        if (item.content_sha256 !== saved.content_sha256 || item.version !== saved.version) throw Error("reference_version_changed");
        const link = document.createElement("a"); link.href = item.reader_url; link.textContent = item.title;
        label.append(link, document.createTextNode(` · النسخة ${item.version}`));
      } catch (_) { label.textContent = "مرجع محفوظ لم يعد متاحًا الآن؛ لا يُعرض عنوانه أو نصه القديم."; }
      const remove = document.createElement("button"); remove.type = "button"; remove.textContent = "حذف هذا المرجع من الجهاز";
      remove.addEventListener("click", () => {
        try { write(stored().filter(row => row.publication_id !== saved.publication_id)); article.remove(); say("حُذف المرجع المحلي."); }
        catch (_) { say("تعذر حذف المرجع من التخزين المحلي."); }
      });
      article.append(label, remove); list.append(article);
    }
  })();
})();
