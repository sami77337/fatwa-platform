"use strict";

// The server has already verified the exact recording, reviewed transcript and
// integer timing pins. This initializer supplies actual native seek behavior on
// browsers that ignore an audio media fragment until playback begins.
export function initializeSegment(player) {
  const status = player.parentElement?.querySelector("[data-recording-seek-status]");
  const say = text => { if (status) status.textContent = text; };
  const integer = value => typeof value === "string" && /^(0|[1-9][0-9]{0,8})$/.test(value);
  const sourcePattern = /^\/(?:library-preview\/recordings|casework\/staff\/recording-transcripts)\/[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\/audio\/$/;
  const startText = player.dataset.startMs;
  const endText = player.dataset.endMs;
  let source;
  try {
    const base = new URL(player.ownerDocument.baseURI);
    source = new URL(player.getAttribute("src"), base);
    if (source.origin !== base.origin || !["http:", "https:"].includes(source.protocol)
      || source.search || !sourcePattern.test(source.pathname)) throw Error("source");
  } catch (_) {
    say("تعذر تهيئة الموضع الموثق؛ مصدر التسجيل غير متاح.");
    player.dataset.segmentState = "unavailable";
    return;
  }
  if (!integer(startText) || !integer(endText)) {
    say("تعذر تهيئة الموضع الموثق؛ لا يوجد توقيت صالح لهذه النسخة.");
    player.dataset.segmentState = "unavailable";
    return;
  }
  const start = Number(startText) / 1000;
  const end = Number(endText) / 1000;
  if (!(start >= 0 && end > start && end <= 86400)) {
    say("تعذر تهيئة الموضع الموثق؛ لا يوجد توقيت صالح لهذه النسخة.");
    player.dataset.segmentState = "unavailable";
    return;
  }
  const events = ["loadedmetadata", "loadeddata", "durationchange", "canplay", "seeked"];
  const deadline = Date.now() + 15000;
  let finished = false, attempts = 0, timer = null;
  const clean = () => {
    if (timer !== null) clearTimeout(timer);
    timer = null;
    events.forEach(name => player.removeEventListener(name, seek));
    player.removeEventListener("error", fail);
  };
  const fail = () => {
    if (finished) return;
    finished = true;
    clean();
    player.dataset.segmentState = "unavailable";
    say("تعذر الانتقال آليًا إلى الموضع الموثق. لم يبدأ تشغيل التسجيل.");
  };
  const later = () => {
    if (timer === null && !finished) timer = setTimeout(() => { timer = null; seek(); }, 100);
  };
  const seek = () => {
    if (finished) return;
    if (Date.now() >= deadline || player.error) { fail(); return; }
    if (player.readyState < 1 || !Number.isFinite(player.duration)) { later(); return; }
    if (start >= player.duration || end > player.duration + 0.05) { fail(); return; }
    if (Math.abs(player.currentTime - start) <= 0.025 && player.readyState >= 2 && !player.seeking) {
      finished = true;
      clean();
      player.dataset.segmentState = "ready";
      say("الموضع الموثق جاهز. اضغط تشغيل للاستماع؛ لا تشغيل تلقائيًا.");
      return;
    }
    if (attempts >= 20) { fail(); return; }
    if (!player.seeking && Math.abs(player.currentTime - start) > 0.025) {
      attempts += 1;
      try { player.currentTime = start; } catch (_) { /* Retry only within the bounded initialization. */ }
    }
    later();
  };
  player.dataset.segmentState = "pending";
  events.forEach(name => player.addEventListener(name, seek));
  player.addEventListener("error", fail);
  seek();
}

if (typeof document !== "undefined") {
  document.querySelectorAll("audio[data-recording-segment]").forEach(initializeSegment);
}
