const { contextBridge } = require("electron");

contextBridge.exposeInMainWorld("vociDesktop", Object.freeze({ platform: process.platform, runtime: "local-loopback" }));
