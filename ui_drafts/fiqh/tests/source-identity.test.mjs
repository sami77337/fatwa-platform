import test from "node:test";
import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import { createHash } from "node:crypto";

test("supplied book-622 ZIP matches expected SHA256 (identity only, no source-heading acceptance)", async t => {
  const archive = new URL("../../../_codex_input/FATWA_622_FIQH_COMPLETE_TOC_11397_20261011.zip", import.meta.url);
  let bytes;
  try { bytes = await readFile(archive); }
  catch (error) { if (error.code === "ENOENT") { t.skip("SOURCE_DATA_MISSING: optional owner archive not supplied"); return; } throw error; }
  assert.equal(createHash("sha256").update(bytes).digest("hex"), "82a797806430635350decdde27d07fe41fb1278838c8173dc4080f9d109957ce");
  assert.equal(bytes.subarray(0, 2).toString(), "PK");
});
