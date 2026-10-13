"use strict";
// Native details/summary keeps keyboard operation available before htmx loads.
document.addEventListener("htmx:responseError", () => {
  const status = document.getElementById("request-status");
  if (status) status.textContent = "تعذر تحميل الفروع. استخدم رابط عرض العناوين الفرعية للمحاولة.";
});
document.addEventListener("htmx:sendError", () => {
  const status = document.getElementById("request-status");
  if (status) status.textContent = "تعذر الاتصال بالفهرس. استخدم رابط عرض العناوين الفرعية.";
});
document.addEventListener("htmx:afterSwap", () => {
  const status = document.getElementById("request-status");
  if (status) status.textContent = "تم تحميل العناوين الفرعية.";
});
