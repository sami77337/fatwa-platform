// Own only this run's browser tree. No security flags, retries of application
// scenarios, shared profiles, or changes to the protected CDP transport.
import {spawn} from "node:child_process";
import {mkdtemp, readFile, rm} from "node:fs/promises";
import os from "node:os";
import path from "node:path";
import {createInterface} from "node:readline";
import {setTimeout as delay} from "node:timers/promises";
import {fileURLToPath} from "node:url";

const supervisorPath = fileURLToPath(new URL("./browser_supervisor.py", import.meta.url));
const flags = ["--headless=new", "--no-first-run", "--no-default-browser-check",
  "--disable-background-networking", "--disable-component-update", "--disable-sync",
  "--remote-debugging-address=127.0.0.1", "--remote-debugging-port=0"];

export function failureResult(phase, cleanupFailed = false) {
  return !cleanupFailed && ["browser-startup", "not-run"].includes(phase) ? "NOT_RUN" : "FAIL";
}

export class BrowserStartupError extends Error {
  constructor(code, stage, causeCode) {
    super(`${code} (${stage})`);
    this.code = code;
    this.stage = stage;
    this.causeCode = causeCode;
  }
}

export class ProtectedBrowser {
  constructor({executable, args = [], python = process.env.FATWA_FASTBUILD_PYTHON ?? (process.platform === "win32" ? "python" : "python3"), startupTimeoutMs = 30000, signal} = {}) {
    if (!Number.isFinite(startupTimeoutMs) || startupTimeoutMs <= 0 || startupTimeoutMs > 30000)
      throw new RangeError("Startup deadline must be within 1..30000 ms");
    this.executable = executable;
    this.args = args;
    this.python = python;
    this.timeoutMs = startupTimeoutMs;
    this.parentSignal = signal;
    this.stage = "profile";
    this.stderr = "";
    this.controller = new AbortController();
  }

  error(code, causeCode) { return new BrowserStartupError(code, this.stage, causeCode); }

  async start() {
    const started = performance.now();
    const abort = () => this.controller.abort(this.error("RUN_DEADLINE_EXCEEDED"));
    this.parentSignal?.addEventListener("abort", abort, {once:true});
    if (this.parentSignal?.aborted) abort();
    const timer = setTimeout(() => this.controller.abort(this.error("BROWSER_STARTUP_TIMEOUT")), this.timeoutMs);
    try {
      this.controller.signal.throwIfAborted();
      this.profile = await mkdtemp(path.join(os.tmpdir(), "fatwa-fastbuild-profile-"));
      this.controller.signal.throwIfAborted();
      this.stage = "port-file";
      this.child = spawn(this.python, ["-u", supervisorPath, this.executable, ...this.args,
        ...flags, "--user-data-dir=" + this.profile, "about:blank"], {
        windowsHide:true, detached:process.platform !== "win32", stdio:["pipe", "pipe", "pipe"],
      });
      this.closed = new Promise(resolve => this.child.once("close", resolve));
      this.child.stdin.on("error", () => {}); // EPIPE during termination is expected.
      this.child.on("error", error => this.controller.abort(this.error("SUPERVISOR_SPAWN_FAILED", error.code)));
      this.child.on("exit", () => {
        if (!this.stopping) this.controller.abort(this.error("SUPERVISOR_EXITED"));
      });
      this.child.stderr.on("data", data => { this.stderr = (this.stderr + data).slice(-1500); });
      this.lines = createInterface({input:this.child.stdout});
      this.lines.on("line", line => {
        if (this.stopping) return;
        try {
          const event = JSON.parse(line);
          if (event.event === "error") this.controller.abort(this.error(
            event.code === "CONTAINMENT_SETUP_FAILED" ? event.code : "BROWSER_SPAWN_FAILED", event.code));
          else if (event.event === "exit") this.controller.abort(this.error("BROWSER_EXITED", event.code));
          else if (event.event !== "spawned") this.controller.abort(this.error("SUPERVISOR_PROTOCOL_INVALID"));
        } catch { this.controller.abort(this.error("SUPERVISOR_PROTOCOL_INVALID")); }
      });

      const port = await this.port();
      this.stage = "target-discovery";
      const endpoint = await this.target(port);
      this.stage = "websocket";
      this.socket = new WebSocket(endpoint);
      await this.bounded(new Promise((resolve, reject) => {
        this.socket.addEventListener("open", resolve, {once:true});
        this.socket.addEventListener("error", () => reject(this.error("DEVTOOLS_WEBSOCKET_FAILED")), {once:true});
        this.socket.addEventListener("close", () => reject(this.error("DEVTOOLS_WEBSOCKET_CLOSED")), {once:true});
      }));
      this.controller.signal.throwIfAborted();
      this.stage = "ready";
      return this.socket;
    } catch (error) {
      throw this.controller.signal.aborted ? this.controller.signal.reason : error;
    } finally {
      clearTimeout(timer);
      this.parentSignal?.removeEventListener("abort", abort);
      this.elapsedMs = Math.round(performance.now() - started);
    }
  }

  async bounded(promise) {
    const signal = this.controller.signal;
    let abort;
    try {
      return await Promise.race([promise, new Promise((_, reject) => {
        abort = () => reject(signal.reason);
        signal.addEventListener("abort", abort, {once:true});
        if (signal.aborted) abort();
      })]);
    } finally { signal.removeEventListener("abort", abort); }
  }

  async pause() { await this.bounded(delay(40)); }

  async port() {
    for (;;) {
      this.controller.signal.throwIfAborted();
      let content;
      try { content = await this.bounded(readFile(path.join(this.profile, "DevToolsActivePort"), "utf8")); }
      catch (error) {
        if (error.code !== "ENOENT") throw this.error("DEVTOOLS_PORT_READ_FAILED", error.code);
        await this.pause(); continue;
      }
      const [rawPort, browserPath] = content.trim().split(/\r?\n/);
      // Chrome may still be writing the file. A complete invalid record fails.
      if (!browserPath) { await this.pause(); continue; }
      if (!/^\d+$/.test(rawPort) || Number(rawPort) < 1 || Number(rawPort) > 65535
          || !/^\/devtools\/browser\/[a-zA-Z0-9-]+$/.test(browserPath))
        throw this.error("DEVTOOLS_PORT_INVALID");
      return Number(rawPort);
    }
  }

  async target(port) {
    for (;;) {
      this.controller.signal.throwIfAborted();
      let response;
      try {
        response = await fetch(`http://127.0.0.1:${port}/json/list`, {
          redirect:"error", signal:this.controller.signal,
        });
      } catch (error) {
        this.controller.signal.throwIfAborted();
        if (error.cause?.code !== "ECONNREFUSED") throw this.error("DEVTOOLS_HTTP_FAILED", error.cause?.code);
        await this.pause(); continue;
      }
      if (response.status !== 200) {
        await response.body?.cancel();
        throw this.error("DEVTOOLS_HTTP_FAILED", response.status);
      }
      let tabs;
      try { tabs = await response.json(); }
      catch { throw this.error("DEVTOOLS_PROTOCOL_INVALID"); }
      if (!Array.isArray(tabs)) throw this.error("DEVTOOLS_PROTOCOL_INVALID");
      const tab = tabs.find(item => item?.type === "page");
      if (!tab) { await this.pause(); continue; }
      let endpoint;
      try { endpoint = new URL(tab.webSocketDebuggerUrl); }
      catch { throw this.error("DEVTOOLS_ENDPOINT_INVALID"); }
      if (endpoint.protocol !== "ws:" || endpoint.hostname !== "127.0.0.1" || Number(endpoint.port) !== port
          || endpoint.username || endpoint.password || endpoint.search || endpoint.hash
          || !/^\/devtools\/page\/[a-zA-Z0-9-]+$/.test(endpoint.pathname))
        throw this.error("DEVTOOLS_ENDPOINT_INVALID");
      return endpoint.href;
    }
  }

  close() {
    this.cleanupPromise ??= this.cleanup();
    return this.cleanupPromise;
  }

  async cleanup() {
    this.stopping = true;
    const errors = [];
    this.socket?.close();
    if (this.child) {
      this.child.stdin.end(); // EOF closes the Windows job / Linux process group.
      const exited = await Promise.race([this.closed.then(() => true), delay(3000, false, {ref:false})]);
      // On POSIX, a dead supervisor and closed pipes do not prove its group is
      // empty: a surviving browser may have closed stderr before the crash.
      if (process.platform !== "win32" && this.child.pid) {
        try { process.kill(-this.child.pid, "SIGKILL"); }
        catch (error) { if (error.code !== "ESRCH") errors.push("TREE_KILL_FAILED"); }
      }
      if (!exited) {
        try {
          if (process.platform === "win32") this.child.kill("SIGKILL");
        } catch (error) { if (error.code !== "ESRCH") errors.push("TREE_KILL_FAILED"); }
        if (!await Promise.race([this.closed.then(() => true), delay(2000, false, {ref:false})])) errors.push("TREE_CLEANUP_TIMEOUT");
      }
      this.lines?.close();
      this.child.stdin.destroy(); this.child.stdout.destroy(); this.child.stderr.destroy();
    }
    if (this.profile) {
      const resolved = path.resolve(this.profile);
      if (path.dirname(resolved) !== path.resolve(os.tmpdir()) || !path.basename(resolved).startsWith("fatwa-fastbuild-profile-"))
        errors.push("PROFILE_CLEANUP_REFUSED");
      else {
        try { await rm(resolved, {recursive:true, force:true, maxRetries:5, retryDelay:200}); }
        catch { errors.push("PROFILE_CLEANUP_FAILED"); }
      }
    }
    return {result:errors.length ? "FAIL" : "PASS", errors};
  }
}
