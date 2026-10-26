// Reuse FAST7B's protected process containment, readiness and cleanup unchanged.
export {ProtectedBrowser} from "../fastbuild/startup.mjs";

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
