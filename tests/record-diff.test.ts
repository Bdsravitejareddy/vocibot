import test from "node:test";
import assert from "node:assert/strict";
import { createEmptyClinicalRecord } from "../src/lib/domain/types";
import { diffClinicalRecord } from "../src/lib/extraction/diff-record";

test("frontend diff produces no change for identical records", () => {
  const record = createEmptyClinicalRecord();
  assert.deepEqual(diffClinicalRecord(record, record, {}), []);
});
