// No network upload, permission request or device enumeration on initialization.
// The existing native form remains the sole authenticated upload boundary.
const RATE = 8000, MAX_FRAMES = 80000;

function wav(chunks, frames) {
  const buffer = new ArrayBuffer(44 + frames * 2);
  const view = new DataView(buffer);
  const ascii = (offset, text) => [...text].forEach((c, i) => view.setUint8(offset + i, c.charCodeAt(0)));
  ascii(0, "RIFF"); view.setUint32(4, 36 + frames * 2, true);
  ascii(8, "WAVEfmt "); view.setUint32(16, 16, true);
  view.setUint16(20, 1, true); view.setUint16(22, 1, true);
  view.setUint32(24, RATE, true); view.setUint32(28, RATE * 2, true);
  view.setUint16(32, 2, true); view.setUint16(34, 16, true);
  ascii(36, "data"); view.setUint32(40, frames * 2, true);
  let offset = 44;
  for (const chunk of chunks) for (const value of chunk) {
    view.setInt16(offset, value, true); offset += 2;
  }
  return new File([buffer], "capture.wav", {type: "audio/wav"});
}

function mount(root) {
  const form = root.closest("form");
  const input = form && [...form.elements].find(e => e.type === "file" && e.name === root.dataset.inputName);
  const start = root.querySelector("[data-audio-start]"), stop = root.querySelector("[data-audio-stop]");
  const pause = root.querySelector("[data-audio-pause]"), resume = root.querySelector("[data-audio-resume]");
  const cancel = root.querySelector("[data-audio-cancel]"), accept = root.querySelector("[data-audio-accept]");
  const preview = root.querySelector("audio"), status = root.querySelector("[data-audio-status]");
  const duration = root.querySelector("[data-audio-duration]"), bytes = root.querySelector("[data-audio-bytes]");
  const progress = root.querySelector("[data-audio-progress]");
  let epoch = 0, session = null, file = null, assigned = null, url = null;
  let state = "idle";
  const metrics = frames => {
    duration.textContent = (frames / RATE).toFixed(2);
    bytes.textContent = String(frames ? 44 + frames * 2 : 0);
    progress.value = frames / RATE;
  };
  const show = (next, message) => {
    state = next; root.dataset.audioState = next; status.textContent = message;
    start.disabled = !["idle", "error"].includes(next);
    stop.disabled = !["recording", "paused"].includes(next);
    pause.disabled = next !== "recording";
    resume.disabled = next !== "paused";
    cancel.disabled = ["idle", "error"].includes(next);
    accept.disabled = next !== "preview";
  };
  const dispose = s => {
    if (!s) return;
    clearTimeout(s.timer);
    s.stream?.getTracks().forEach(t => { t.onended = null; t.stop(); });
    if (s.node) { s.node.onprocessorerror = null; s.node.port.onmessage = null; s.node.port.close(); s.node.disconnect(); }
    s.source?.disconnect();
    if (s.context) s.context.onstatechange = null;
    if (s.context && s.context.state !== "closed") s.context.close().catch(() => {});
    s.chunks = [];
  };
  const reset = () => {
    epoch++; dispose(session); session = null; file = null;
    root.dataset.audioFrames = "0";
    metrics(0);
    preview.pause(); preview.removeAttribute("src"); preview.load(); preview.hidden = true;
    if (url) URL.revokeObjectURL(url);
    url = null;
    if (assigned && input?.files[0] === assigned) input.value = "";
    assigned = null;
  };
  const fail = message => { reset(); show("error", message); };
  const finish = () => {
    if (!["recording", "pausing", "paused"].includes(state)) return;
    const s = session;
    if (!s.frames) { fail("لم يلتقط صوتًا صالحًا؛ أعد المحاولة."); return; }
    file = wav(s.chunks, s.frames);
    metrics(s.frames);
    dispose(s); session = null;
    url = URL.createObjectURL(file); preview.src = url; preview.hidden = false;
    const reason = s.frames === MAX_FRAMES ? "بلغ التسجيل حد عشر ثوانٍ وأُوقف الميكروفون. " : "أُوقف الميكروفون. ";
    show("preview", `${reason}معاينة محلية: ${(s.frames / RATE).toFixed(2)} ثانية، ${file.size} بايت، audio/wav. لم يُرفع الملف بعد.`);
  };
  const watchdog = (s, milliseconds, message) => {
    clearTimeout(s.timer);
    s.timer = setTimeout(() => { if (session === s) fail(message); }, milliseconds);
  };
  const recordingWatchdog = s => watchdog(s, (MAX_FRAMES - s.frames) / RATE * 1000 + 1000,
    "توقف تدفق الصوت؛ أُلغي التسجيل. أعد المحاولة.");
  if (!input || !window.isSecureContext || !navigator.mediaDevices?.getUserMedia || !window.AudioWorkletNode || !window.DataTransfer) {
    start.disabled = true;
    status.textContent = "التسجيل غير متاح هنا. يمكنك اختيار ملف WAV صالح في النموذج.";
    return;
  }
  show("idle", status.textContent);
  start.addEventListener("click", async () => {
    if (!["idle", "error"].includes(state)) return;
    reset(); const mine = epoch;
    const s = {chunks: [], frames: 0, displayedFrames: 0}; session = s;
    show("permission", "بانتظار إذنك بالميكروفون. يمكنك الإلغاء.");
    try {
      // Called synchronously from the explicit button interaction only.
      s.context = new AudioContext({sampleRate: RATE});
      const resumed = s.context.resume();
      resumed.catch(() => {}); // Cancellation may close a context while permission is pending.
      s.stream = await navigator.mediaDevices.getUserMedia({audio: {channelCount: 1}, video: false});
      if (mine !== epoch) { dispose(s); return; }
      await resumed;
      if (s.context.sampleRate !== RATE) throw new Error("unsupported_rate");
      await s.context.audioWorklet.addModule("/casework/audio-worklet.js");
      if (mine !== epoch) { dispose(s); return; }
      if (!s.stream.getAudioTracks().some(t => t.readyState === "live")) throw new Error("device_ended");
      s.source = s.context.createMediaStreamSource(s.stream);
      s.node = new AudioWorkletNode(s.context, "private-capture", {channelCount: 1, channelCountMode: "explicit"});
      s.node.onprocessorerror = () => { if (mine === epoch) fail("تعذر التقاط الصوت؛ أُوقف الميكروفون."); };
      s.node.port.onmessage = event => {
        if (mine !== epoch || session !== s) return;
        if (event.data?.state === "paused" && state === "pausing") {
          s.stream.getAudioTracks().forEach(t => { t.enabled = false; });
          metrics(s.frames);
          show("paused", "التسجيل متوقف مؤقتًا؛ الميكروفون معطل ولا تُضاف عينات. يمكنك الاستكمال أو الإيقاف والمعاينة.");
          watchdog(s, 60000, "انتهت مهلة الإيقاف المؤقت؛ أُلغي التسجيل وأُوقف الميكروفون.");
          return;
        }
        if (event.data?.state === "recording" && state === "resuming") {
          show("recording", "استُكمل التسجيل نفسه؛ مدة الإيقاف المؤقت لا تدخل في الصوت. الحد الإجمالي عشر ثوانٍ.");
          recordingWatchdog(s);
          return;
        }
        if (!["recording", "pausing"].includes(state)) return;
        const pcm = event.data;
        if (!(pcm instanceof Int16Array) || s.frames + pcm.length > MAX_FRAMES) {
          fail("تجاوز التسجيل الحد المسموح؛ لم يُحفظ."); return;
        }
        s.chunks.push(pcm); s.frames += pcm.length;
        root.dataset.audioFrames = String(s.frames);
        // Visible progress at most four times a second; status announcements remain discrete.
        if (s.frames - s.displayedFrames >= RATE / 4) { metrics(s.frames); s.displayedFrames = s.frames; }
        if (s.frames >= MAX_FRAMES) finish();
      };
      s.stream.getTracks().forEach(t => { t.onended = () => { if (mine === epoch) fail("انقطع الميكروفون؛ أُلغي التسجيل."); }; });
      s.context.onstatechange = () => {
        if (mine === epoch && ["recording", "pausing", "paused", "resuming"].includes(state) && s.context.state !== "running") fail("انقطع التقاط الصوت؛ أُلغي التسجيل وأُوقف الميكروفون.");
      };
      show("recording", "جارٍ التسجيل — توقف تلقائي عند عشر ثوانٍ. يمكنك الإيقاف أو الإلغاء.");
      s.source.connect(s.node); s.node.connect(s.context.destination);
      recordingWatchdog(s); // Pauses never reset the total captured-frame budget.
    } catch (error) {
      dispose(s);
      if (mine === epoch) fail(error.name === "NotAllowedError" ? "لم يُمنح إذن الميكروفون. لم يُحفظ تسجيل." : "التسجيل غير متاح بهذا المتصفح أو الجهاز؛ اختر ملف WAV صالحًا.");
    }
  });
  pause.addEventListener("click", () => {
    if (state !== "recording" || !session) return;
    show("pausing", "جارٍ إيقاف التسجيل مؤقتًا…");
    watchdog(session, 1000, "تعذر إيقاف التسجيل مؤقتًا؛ أُلغي وأُوقف الميكروفون.");
    session.node.port.postMessage("pause");
  });
  resume.addEventListener("click", () => {
    if (state !== "paused" || !session) return;
    show("resuming", "جارٍ استكمال التسجيل…");
    watchdog(session, 1000, "تعذر استكمال التسجيل؛ أُلغي وأُوقف الميكروفون.");
    session.stream.getAudioTracks().forEach(t => { t.enabled = true; });
    session.node.port.postMessage("resume");
  });
  stop.addEventListener("click", finish);
  cancel.addEventListener("click", () => { reset(); show("idle", "أُلغي التسجيل وأُوقف الميكروفون. لم يُرفع شيء."); });
  accept.addEventListener("click", () => {
    if (state !== "preview" || !file) return;
    try {
      const transfer = new DataTransfer(); transfer.items.add(file); input.files = transfer.files;
      assigned = input.files[0];
      input.dispatchEvent(new Event("change", {bubbles: true}));
      show("accepted", "اختير التسجيل للنموذج. راجع التأكيد الاصطناعي ثم احفظ بالنموذج الأصلي. يتحقق الخادم من الصوت والصلاحيات.");
    } catch { fail("تعذر اختيار التسجيل؛ اختر ملف WAV صالحًا يدويًا."); }
  });
  input.addEventListener("change", () => {
    if (assigned && input.files[0] !== assigned) { reset(); show("idle", "تغيّر الملف المختار؛ أُزيلت معاينة التسجيل."); }
  });
  form.addEventListener("submit", event => {
    if (["permission", "recording", "pausing", "paused", "resuming", "preview"].includes(state)) {
      event.preventDefault(); status.textContent = "أوقف التسجيل واختر استخدامه، أو ألغِه، قبل حفظ النموذج.";
    }
  });
  form.addEventListener("reset", () => { reset(); show("idle", "أُلغي التسجيل."); });
  window.addEventListener("pagehide", () => { reset(); show("idle", "أُوقف التسجيل عند مغادرة الصفحة."); });
  document.addEventListener("visibilitychange", () => {
    if (document.hidden && ["permission", "recording", "pausing", "paused", "resuming"].includes(state)) { reset(); show("idle", "أُلغي التسجيل عند إخفاء الصفحة."); }
  });
}

document.querySelectorAll("[data-browser-audio]").forEach(mount);
