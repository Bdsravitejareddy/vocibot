import test from "node:test";
import assert from "node:assert/strict";
import { parseLocalEvent } from "../src/lib/speech/local-websocket-provider";

test("local transcript event maps to a transcript draft", () => {
  const event = parseLocalEvent(JSON.stringify({ type: "transcript", id: "l1", text: "नमस्ते", speaker: "PATIENT", timestamp: "2026-09-26T10:00:00Z", sequence_number: 3 }));
  assert.deepEqual(event, { id: "l1", text: "नमस्ते", speaker: "PATIENT", timestamp: "2026-09-26T10:00:00Z", sequence_number: 3 });
});

test("local error event preserves exact backend diagnostics", () => {
  const event = parseLocalEvent(JSON.stringify({ type: "error", category: "PIPELINE", message: "WhisperX dependency unavailable: No module named whisperx" }));
  assert.equal(event?.error, "WhisperX dependency unavailable: No module named whisperx");
});

test("non-transcript status events do not create transcript rows", () => {
  assert.equal(parseLocalEvent(JSON.stringify({ type: "status", timings: { vad_ms: 1 } })), null);
});
