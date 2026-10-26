// Lifecycle only: the existing research journey owns its assertions and guards.
import {ProtectedBrowser, failureResult} from "../acceptance/fastbuild/startup.mjs";

function diagnostics(stderr) {
  // Never publish raw browser output: it can contain local paths, URLs or secrets.
  // Fixed hints retain useful evidence without relying on incomplete redaction.
  const hints = [
    ["SANDBOX_UNAVAILABLE", /No usable sandbox|Running as root without --no-sandbox/i],
    ["NAMESPACE_DENIED", /Failed to move to new namespace|Failed to unshare|Operation not permitted/i],
    ["PROFILE_LOCKED", /SingletonLock|ProcessSingleton|profile.*in use/i],
    ["DEVTOOLS_LISTENING", /DevTools listening on/i],
    ["ADDRESS_IN_USE", /Address already in use/i],
    ["RESOURCE_EXHAUSTED", /Resource temporarily unavailable|Cannot allocate memory|Too many open files/i],
  ].filter(([, pattern]) => pattern.test(stderr)).map(([hint]) => hint);
  return {stderr_present:stderr.length > 0, stderr_hints:hints};
}

export async function runResearchBrowser(interact, {
  executable = process.env.FATWA_FASTBUILD_BROWSER ?? (process.platform === "win32"
    ? "C:/Program Files/Google/Chrome/Application/chrome.exe" : "/usr/bin/chromium"),
  args = [], python, startupTimeoutMs = 30000, runTimeoutMs = 75000,
} = {}) {
  if (!Number.isFinite(runTimeoutMs) || runTimeoutMs <= 0 || runTimeoutMs > 75000)
    throw new RangeError("Run deadline must be within 1..75000 ms");
  const deadline = new AbortController();
  const browser = new ProtectedBrowser({executable, args, python, startupTimeoutMs, signal:deadline.signal});
  const report = {result:"NOT_RUN", catalog:"fixed synthetic test double; no database"};
  let phase = "browser-startup";
  const watchdog = setTimeout(() => {
    deadline.abort();
    // start() observes the signal; after readiness bounded() observes this abort.
    browser.controller.abort(browser.error("RUN_DEADLINE_EXCEEDED"));
  }, runTimeoutMs);
  try {
    const socket = await browser.start();
    phase = "interactions";
    Object.assign(report, await browser.bounded(interact(socket, browser.controller.signal)));
    browser.controller.signal.throwIfAborted();
    report.result = "PASS";
  } catch (error) {
    report.result = deadline.signal.aborted ? "FAIL" : failureResult(phase);
    report.failure = {
      code:error.code ?? "BROWSER_JOURNEY_FAILED", stage:error.stage ?? phase,
      cause_code:error.causeCode ?? null,
    };
  } finally {
    clearTimeout(watchdog);
    report.cleanup = await browser.close();
    report.startup = {stage:browser.stage, elapsed_ms:browser.elapsedMs, timeout_ms:browser.timeoutMs};
    report.diagnostics = diagnostics(browser.stderr);
    if (report.cleanup.result !== "PASS") report.result = "FAIL";
  }
  return report;
}
