// Synthetic lifecycle peer; not Chrome, an external provider or product acceptance.
import {setTimeout as delay} from "node:timers/promises";
import {writeFile} from "node:fs/promises";

const record = process.argv[3];
const profile = process.argv.find(arg => arg.startsWith("--user-data-dir=")).slice(16);
await writeFile(record, JSON.stringify({pid:process.pid, profile, args:process.argv.slice(4)}));
await delay(650);
process.argv[2] = "socket-hang";
await import("../acceptance/fastbuild/startup_fixture.mjs");
