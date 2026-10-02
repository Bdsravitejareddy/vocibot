const { spawn: defaultSpawn } = require("node:child_process");
const { mkdirSync } = require("node:fs");
const { join } = require("node:path");

const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));

async function defaultFetchHealth() {
  try {
    const [api, web] = await Promise.all([
      fetch("http://127.0.0.1:8000/health", { signal: AbortSignal.timeout(700) }),
      fetch("http://127.0.0.1:3000", { signal: AbortSignal.timeout(700) }),
    ]);
    return api.ok && web.ok;
  } catch {
    return false;
  }
}

async function startRuntime({
  spawn = defaultSpawn,
  appDataPath,
  resourcesPath,
  fetchHealth = defaultFetchHealth,
  pollIntervalMs = 250,
  timeoutMs = 30_000,
  shutdownGraceMs = 1_500,
} = {}) {
  if (!appDataPath || !resourcesPath) throw new Error("appDataPath and resourcesPath are required");
  const children = [];
  let launchFailure;
  const apiPath = join(resourcesPath, "backend", "vocibot-api", process.platform === "win32" ? "vocibot-api.exe" : "vocibot-api");
  const webPath = join(resourcesPath, "web", "server.js");
  const launch = (command, args, options) => {
    const child = spawn(command, args, { stdio: "ignore", ...options });
    child.once?.("error", (error) => { launchFailure = error; });
    children.push(child);
    return child;
  };
  const stop = async () => {
    const owned = children.splice(0);
    const stopped = owned.map((child) => new Promise((resolve) => {
      if (child.exitCode != null || child.signalCode != null) return resolve();
      let settled = false;
      let graceTimer;
      const finish = () => {
        if (settled) return;
        settled = true;
        clearTimeout(graceTimer);
        child.removeListener?.("exit", finish);
        child.removeListener?.("error", finish);
        resolve();
      };
      child.once?.("exit", finish);
      child.once?.("error", finish);
      graceTimer = setTimeout(() => {
        if (child.exitCode == null && child.signalCode == null) {
          child.kill("SIGKILL");
        } else finish();
      }, shutdownGraceMs);
      child.kill("SIGTERM");
    }));
    await Promise.all(stopped);
  };

  try {
    mkdirSync(appDataPath, { recursive: true });
    launch(apiPath, [], { cwd: join(resourcesPath, "backend"), env: { ...process.env, AI_MODE: "local", HOST: "127.0.0.1", PORT: "8000", DATABASE_URL: `sqlite:///${join(appDataPath, "vocibot.sqlite")}`, OLLAMA_BASE_URL: "http://127.0.0.1:11434", NO_PROXY: "127.0.0.1,localhost", no_proxy: "127.0.0.1,localhost", HF_HUB_OFFLINE: "1", TRANSFORMERS_OFFLINE: "1", HF_HUB_DISABLE_TELEMETRY: "1" } });
    launch(process.execPath, [webPath], { cwd: join(resourcesPath, "web"), env: { ...process.env, ELECTRON_RUN_AS_NODE: "1", HOSTNAME: "127.0.0.1", PORT: "3000", NEXT_PUBLIC_API_URL: "http://127.0.0.1:8000" } });
    const deadline = Date.now() + timeoutMs;
    while (Date.now() < deadline) {
      if (launchFailure) throw new Error(`Unable to start a local runtime process: ${launchFailure.message}`);
      if (children.some((child) => child.exitCode != null || child.signalCode != null)) throw new Error("A local runtime process exited during startup");
      if (await fetchHealth()) return { stop };
      await sleep(pollIntervalMs);
    }
    throw new Error("Local backend health check timed out on 127.0.0.1:8000");
  } catch (error) {
    await stop();
    throw error;
  }
}

module.exports = { startRuntime };
