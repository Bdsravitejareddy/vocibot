const { spawn: defaultSpawn } = require("node:child_process");
const { join } = require("node:path");

const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));

/** The bundled VociBot Enterprise server for this edition, started privately on this computer. */
async function startServer({
  spawn = defaultSpawn,
  resourcesPath,
  port = 8765,
  fetchHealth = async (url) => { try { return (await fetch(url, { signal: AbortSignal.timeout(1000) })).ok; } catch { return false; } },
  timeoutMs = 120_000,
  pollIntervalMs = 300,
  platform = process.platform,
} = {}) {
  if (!resourcesPath) throw new Error("resourcesPath is required");
  const executable = join(resourcesPath, "server", "vocibot-server", platform === "win32" ? "vocibot-server.exe" : "vocibot-server");
  const origin = `http://127.0.0.1:${port}`;
  let failure;
  const child = spawn(executable, ["serve", "--edition", "one-computer", "--port", String(port)], {
    stdio: "ignore",
    windowsHide: true,
    env: { ...process.env, VOCIBOT_EDITION: "one-computer", NO_PROXY: "127.0.0.1,localhost", no_proxy: "127.0.0.1,localhost" },
  });
  child.once?.("error", (error) => { failure = error; });
  const stop = () => new Promise((resolve) => {
    if (child.exitCode != null || child.signalCode != null) return resolve();
    const timer = setTimeout(() => { child.kill("SIGKILL"); resolve(); }, 5000);
    child.once?.("exit", () => { clearTimeout(timer); resolve(); });
    child.kill();
  });
  const deadline = Date.now() + timeoutMs;
  while (Date.now() < deadline) {
    if (failure) throw new Error(`VociBot could not start its local server: ${failure.message}`);
    if (child.exitCode != null) throw new Error("The VociBot server stopped during startup. Is another copy already running?");
    if (await fetchHealth(`${origin}/health`)) return { origin, stop };
    await sleep(pollIntervalMs);
  }
  await stop();
  throw new Error("The VociBot server did not start in time.");
}

module.exports = { startServer };
