// VociBot Enterprise - one computer, several clinicians: each signs in with
// their own account. The bundled server listens on this computer only.
const { app, BrowserWindow, dialog, session } = require("electron");
const { startServer } = require("./server-runtime.cjs");

let server;
let quitting = false;

if (!app.requestSingleInstanceLock()) app.quit();

async function createWindow() {
  server = await startServer({ resourcesPath: process.resourcesPath });
  const window = new BrowserWindow({ width: 1440, height: 960, minWidth: 1100, minHeight: 720, title: "VociBot Enterprise", webPreferences: { nodeIntegration: false, contextIsolation: true, sandbox: true } });
  // Only the local VociBot page may use the microphone.
  session.defaultSession.setPermissionRequestHandler((webContents, permission, callback) => callback(permission === "media" && webContents.getURL().startsWith(server.origin)));
  window.webContents.setWindowOpenHandler(() => ({ action: "deny" }));
  await window.loadURL(server.origin);
}

app.on("second-instance", () => { const [window] = BrowserWindow.getAllWindows(); if (window) { if (window.isMinimized()) window.restore(); window.focus(); } });
app.whenReady().then(async () => {
  try { await createWindow(); }
  catch (error) { await dialog.showMessageBox({ type: "error", title: "VociBot could not start", message: String(error instanceof Error ? error.message : error) }); app.quit(); }
});
app.on("window-all-closed", () => app.quit());
app.on("before-quit", (event) => {
  if (!server || quitting) return;
  event.preventDefault();
  quitting = true;
  void server.stop().finally(() => { server = undefined; app.quit(); });
});
