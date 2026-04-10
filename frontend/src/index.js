const { app, BrowserWindow, ipcMain, Menu, dialog } = require("electron");
const path = require("node:path");
const fs = require("node:fs");
const apiService = require("./services/apiService");

let mainWindow;
let tokenStore = { accessToken: null, refreshToken: null };

const createWindow = () => {
  mainWindow = new BrowserWindow({
    width: 900,
    height: 650,
    webPreferences: {
      preload: path.join(__dirname, "preload.js"),
    },
  });

  mainWindow.loadFile(path.join(__dirname, "auth.html"));

  mainWindow.webContents.on("context-menu", () => {
    Menu.buildFromTemplate([
      {
        label: "Developer Tools",
        click: () => mainWindow.webContents.openDevTools(),
      },
    ]).popup(mainWindow);
  });
};

if (require("electron-squirrel-startup")) {
  app.quit();
}

app.whenReady().then(() => {
  // ---- Auth handlers ----
  ipcMain.handle("auth:login", async (_event, email, password) => {
    try {
      const result = await apiService.login(email, password);
      if (result && result.success && result.body) {
        tokenStore.accessToken = result.body.access_token;
        tokenStore.refreshToken = result.body.refresh_token;
      }
      return result;
    } catch (error) {
      return { success: false, message: "Login failed. " + error.message };
    }
  });

  ipcMain.handle("auth:register", async (_event, username, email, password) => {
    try {
      return await apiService.register(username, email, password);
    } catch (error) {
      return { success: false, message: "Registration failed. " + error.message };
    }
  });

  ipcMain.handle("auth:navigate-chat", async () => {
    if (mainWindow) {
      mainWindow.loadFile(path.join(__dirname, "index.html"));
    }
  });

  ipcMain.handle("auth:store-tokens", async (_event, tokens) => {
    tokenStore.accessToken = tokens.accessToken || null;
    tokenStore.refreshToken = tokens.refreshToken || null;
    return { success: true };
  });

  ipcMain.handle("auth:logout", async () => {
    try {
      await apiService.logout(tokenStore.refreshToken, tokenStore.accessToken);
    } catch (_) {
      // Best-effort server-side blacklist; clear local state regardless
    }
    tokenStore.accessToken = null;
    tokenStore.refreshToken = null;
    if (mainWindow) {
      mainWindow.loadFile(path.join(__dirname, "auth.html"));
    }
    return { success: true };
  });

  // ---- Thread handlers ----
  ipcMain.handle("threads:get-all", async () => {
    return await apiService.getThreads(tokenStore.accessToken);
  });

  ipcMain.handle("threads:create", async () => {
    return await apiService.createThread(tokenStore.accessToken);
  });

  ipcMain.handle("threads:get", async (_event, threadId) => {
    return await apiService.getThread(threadId, tokenStore.accessToken);
  });

  ipcMain.handle("threads:rename", async (_event, threadId, title) => {
    return await apiService.renameThread(threadId, title, tokenStore.accessToken);
  });

  ipcMain.handle("threads:delete", async (_event, threadId) => {
    return await apiService.deleteThread(threadId, tokenStore.accessToken);
  });

  // ---- File handler ----
  ipcMain.handle("files:pick", async () => {
    const result = await dialog.showOpenDialog(mainWindow, {
      properties: ["openFile", "multiSelections"],
    });
    if (result.canceled) return [];

    return result.filePaths.map((filePath) => {
      const name = path.basename(filePath);
      const ext = path.extname(filePath).toLowerCase().slice(1);
      const size = fs.statSync(filePath).size;

      let type = "other";
      if (["jpg", "jpeg", "png", "gif", "bmp", "webp", "svg", "ico"].includes(ext)) type = "image";
      else if (["mp3", "wav", "ogg", "flac", "aac", "m4a", "wma"].includes(ext)) type = "audio";
      else if (["mp4", "webm", "avi", "mov", "mkv", "wmv"].includes(ext)) type = "video";
      else if (ext === "pdf") type = "pdf";
      else if (["doc", "docx", "ppt", "pptx", "xls", "xlsx", "odt", "ods", "odp"].includes(ext)) type = "document";
      else if (["js", "ts", "jsx", "tsx", "py", "java", "c", "cpp", "h", "cs", "go", "rb", "php", "html", "css", "json", "xml", "yaml", "yml", "md", "txt", "sh", "bat", "sql", "rs", "swift", "kt", "r", "lua"].includes(ext)) type = "code";

      let dataUrl = null;
      if (type === "image" && size < 10 * 1024 * 1024) {
        const buffer = fs.readFileSync(filePath);
        const mimeMap = { jpg: "image/jpeg", jpeg: "image/jpeg", png: "image/png", gif: "image/gif", bmp: "image/bmp", webp: "image/webp", svg: "image/svg+xml", ico: "image/x-icon" };
        dataUrl = `data:${mimeMap[ext] || "image/png"};base64,${buffer.toString("base64")}`;
      }

      let textContent = null;
      if (type === "code" || ["txt", "md", "csv", "log", "ini", "cfg", "conf", "env"].includes(ext)) {
        try {
          textContent = fs.readFileSync(filePath, "utf-8");
        } catch (_) {}
      }

      return { name, path: filePath, ext, size, type, dataUrl, textContent };
    });
  });

  // ---- RAG folder handler ----
  ipcMain.handle("rag:pick-folder", async () => {
    const result = await dialog.showOpenDialog(mainWindow, {
      properties: ["openDirectory"],
    });
    if (result.canceled || result.filePaths.length === 0) return [];

    const folderPath = result.filePaths[0];
    const ragExts = [".pdf", ".txt", ".docx", ".pptx", ".xlsx"];
    const found = [];

    function walk(dir) {
      let entries;
      try {
        entries = fs.readdirSync(dir, { withFileTypes: true });
      } catch (_) {
        return;
      }
      for (const entry of entries) {
        const fullPath = path.join(dir, entry.name);
        if (entry.isDirectory()) {
          walk(fullPath);
        } else if (entry.isFile()) {
          const ext = path.extname(entry.name).toLowerCase();
          if (ragExts.includes(ext)) {
            found.push({
              name: entry.name,
              path: fullPath,
              ext: ext.slice(1),
            });
          }
        }
      }
    }

    walk(folderPath);
    return { folder: path.basename(folderPath), files: found };
  });

  // ---- Chat handler ----
  ipcMain.handle("chat:send", async (_event, threadId, message, files, mode) => {
    try {
      return await apiService.sendMessage(
        threadId,
        message,
        tokenStore.accessToken,
        files,
        mode
      );
    } catch (error) {
      return {
        message: "I'm sorry, I encountered an error processing your request.",
        tokens: null,
        sources: [],
      };
    }
  });

  // ---- RAG handler ----
  ipcMain.handle("rag:upload", async (_event, filePath) => {
    try {
      return await apiService.uploadDocument(filePath, tokenStore.accessToken);
    } catch (error) {
      return { success: false, message: error.message };
    }
  });

  createWindow();

  app.on("activate", () => {
    if (BrowserWindow.getAllWindows().length === 0) {
      createWindow();
    }
  });
});

app.on("window-all-closed", () => {
  if (process.platform !== "darwin") {
    app.quit();
  }
});
