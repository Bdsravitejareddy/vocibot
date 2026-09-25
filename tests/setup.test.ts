import test from "node:test";
import assert from "node:assert/strict";

import { createEmptyClinicalRecord } from "../src/lib/domain/types";

test("creates an empty clinical record without inventing facts", () => {
  assert.deepEqual(createEmptyClinicalRecord(), {
    chief_complaint: null,
    duration: null,
    presenting_symptoms: [],
    history_present_illness: null,
    relevant_negatives: [],
    past_medical_history: null,
    medications: [],
    allergies: [],
    vitals: {},
    examination_findings: [],
    assessment: null,
    plan: null,
    follow_up: null,
  });
});
