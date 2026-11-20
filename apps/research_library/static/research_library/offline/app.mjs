import {ROOT, FORMAT, bytes, packetURL} from "./core.mjs";

const status = document.querySelector("#status"), saved = document.querySelector("#saved"), available = document.querySelector("#available"), reader = document.querySelector("#reader");
let worker, objects = [], expiry, activeId, activeExpires;
function element(tag, text) { const node = document.createElement(tag); if (text !== undefined) node.textContent = text; return node; }
function tell(text) { status.textContent = text; }
function clearReader() { clearTimeout(expiry); for (const url of objects) URL.revokeObjectURL(url); objects = []; activeId = null; activeExpires = null; reader.replaceChildren(); reader.hidden = true; }
function request(command, id) {
  return new Promise((resolve, reject) => {
    const channel = new MessageChannel(), timer = setTimeout(() => reject(new Error("offline_timeout")), 15000);
    channel.port1.onmessage = event => { clearTimeout(timer); channel.port1.close(); event.data.ok ? resolve(event.data.result) : reject(new Error("offline_unavailable")); };
    worker.postMessage({command, id}, [channel.port2]);
  });
}
async function show(id) {
  const value = await request("READ", id), row = value.material;
  clearReader(); activeId = id; activeExpires = Date.parse(value.expires_at); reader.hidden = false;
  reader.append(element("h2", row.title), element("p", `${row.creator}، ${row.work_title}، ${row.edition_label}، ${row.source_locator}. نسخة ${row.number}.`));
  reader.append(element("p", "أُعدت النسخة: " + new Date(value.prepared_at).toLocaleString("ar") + " · تنتهي: " + new Date(value.expires_at).toLocaleString("ar")));
  const origin = element("a", "التحقق من المصدر عند الاتصال"); origin.href = row.url; reader.append(origin);
  if (row.recorded_text) reader.append(element("pre", row.recorded_text));
  if (row.file) {
    const raw = bytes(value.file_base64), url = URL.createObjectURL(new Blob([raw], {type: row.file.media_type})); objects.push(url);
    if (["AUDIO", "VIDEO", "IMAGE"].includes(row.kind)) {
      const media = element({AUDIO: "audio", VIDEO: "video", IMAGE: "img"}[row.kind]); media.src = url;
      if (row.kind === "IMAGE") media.alt = row.title; else { media.controls = true; media.preload = "metadata"; }
      reader.append(media);
    } else if (row.file.media_type === "text/plain") reader.append(element("pre", new TextDecoder("utf-8", {fatal: true}).decode(raw)));
    const file = element("a", "فتح الملف المحلي"); file.href = url; file.target = "_blank"; file.rel = "noopener"; reader.append(file);
    const download = element("a", "تنزيل الملف المحلي"); download.href = url; download.download = row.file.filename; reader.append(download);
    reader.append(element("p", "SHA-256: " + row.file.sha256));
  }
  expiry = setTimeout(async () => { clearReader(); await list(); tell("انتهت صلاحية النسخة المحلية. أعد حفظها عند الاتصال إذا بقي الإذن قائمًا."); }, Math.max(1, Date.parse(value.expires_at) - Date.now()));
  reader.scrollIntoView({block: "start"});
}
function button(label, callback) {
  const result = element("button", label); result.type = "button";
  result.addEventListener("click", async () => {
    result.disabled = true;
    try { await callback(); } catch { tell("تعذر إتمام الطلب. تحقق من الاتصال وصلاحية هذه النسخة."); }
    finally { result.disabled = false; }
  });
  return result;
}
async function list(command = "LIST") {
  const rows = await request(command); saved.replaceChildren();
  if (!rows.length) saved.append(element("p", "لم تحفظ مواد صالحة على هذا الجهاز بعد."));
  if (activeId && !rows.some(row => row.id === activeId)) clearReader();
  const active = rows.find(row => row.id === activeId);
  if (active && Date.parse(active.expires_at) !== activeExpires) await show(activeId);
  for (const row of rows) {
    const card = element("article"); card.dataset.versionId = row.id;
    card.append(element("h3", row.title + " — نسخة " + row.number), element("p", "صالحة محليًا حتى " + new Date(row.expires_at).toLocaleString("ar")));
    card.append(button("قراءة النسخة المحلية", () => show(row.id)), button("حذف هذه النسخة", async () => { await request("REMOVE", row.id); await list(); tell("حُذفت النسخة من هذا الجهاز."); })); saved.append(card);
  }
}
async function catalog() {
  available.replaceChildren();
  try {
    const response = await fetch(ROOT + "catalog/", {credentials: "omit", cache: "no-store", redirect: "error"});
    if (!response.ok) throw new Error();
    const result = await response.json();
    if (result.format !== FORMAT || !Array.isArray(result.materials) || result.materials.length > 64) throw new Error();
    for (const row of result.materials) {
      packetURL(row.version_id);
      const card = element("article"); card.dataset.versionId = row.version_id;
      card.append(element("h3", row.title), element("p", row.work_title + " — نسخة " + row.number));
      card.append(button("حفظ هذه المادة على الجهاز", async () => { await request("SAVE", row.version_id); await list(); tell("حُفظت نسخة محددة للقراءة دون اتصال."); }));
      const label = element("label"), checkbox = element("input"); checkbox.type = "checkbox"; checkbox.name = "version"; checkbox.value = row.version_id;
      checkbox.addEventListener("change", () => {
        if (document.querySelectorAll("input[name=version]:checked").length > 20) { checkbox.checked = false; tell("تتسع الحزمة لعشرين مادة كحد أقصى."); }
        document.querySelector("#package").disabled = !document.querySelector("input[name=version]:checked");
      });
      label.append(checkbox, document.createTextNode(" إضافة إلى حزمة الأرشيف")); card.append(label); available.append(card);
    }
    if (!result.materials.length) available.append(element("p", "لا توجد مواد يسمح إذنها الحالي بالحفظ."));
  } catch { available.append(element("p", "القائمة الحالية تحتاج إلى اتصال. المواد التي اخترتها سابقًا تبقى متاحة ضمن صلاحيتها المحلية.")); }
}
async function refresh() {
  await list(navigator.onLine ? "SYNC" : "LIST"); await catalog();
  tell(navigator.onLine ? "اكتمل التحقق من النسخ المحفوظة المتاحة." : "أنت دون اتصال. افتح إحدى النسخ التي حفظتها سابقًا.");
}
document.querySelector("#archive").addEventListener("submit", event => { if (!document.querySelector("input[name=version]:checked")) event.preventDefault(); });
document.querySelector("#refresh").addEventListener("click", () => refresh().catch(() => tell("تعذر التحقق الآن.")));
document.querySelector("#clear").addEventListener("click", () => request("CLEAR").then(() => { clearReader(); return list(); }).then(() => tell("حُذفت جميع المواد المحلية المختارة.")).catch(() => tell("تعذر حذف المواد الآن.")));
window.addEventListener("online", () => refresh().catch(() => {}));
document.addEventListener("visibilitychange", () => { if (!document.hidden && worker) refresh().catch(() => {}); });
try {
  if (!window.isSecureContext || !("serviceWorker" in navigator)) throw new Error();
  await navigator.serviceWorker.register(ROOT + "sw.mjs", {type: "module", scope: ROOT});
  const registration = await Promise.race([navigator.serviceWorker.ready, new Promise((_, reject) => setTimeout(reject, 15000))]);
  worker = registration.active;
  if (!worker) throw new Error();
  await refresh();
} catch { tell("الحفظ المحلي غير متاح في هذا المتصفح أو السياق. افتح المكتبة عند الاتصال."); }
