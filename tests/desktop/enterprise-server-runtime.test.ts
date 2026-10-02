import test from "node:test";
import assert from "node:assert/strict";
import { EventEmitter } from "node:events";
// eslint-disable-next-line @typescript-eslint/no-require-imports
const { startServer } = require("../../desktop/enterprise/server-runtime.cjs");

class FakeChild extends EventEmitter {
  exitCode: number | null = null;
  signalCode: string | null = null;
  killed = false;
  kill() { this.killed = true; this.exitCode = 0; this.emit("exit", 0); return true; }
}

test("the one-computer app starts the bundled server on this computer only and waits for it", async () => {
  const calls: Array<{ command: string; args: string[]; options: { env: NodeJS.ProcessEnv; windowsHide: boolean } }> = [];
  let checks = 0;
  const child = new FakeChild();
  const server = await startServer({
    resourcesPath: "C:\\Program Files\\VociBot Enterprise\\resources",
    platform: "win32",
    spawn: (command: string, args: string[], options: { env: NodeJS.ProcessEnv; windowsHide: boolean }) => { calls.push({ command, args, options }); return child; },
    fetchHealth: async (url: string) => { assert.equal(url, "http://127.0.0.1:8765/health"); checks += 1; return checks >= 3; },
    pollIntervalMs: 1,
  });
  assert.equal(server.origin, "http://127.0.0.1:8765");
  assert.match(calls[0].command, /server[\\/]vocibot-server[\\/]vocibot-server\.exe$/);
  assert.deepEqual(calls[0].args, ["serve", "--edition", "one-computer", "--port", "8765"]);
  assert.equal(calls[0].options.env.VOCIBOT_EDITION, "one-computer");
  assert.equal(calls[0].options.windowsHide, true);
  await server.stop();
  assert.equal(child.killed, true);
});

test("a server that exits during startup is reported instead of waiting forever", async () => {
  const child = new FakeChild();
  child.exitCode = 1;
  await assert.rejects(startServer({ resourcesPath: "/r", spawn: () => child, fetchHealth: async () => false, pollIntervalMs: 1 }), /stopped during startup/);
});
