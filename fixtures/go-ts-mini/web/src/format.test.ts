import { test } from "node:test";
import assert from "node:assert/strict";
import type { Job } from "./api.ts";
import { formatDate, formatHours, formatLanguages, formatSummary } from "./format.ts";

const sample: Job = {
  id: "job-0001",
  reference: "REF-1",
  source_lang: "en",
  target_lang: "de",
  hours_estimate: 0.4,
  status: "in_progress",
  created_at: "2026-10-01T09:30:00Z",
};

test("formatHours shows minutes under one hour", () => {
  assert.equal(formatHours(0.25), "15 min");
});

test("formatHours shows one decimal in hours", () => {
  assert.equal(formatHours(12.54), "12.5 h");
});

test("formatLanguages joins source and target language", () => {
  assert.equal(formatLanguages("en", "de"), "en -> de");
});

test("formatDate keeps the calendar date", () => {
  assert.equal(formatDate("2026-10-01T09:30:00Z"), "2026-10-01");
});

test("formatSummary combines reference, languages, estimated hours and status", () => {
  assert.equal(formatSummary(sample), "REF-1: en -> de, 24 min (In progress)");
});
