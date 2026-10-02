import assert from "node:assert/strict";
import { EventEmitter } from "node:events";
import test from "node:test";

import { startRuntime } from "../../desktop/runtime-manager.cjs";

test("runtime starts loopback children and stops only processes it owns", async () => {
  const previousOllamaUrl = process.env.OLLAMA_BASE_URL;
  process.env.OLLAMA_BASE_URL = "https://example.invalid";
  const calls: Array<{ command: string; args: string[]; options: Record<string, unknown>; child: EventEmitter & { kill: (signal?: string) => void } }> = [];
  const spawn = (command: string, args: string[], options: Record<string, unknown>) => {
    const child = Object.assign(new EventEmitter(), { kill: () => { child.emit("exit", 0); } });
    calls.push({ command, args, options, child });
    return child;
  };
  const runtime = await startRuntime({
    spawn,
    appDataPath: "/tmp/vocibot-test",
    resourcesPath: "/resources",
    fetchHealth: async () => true,
    pollIntervalMs: 1,
    shutdownGraceMs: 5,
  });
  assert.equal(calls.length, 2);
  assert.equal((calls[0].options.env as NodeJS.ProcessEnv).HOST, "127.0.0.1");
  assert.equal((calls[0].options.env as NodeJS.ProcessEnv).DATABASE_URL, "sqlite:////tmp/vocibot-test/vocibot.sqlite");
  assert.equal((calls[0].options.env as NodeJS.ProcessEnv).RECORDINGS_DIR, "/tmp/vocibot-test/recordings");
  assert.equal((calls[0].options.env as NodeJS.ProcessEnv).OLLAMA_BASE_URL, "http://127.0.0.1:11434");
  await runtime.stop();
  if (previousOllamaUrl === undefined) delete process.env.OLLAMA_BASE_URL;
  else process.env.OLLAMA_BASE_URL = previousOllamaUrl;
  assert.equal(calls.every(({ child }) => child.listenerCount("exit") === 0), true);
});

test("runtime stops owned children when health check times out", async () => {
  const signals: string[] = [];
  const createChild = () => {
    const child = new EventEmitter();
    return Object.assign(child, { kill: (signal?: string) => {
      if (!signal) return;
      signals.push(signal);
      if (signal === "SIGKILL") child.emit("exit", null, "SIGKILL");
    } });
  };
  const safeSpawn = () => createChild();
  await assert.rejects(startRuntime({
    spawn: safeSpawn,
    appDataPath: "/tmp/vocibot-test",
    resourcesPath: "/resources",
    fetchHealth: async () => false,
    pollIntervalMs: 1,
    timeoutMs: 4,
    shutdownGraceMs: 5,
  }), /health check timed out/);
  assert.deepEqual(signals.filter((signal) => signal === "SIGTERM").length, 2);
  assert.deepEqual(signals.filter((signal) => signal === "SIGKILL").length, 2);
});
