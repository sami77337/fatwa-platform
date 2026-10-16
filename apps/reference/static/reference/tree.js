"use strict";
// Native details/summary and heading links work before htmx is available.
document.addEventListener("htmx:beforeRequest", event => {
  event.detail.target?.setAttribute("aria-busy", "true");
  const status = document.getElementById("request-status");
  if (status) status.textContent = "جارٍ تحميل العناوين الفرعية…";
});
document.addEventListener("htmx:afterRequest", event => {
  event.detail.target?.setAttribute("aria-busy", "false");
  const status = document.getElementById("request-status");
  if (status && event.detail.successful) status.textContent = "تم تحميل العناوين الفرعية.";
});
for (const type of ["htmx:responseError", "htmx:sendError", "htmx:timeout"]) {
  document.addEventListener(type, event => {
    event.detail.target?.setAttribute("aria-busy", "false");
    const status = document.getElementById("request-status");
    if (status) status.textContent = "تعذر تحميل الفروع. استخدم رابط عرض العناوين الفرعية للمحاولة.";
  });
}
