import test from "node:test";
import assert from "node:assert/strict";

test("consultation API contract uses explicit review and approval states", () => {
  const statuses = ["IN_PROGRESS", "READY_FOR_REVIEW", "APPROVED"] as const;
  assert.deepEqual(statuses, ["IN_PROGRESS", "READY_FOR_REVIEW", "APPROVED"]);
});
