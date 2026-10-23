import { test } from "node:test";
import assert from "node:assert/strict";
import { canCancel, isTerminal, statusLabel } from "./status.ts";

test("statusLabel is human readable", () => {
  assert.equal(statusLabel("in_progress"), "In progress");
});

test("delivered and cancelled are terminal", () => {
  assert.equal(isTerminal("delivered"), true);
  assert.equal(isTerminal("cancelled"), true);
  assert.equal(isTerminal("pending"), false);
});

test("only pending jobs can be cancelled", () => {
  assert.equal(canCancel("pending"), true);
  assert.equal(canCancel("in_progress"), false);
});
