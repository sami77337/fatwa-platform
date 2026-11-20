const status = document.querySelector("[data-staff-install-status]");
if (status && "serviceWorker" in navigator && window.isSecureContext) {
  navigator.serviceWorker.register("/casework/staff/pwa/sw.mjs", {scope: "/casework/staff/"})
    .then(() => { status.textContent = "يمكن تثبيت المكتب من قائمة المتصفح عند توفر الخيار. القضايا والعمليات الخاصة تحتاج إلى اتصال وصلاحية حالية."; })
    .catch(() => { status.textContent = "تعذّر تجهيز التثبيت في هذا المتصفح. يمكنك متابعة العمل من الصفحة عند الاتصال."; });
}
