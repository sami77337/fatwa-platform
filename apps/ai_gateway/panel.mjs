// Only a separately clicked, freshly authorized selection updates source fields.
// No code reads, changes, serializes, autosubmits or saves the answer textarea.
const panel = document.querySelector('#ai-citation-panel[data-ai-citation="enabled"]');
if (panel) {
  let busy = false;
  const enable = () => panel.querySelectorAll('[data-ai-submit]').forEach(button => { button.disabled = false; });
  enable();
  panel.addEventListener('submit', async event => {
    const form = event.target;
    if (!(form instanceof HTMLFormElement) || !panel.contains(form)) return;
    event.preventDefault();
    if (busy || !form.reportValidity()) return;
    busy = true;
    panel.setAttribute('aria-busy', 'true');
    try {
      const reply = await fetch('/casework/ai-citations/', {
        method: 'POST', credentials: 'same-origin', redirect: 'error',
        headers: {'Content-Type': 'application/x-www-form-urlencoded', 'Accept': 'text/html'},
        body: new URLSearchParams(new FormData(form)),
      });
      if (!reply.ok || reply.headers.get('X-AI-Citation-Panel') !== '1') throw new Error('unavailable');
      const document = new DOMParser().parseFromString(await reply.text(), 'text/html');
      const next = document.querySelector('#ai-citation-result[data-ai-result="1"]');
      if (!next || document.querySelectorAll('#ai-citation-result').length !== 1 ||
          next.querySelector('script,iframe,object,embed')) throw new Error('response');
      const handoff = next.querySelector('[data-ai-handoff="1"]');
      if (handoff) {
        const values = Object.fromEntries([...handoff.querySelectorAll('input')].map(input => [input.name, input.value]));
        const targets = ['selection', 'mode', 'start', 'end'].map(name => window.document.querySelector(`#precise-${name}`));
        if (Object.keys(values).sort().join(',') !== 'end,mode,selection,start' ||
            targets.some(target => !target) || values.mode !== 'TEXT' ||
            ![...targets[0].options].some(option => option.value === values.selection)) throw new Error('handoff');
        ['selection', 'mode', 'start', 'end'].forEach((name, index) => { targets[index].value = values[name]; });
        // Old page/time labels and limitations must not describe a new text range.
        window.document.querySelector('#precise-label').value = '';
        window.document.querySelector('#precise-limitation').value = '';
        targets[0].focus();
      }
      const adopted = window.document.importNode(next, true);
      panel.querySelector('#ai-citation-result').replaceWith(adopted);
      const requestState = panel.querySelector('#ai-citation-request [name="state"]');
      if (requestState && adopted.dataset.nextState) requestState.value = adopted.dataset.nextState;
      enable();
      adopted.querySelector('[role="status"]')?.focus();
    } catch {
      const output = panel.querySelector('#ai-citation-result');
      output.replaceChildren();
      output.dataset.runStatus = 'UNAVAILABLE';
      delete output.dataset.runId;
      delete output.dataset.nextState;
      const status = window.document.createElement('p');
      status.setAttribute('role', 'status');
      status.tabIndex = -1;
      status.textContent = 'تعذرت المساعدة أو تغير المصدر أو الإذن. بقيت مسودة الجواب دون تعديل ويمكن متابعة الإحالات يدويًا.';
      output.append(status);
      status.focus();
    } finally {
      busy = false;
      panel.removeAttribute('aria-busy');
    }
  });
}
