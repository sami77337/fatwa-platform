// Keep the author's textarea, file selection and link fields outside panel updates.
const selector = '#answer-related-panel[data-answer-related="enabled"]';
let panel = document.querySelector(selector);
if (panel) {
  let busy = false;
  const enable = () => panel.querySelectorAll('button[data-related-submit]').forEach(button => { button.disabled = false; });
  enable();
  document.addEventListener('submit', async event => {
    const form = event.target;
    if (!(form instanceof HTMLFormElement) || !panel.contains(form)) return;
    event.preventDefault();
    if (busy || !form.reportValidity()) return;
    busy = true;
    panel.setAttribute('aria-busy', 'true');
    const reference = panel.dataset.caseRef;
    const revision = panel.dataset.revision;
    try {
      const reply = await fetch('/casework/staff/', {
        method: 'POST', credentials: 'same-origin', redirect: 'error',
        headers: {'Content-Type': 'application/x-www-form-urlencoded', 'Accept': 'text/html'},
        body: new URLSearchParams(new FormData(form)),
      });
      if (!reply.ok || reply.headers.get('X-Answer-Related-Panel') !== '1') throw new Error('unavailable');
      const parsed = new DOMParser().parseFromString(await reply.text(), 'text/html');
      const replacement = parsed.querySelector(selector);
      if (!replacement || parsed.querySelectorAll(selector).length !== 1 ||
          replacement.dataset.caseRef !== reference || replacement.dataset.revision !== revision ||
          replacement.querySelector('script,iframe,object,embed')) throw new Error('invalid');
      panel.replaceWith(document.importNode(replacement, true));
      panel = document.querySelector(selector);
      enable();
      const status = panel.querySelector('[role="status"]');
      status?.focus();
    } catch {
      // Remove previously authorized source text when the new request is denied.
      panel.querySelectorAll('.related-results,.related-opened').forEach(node => node.remove());
      const status = panel.querySelector('[role="status"]');
      status.textContent = 'المواد غير متاحة أو تغير إصدار القضية أو الإذن. بقيت مسودتك وملفك المختار دون تعديل.';
      status.focus();
    } finally {
      busy = false;
      panel.removeAttribute('aria-busy');
    }
  });
}
