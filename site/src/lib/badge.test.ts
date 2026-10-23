import assert from "node:assert/strict";
import { test } from "node:test";
import { badgeFor, type LessonEntry } from "./badge.ts";

const NOW = new Date("2026-10-17T12:00:00Z");

function report(overrides: Partial<LessonEntry> = {}): LessonEntry {
  return {
    slug: "m1/a",
    path: "site/src/content/docs/m1/a.md",
    title: "A",
    verified_on: "2026-10-16",
    executed: "local",
    badge: "green",
    drifts: {},
    links: [{ url: "https://a.com", ok: true, redirected: false }],
    ...overrides,
  };
}

test("stale frontmatter beats a green report", () => {
  const badge = badgeFor({ verified_on: "2025-01-01", executed: "local" }, report(), NOW);
  assert.equal(badge.color, "red");
  assert.equal(badge.verifiedOn, "2025-01-01");
  assert.match(badge.label, /verified 2025-01-01/);
});

test("report for a different verified_on is ignored", () => {
  const drifted = report({
    verified_on: "2026-09-01",
    drifts: { "pypi:x": { pinned: "1.0.0", latest: "2.0.0", level: "major" } },
  });
  const badge = badgeFor({ verified_on: "2026-10-10", executed: "local" }, drifted, NOW);
  assert.equal(badge.color, "green");
  assert.deepEqual(badge.drifts, []);
});

test("matching report drift and links make the badge worse", () => {
  const fm = { verified_on: "2026-10-16", executed: "local" } as const;
  const major = report({ drifts: { "pypi:x": { pinned: "1", latest: "2", level: "major" } } });
  assert.equal(badgeFor(fm, major, NOW).color, "amber");
  const unknown = report({ drifts: { "npm:y": { pinned: "1", latest: null, level: "unknown" } } });
  assert.equal(badgeFor(fm, unknown, NOW).color, "amber");
  const broken = report({ links: [{ url: "https://b.com", ok: false, redirected: false }] });
  assert.equal(badgeFor(fm, broken, NOW).color, "red");
  const moved = report({ links: [{ url: "https://c.com", ok: true, redirected: true }] });
  assert.equal(badgeFor(fm, moved, NOW).color, "amber");
});

test("age uses whole days", () => {
  const at = (verified_on: string) => badgeFor({ verified_on, executed: "local" }, undefined, NOW);
  assert.equal(at("2026-07-19").color, "green");
  assert.equal(at("2026-07-18").color, "amber");
  assert.equal(at("2026-04-20").color, "amber");
  assert.equal(at("2026-04-19").color, "red");
});

test("not executed is amber, date objects are accepted", () => {
  const badge = badgeFor({ verified_on: new Date("2026-10-16"), executed: "none" }, undefined, NOW);
  assert.equal(badge.color, "amber");
  assert.equal(badge.verifiedOn, "2026-10-16");
});
