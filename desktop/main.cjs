const { app, BrowserWindow, dialog, session } = require("electron");
const { join } = require("node:path");
const { startRuntime } = require("./runtime-manager.cjs");

let runtime;
let shuttingDown = false;
async function createWindow() {
  if (app.isPackaged) runtime = await startRuntime({ appDataPath: app.getPath("userData"), resourcesPath: process.resourcesPath });
  const window = new BrowserWindow({ width: 1440, height: 960, minWidth: 1100, minHeight: 720, webPreferences: { preload: join(__dirname, "preload.cjs"), nodeIntegration: false, contextIsolation: true, sandbox: true } });
  await window.loadURL("http://127.0.0.1:3000");
}
app.whenReady().then(async () => {
  session.defaultSession.setPermissionRequestHandler((webContents, permission, callback) => callback(permission === "media" && webContents.getURL().startsWith("http://127.0.0.1:3000")));
  try { await createWindow(); }
  catch (error) { await dialog.showMessageBox({ type: "error", title: "Gaya could not start", message: String(error) }); app.quit(); }
});
app.on("window-all-closed", () => app.quit());
app.on("before-quit", (event) => {
  if (!runtime || shuttingDown) return;
  event.preventDefault();
  shuttingDown = true;
  void runtime.stop().catch((error) => console.error("Failed while stopping local services", error)).finally(() => { runtime = undefined; app.quit(); });
});
