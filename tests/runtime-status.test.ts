import test from "node:test";
import assert from "node:assert/strict";
import { runtimePresentation } from "../src/lib/runtime-status";

test("demo runtime presents demo mode and scripted provider", () => {
  const presentation = runtimePresentation({ mode: "demo", providers: {} });
  assert.equal(presentation.modeLabel, "Demo mode");
  assert.equal(presentation.providerLabel, "Deterministic scripted provider");
  assert.equal(presentation.microphoneEnabled, false);
});

test("local runtime presents local AI and enables microphone only for local mode", () => {
  const presentation = runtimePresentation({ mode: "local", providers: {} });
  assert.equal(presentation.modeLabel, "Local AI");
  assert.equal(presentation.providerLabel, "Local microphone pipeline");
  assert.equal(presentation.microphoneEnabled, true);
});
