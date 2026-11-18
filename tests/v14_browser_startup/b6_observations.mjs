// Optional B6 instrumentation for the integrator. No launch, I/O, timers,
// retries, exception handling policy or deadline changes live in this module.
const phases = ["spawn", "port-file", "target-discovery", "websocket"];
const events = ["spawned", "spawn-error", "process-exit", "port-missing",
  "port-incomplete", "port-read-error", "port-ready", "target-response",
  "websocket-open", "websocket-error", "websocket-close"];
const max = 600000;
const bounded = value => Number.isFinite(value) ? Math.min(max, Math.max(0, Math.round(value))) : null;

export class B6StartupObservations {
  #clock; #started; #phase; #phases = []; #events = {}; #snapshot;
  constructor({clock = () => performance.now()} = {}) {
    this.#clock = clock;
    this.#started = this.#now();
    for (const name of events) this.#events[name] = {count:0, first_ms:null};
  }
  #now() {
    try { const value = this.#clock(); return typeof value === "number" && Number.isFinite(value) ? value : null; }
    catch { return null; }
  }
  #offset(now) { return now === null || this.#started === null ? null : bounded(now - this.#started); }
  #finishPhase(now) {
    if (!this.#phase) return;
    this.#phases.push({phase:this.#phase.name, started_ms:this.#offset(this.#phase.start),
      elapsed_ms:now === null || this.#phase.start === null ? null : bounded(now - this.#phase.start)});
  }
  phase(name) {
    // Fixed one-way sequence and bounded storage, even with erroneous callers.
    if (this.#snapshot || !phases.includes(name) || name !== phases[this.#phases.length + (this.#phase ? 1 : 0)]) return;
    const now = this.#now();
    this.#finishPhase(now);
    this.#phase = {name, start:now};
  }
  event(name) {
    if (this.#snapshot || !events.includes(name)) return;
    const entry = this.#events[name];
    if (!entry.count) entry.first_ms = this.#offset(this.#now());
    entry.count = Math.min(10000, entry.count + 1);
  }
  snapshot(result) {
    if (!this.#snapshot) {
      const now = this.#now();
      this.#finishPhase(now);
      this.#snapshot = {
        schema:"fatwa.b6.startup-observations.v1", clock:"monotonic", scope:"startup-only",
        // This is the existing port-file poll limit, NOT an overall launch limit.
        port_poll_limit_ms:12000, root_cause:"ROOT_CAUSE_UNKNOWN",
        result:["READY", "BLOCKED"].includes(result) ? result : "UNKNOWN",
        elapsed_ms:this.#offset(now), phases:this.#phases, events:this.#events,
      };
    }
    // Caller mutation and subsequent cleanup cannot rewrite startup evidence.
    return structuredClone(this.#snapshot);
  }
}
