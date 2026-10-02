import test from "node:test";
import assert from "node:assert/strict";
import { LocalWebSocketSpeechProvider, parseLocalEvent } from "../src/lib/speech/local-websocket-provider";

test("local transcript event maps to a transcript draft", () => {
  const event = parseLocalEvent(JSON.stringify({ type: "transcript", id: "l1", text: "नमस्ते", speaker: "PATIENT", timestamp: "2026-09-26T10:00:00Z", sequence_number: 3 }));
  assert.deepEqual(event, { id: "l1", text: "नमस्ते", speaker: "PATIENT", timestamp: "2026-09-26T10:00:00Z", sequence_number: 3 });
});

test("local transcript event preserves the detected language code", () => {
  const event = parseLocalEvent(JSON.stringify({ type: "transcript", id: "te-1", text: "నమస్కారం", speaker: "PATIENT", timestamp: "00:00:00", sequence_number: 0, language_code: "te" }));
  assert.equal(event?.language_code, "te");
});

test("local error event preserves exact backend diagnostics", () => {
  const event = parseLocalEvent(JSON.stringify({ type: "error", category: "PIPELINE", message: "WhisperX dependency unavailable: No module named whisperx" }));
  assert.equal(event?.error, "WhisperX dependency unavailable: No module named whisperx");
});

test("non-transcript status events do not create transcript rows", () => {
  assert.equal(parseLocalEvent(JSON.stringify({ type: "status", timings: { vad_ms: 1 } })), null);
});

test("local microphone waits for the warmed server-ready event before streaming audio", async () => {
  const originalNavigator = Object.getOwnPropertyDescriptor(globalThis, "navigator");
  const originalAudioContext = Object.getOwnPropertyDescriptor(globalThis, "AudioContext");
  const originalWebSocket = Object.getOwnPropertyDescriptor(globalThis, "WebSocket");
  const originalWindow = Object.getOwnPropertyDescriptor(globalThis, "window");
  let socket: FakeWebSocket | undefined;
  let processor: { onaudioprocess: ((event: { inputBuffer: { getChannelData(channel: number): Float32Array } }) => void) | null } | undefined;

  class FakeWebSocket {
    static readonly OPEN = 1;
    readyState = 0;
    onopen?: () => void;
    onerror?: () => void;
    onmessage?: (event: { data: string }) => void;
    onclose?: () => void;
    binaryFrames = 0;

    constructor() {
      // Test harness exposes the instantiated socket to the assertion below.
      // eslint-disable-next-line @typescript-eslint/no-this-alias
      socket = this;
      queueMicrotask(() => {
        this.readyState = FakeWebSocket.OPEN;
        this.onopen?.();
      });
    }

    send(data: string | ArrayBuffer) {
      if (typeof data !== "string") this.binaryFrames += 1;
    }

    emitReady() { this.onmessage?.({ data: JSON.stringify({ type: "ready" }) }); }
    close() { this.readyState = 3; this.onclose?.(); }
  }

  class FakeAudioContext {
    sampleRate = 16_000;
    destination = {};
    createMediaStreamSource() { return { connect() {}, disconnect() {} }; }
    createScriptProcessor() {
      processor = { onaudioprocess: null };
      return { connect() {}, disconnect() {}, get onaudioprocess() { return processor?.onaudioprocess ?? null; }, set onaudioprocess(value) { if (processor) processor.onaudioprocess = value; } };
    }
    close() { return Promise.resolve(); }
  }

  Object.defineProperty(globalThis, "navigator", { configurable: true, value: { mediaDevices: { getUserMedia: async () => ({ getTracks: () => [{ stop() {} }] }) } } });
  Object.defineProperty(globalThis, "AudioContext", { configurable: true, value: FakeAudioContext });
  Object.defineProperty(globalThis, "WebSocket", { configurable: true, value: FakeWebSocket });
  Object.defineProperty(globalThis, "window", { configurable: true, value: globalThis });

  try {
    const provider = new LocalWebSocketSpeechProvider("wait-for-ready");
    let started = false;
    const start = provider.start(() => {}).then(() => { started = true; });
    await new Promise((resolve) => setTimeout(resolve, 0));
    assert.equal(started, false);
    assert.equal(socket?.binaryFrames, 0);
    socket?.emitReady();
    await start;
    processor?.onaudioprocess?.({ inputBuffer: { getChannelData: () => new Float32Array(128) } });
    assert.equal(socket?.binaryFrames, 1);
  } finally {
    for (const [key, descriptor] of [["navigator", originalNavigator], ["AudioContext", originalAudioContext], ["WebSocket", originalWebSocket], ["window", originalWindow]] as const) {
      if (descriptor) Object.defineProperty(globalThis, key, descriptor);
      else Reflect.deleteProperty(globalThis, key);
    }
  }
});

test("local stop waits for the server final-pass acknowledgment before closing audio", async () => {
  const originalNavigator = Object.getOwnPropertyDescriptor(globalThis, "navigator");
  const originalAudioContext = Object.getOwnPropertyDescriptor(globalThis, "AudioContext");
  const originalWebSocket = Object.getOwnPropertyDescriptor(globalThis, "WebSocket");
  const originalWindow = Object.getOwnPropertyDescriptor(globalThis, "window");
  let acknowledgedAt = 0;
  const websocketState = { closedAt: 0 };

  class FakeWebSocket {
    static readonly OPEN = 1;
    readyState = 0;
    onopen?: () => void;
    onerror?: () => void;
    onmessage?: (event: { data: string }) => void;
    onclose?: () => void;

    constructor() {
      queueMicrotask(() => {
        this.readyState = FakeWebSocket.OPEN;
        this.onopen?.();
        this.onmessage?.({ data: JSON.stringify({ type: "ready" }) });
      });
    }

    send(data: string | ArrayBuffer) {
      if (typeof data === "string" && JSON.parse(data).type === "stop") {
        setTimeout(() => {
          if (this.readyState !== FakeWebSocket.OPEN) return;
          acknowledgedAt = Date.now();
          this.onmessage?.({ data: JSON.stringify({ type: "stopped" }) });
        }, 2_500);
      }
    }

    close() {
      this.readyState = 3;
      websocketState.closedAt = Date.now();
      this.onclose?.();
    }
  }

  class FakeAudioContext {
    sampleRate = 16_000;
    destination = {};
    createMediaStreamSource() { return { connect() {}, disconnect() {} }; }
    createScriptProcessor() { return { connect() {}, disconnect() {}, onaudioprocess: null }; }
    close() { return Promise.resolve(); }
  }

  Object.defineProperty(globalThis, "navigator", {
    configurable: true,
    value: { mediaDevices: { getUserMedia: async () => ({ getTracks: () => [{ stop() {} }] }) } },
  });
  Object.defineProperty(globalThis, "AudioContext", { configurable: true, value: FakeAudioContext });
  Object.defineProperty(globalThis, "WebSocket", { configurable: true, value: FakeWebSocket });
  Object.defineProperty(globalThis, "window", { configurable: true, value: globalThis });

  try {
    const provider = new LocalWebSocketSpeechProvider("slow-final-pass");
    await provider.start(() => {});
    let stopError = "";
    const stopped = provider.stop().then(() => true, (error: unknown) => {
      stopError = error instanceof Error ? error.message : String(error);
      return false;
    });
    const result = await Promise.race([
      stopped,
      new Promise<false>((resolve) => setTimeout(() => resolve(false), 4_000)),
    ]);

    assert.equal(result, true, `stop should wait for the delayed server acknowledgment (${stopError})`);
    assert.ok(acknowledgedAt > 0);
    assert.ok(websocketState.closedAt >= acknowledgedAt, "the client must close only after reconciliation completes");
  } finally {
    for (const [key, descriptor] of [
      ["navigator", originalNavigator],
      ["AudioContext", originalAudioContext],
      ["WebSocket", originalWebSocket],
      ["window", originalWindow],
    ] as const) {
      if (descriptor) Object.defineProperty(globalThis, key, descriptor);
      else Reflect.deleteProperty(globalThis, key);
    }
  }
});
