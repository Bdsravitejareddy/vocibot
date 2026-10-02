import test from "node:test";
import assert from "node:assert/strict";
import { createEmptyClinicalRecord } from "../src/lib/domain/types";
import { diffClinicalRecord } from "../src/lib/extraction/diff-record";

test("frontend record diff skips empty values and doctor-edited fields", () => {
  const current = createEmptyClinicalRecord();
  const proposed = { ...current, chief_complaint: "Fever" };
  assert.deepEqual(diffClinicalRecord(current, proposed, { chief_complaint: ["s2"] }), [
    { field_name: "chief_complaint", previous_value: null, new_value: "Fever", source_segment_ids: ["s2"] },
  ]);
});
