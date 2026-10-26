// Synthetic lifecycle peer only; never imported by acceptance launchers.
import {writeFile} from "node:fs/promises";
import path from "node:path";
import {setTimeout as delay} from "node:timers/promises";

const profile = process.argv.find(value => value.startsWith("--user-data-dir=")).slice("--user-data-dir=".length);
await writeFile(path.join(profile, "launch.json"), JSON.stringify(process.argv.slice(2)));
if (process.argv[2] === "delayed-port") await delay(12500);
await import("../fastbuild/startup_fixture.mjs");
