import assert from "node:assert/strict";
import test from "node:test";
import vm from "node:vm";
import {fast3Cases} from "./fast3.mjs";

// Replay the different pre-focus states in the two #163 CDP traces through
// the actual scenario. Advance native focus while the existing wait is pending.
async function untilPacket(focusArrives) {
  const body = {id:""}, snapshot = {id:"snapshot"};
  const location = {pathname:"/dev/editorial-workbench/batch-synthetic-csv-1", hash:"#snapshot"};
  const document = {
    readyState:"complete", activeElement:body,
    getElementById: id => id === "snapshot" ? snapshot : null,
    querySelector: selector => selector === "#snapshot strong" ? {textContent:"1"} : null,
  };
  const packetReached = Error("packet activation reached");
  let openedRevision = false;
  let packetActivations = 0;
  const scenario = fast3Cases({
    async navigate() {}, async key() {}, async type() {},
    async evaluate(expression) {
      return expression.includes(".length") ? 4 : "synthetic-csv";
    },
    async activate(selector) {
      if (selector.startsWith("#revisions")) openedRevision = true;
      if (selector.includes("packet=html")) {
        packetActivations++;
        assert.equal(document.activeElement,snapshot,"fragment focus still pending");
        throw packetReached;
      }
    },
    async wait(expression) {
      if (!openedRevision) return;
      const satisfied = () => vm.runInNewContext(expression,{document,location});
      if (satisfied()) return;
      if (focusArrives) document.activeElement = snapshot;
      if (!satisfied()) throw Error("Timed out: "+expression);
    },
  })[0][1];
  if (focusArrives) {
    await assert.rejects(scenario(), error => error === packetReached);
    assert.equal(packetActivations,1);
  } else {
    await assert.rejects(scenario(), /^Error: Timed out:/);
    assert.equal(packetActivations,0);
  }
}

test("packet keyboard activation waits for native revision-fragment focus",()=>untilPacket(true));
test("missing revision-fragment focus fails before packet activation",()=>untilPacket(false));
