import { test } from "node:test";
import assert from "node:assert/strict";
import { isLocalHost } from "./api.ts";
test("local hosts", () => {
  for (const h of ["localhost", "127.0.0.1", "[::1]"]) assert.equal(isLocalHost(h), true);
  for (const h of ["factory.lihachev.pro", "miubais.pages.dev", ""]) assert.equal(isLocalHost(h), false);
});
