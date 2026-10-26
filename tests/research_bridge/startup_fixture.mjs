// Synthetic lifecycle fixture only; never used for browser acceptance.
import {spawn} from "node:child_process";
import {writeFile} from "node:fs/promises";
import {setTimeout as delay} from "node:timers/promises";

const [mode, record] = process.argv.slice(2);
const profile = process.argv.find(arg => arg.startsWith("--user-data-dir=")).slice(16);
let child;
if (mode === "missing-port-tree") {
  child = spawn(process.execPath, ["-e", "setInterval(() => {}, 1000)"], {stdio:"ignore", windowsHide:true});
  process.argv[2] = "missing-port";
}
await writeFile(record, JSON.stringify({profile, pid:process.pid, child:child?.pid, args:process.argv.slice(4)}));
if (mode === "slow-port") {
  await delay(11000); // Exceeds the legacy ten-second deadline, within the protected bound.
  process.argv[2] = "delayed-target";
}
if (mode === "stderr-exit") {
  process.stderr.write("private-value ".repeat(300));
  process.stderr.write(`\nNo usable sandbox! ${profile} https://user:secret@example.invalid/?token=secret\n`);
  process.argv[2] = "exit";
}
await import("../acceptance/fastbuild/startup_fixture.mjs");
