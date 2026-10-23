import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { test } from "node:test";
import { CAPSTONE_RECORD, LIVE_RECORD, MERGED, ORDER } from "../data/modules.ts";
import {
  checkRun,
  liveRecordLine,
  markStatus,
  moduleStatus,
  newestVerifiedOn,
  NO_RECORD,
  stagesWritten,
  type LiveRecord,
} from "./landing.ts";

function committed(file: string): LiveRecord {
  return JSON.parse(readFileSync(new URL(`../../../course/${file}`, import.meta.url), "utf8"));
}

function committedRecords(): Record<string, LiveRecord> {
  const records: Record<string, LiveRecord> = {};
  for (const spec of Object.values(LIVE_RECORD)) {
    if (spec && typeof spec === "object") records[spec.file] = committed(spec.file);
  }
  return records;
}

test("live record lines come from the committed records", () => {
  const records = committedRecords();
  const line = (id: string) => liveRecordLine(LIVE_RECORD[id], records);
  assert.equal(line("m0"), "synthetic transports");
  assert.equal(line("m1"), NO_RECORD);
  assert.equal(line("m2"), "judge 20/20 outcome");
  assert.equal(line("m3"), "9 spans · Langfuse 4.63");
  assert.equal(line("m7"), "12 PRs · recall 0.80");
  assert.equal(line("m5"), "injection denied · checklist 10/10");
  assert.equal(line("m4"), "recall@10 0.78 · MRR 0.65");
  assert.equal(line("m6"), "gateway 6/6 routed · $0.057");
});

test("a configured record that is missing reads as none", () => {
  const spec = { file: "x/fixtures/live_gone.json", format: () => "never" };
  assert.equal(liveRecordLine(spec, {}), NO_RECORD);
});

test("check run reads the capstone record", () => {
  const run = checkRun(committed(CAPSTONE_RECORD), "fixtures/live_review_run.json");
  assert.equal(run.title, "Capstone reviewer, run on 12 pull requests");
  assert.equal(run.source, "fixtures/live_review_run.json · claude-opus-5-5");
  assert.deepEqual(
    run.cells.map((c) => c.value),
    ["0.80", "0.58", "10 / 12", "$0.70"],
  );
  assert.equal(run.cells[3].label, "total cost, 131 s");
});

test("merged needs an exercise and the merged list", () => {
  assert.equal(moduleStatus("m7", true, MERGED), "merged");
  assert.equal(moduleStatus("m6", true, MERGED), "merged");
  assert.equal(moduleStatus("m7", false, MERGED), "not started");
  assert.equal(ORDER.filter((id) => moduleStatus(id, true, MERGED) === "merged").length, 8);
});

test("newest verified_on skips missing dates and accepts both forms", () => {
  assert.equal(newestVerifiedOn([undefined, new Date("2026-10-16"), "2026-10-17", "2026-09-01"]), "2026-10-17");
  assert.equal(newestVerifiedOn([undefined]), null);
});

test("stub tests do not count as written stages", () => {
  const sources = { "a/t1.py": "def test_x(): assert f()", "a/t2.py": 'pytest.skip("stage not written yet")' };
  assert.equal(stagesWritten(["a/t1.py", "a/t2.py", "a/t3.py"], sources), 1);
});

test("mark status falls back to pending", () => {
  const progress = { ex: { s1: { status: "passed" }, s2: { status: "weird" } } };
  assert.equal(markStatus(progress, "ex", "s1"), "passed");
  assert.equal(markStatus(progress, "ex", "s2"), "pending");
  assert.equal(markStatus(progress, "other", "s1"), "pending");
});
