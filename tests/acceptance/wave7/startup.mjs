// Reuse FAST7B's protected process containment, readiness and cleanup unchanged.
export {ProtectedBrowser} from "../fastbuild/startup.mjs";

// Persist only fixed hints: profile redaction alone cannot make stderr safe.
// Keep the internal cleanup report contract; both artifact writers use this boundary.
export function serializeBrowserReport(report) {
  const {browser_stderr:stderr = "", ...artifact} = report;
  artifact.diagnostics = {stderr_present:stderr.length > 0, stderr_hints:[
    ["SANDBOX_UNAVAILABLE", /No usable sandbox|Running as root without --no-sandbox/i],
    ["NAMESPACE_DENIED", /Failed to move to new namespace|Failed to unshare|Operation not permitted/i],
    ["PROFILE_LOCKED", /SingletonLock|ProcessSingleton|profile.*in use/i],
    ["DEVTOOLS_LISTENING", /DevTools listening on/i],
    ["ADDRESS_IN_USE", /Address already in use/i],
    ["RESOURCE_EXHAUSTED", /Resource temporarily unavailable|Cannot allocate memory|Too many open files/i],
  ].filter(([, pattern]) => pattern.test(stderr)).map(([hint]) => hint)};
  return JSON.stringify(artifact, null, 2) + "\n";
}

export function recordBrowserFailure(report, error, phase) {
  report.result = phase === "browser-startup" ? "BLOCKED" : "FAIL";
  report.blocker = error.message;
  report.phase = phase;
  report.failure = {code:error.code ?? "BROWSER_JOURNEY_FAILED",
    stage:error.stage ?? phase, cause_code:error.causeCode ?? null};
}

export async function closeBrowser(report, browser) {
  if (!browser) return;
  report.cleanup = await browser.close();
  report.startup = {stage:browser.stage, elapsed_ms:browser.elapsedMs, timeout_ms:browser.timeoutMs};
  report.browser_stderr = browser.profile
    ? browser.stderr.replaceAll(browser.profile, "<temporary-profile>") : browser.stderr;
  // Cleanup is part of acceptance, including when all application cases passed.
  if (report.cleanup.result !== "PASS") report.result = "FAIL";
}
