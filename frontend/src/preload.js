const { contextBridge, ipcRenderer } = require("electron");

contextBridge.exposeInMainWorld("electronAPI", {
  // Auth — login & registration are served by Django's built-in auth views.
  // Electron only handles navigation, token hand-off, and logout.
  navigateToChat: () => ipcRenderer.invoke("auth:navigate-chat"),
  storeTokens: (tokens) => ipcRenderer.invoke("auth:store-tokens", tokens),
  logout: () => ipcRenderer.invoke("auth:logout"),

  // Threads
  getThreads: () => ipcRenderer.invoke("threads:get-all"),
  createThread: () => ipcRenderer.invoke("threads:create"),
  getThread: (threadId) => ipcRenderer.invoke("threads:get", threadId),
  renameThread: (threadId, title) =>
    ipcRenderer.invoke("threads:rename", threadId, title),
  deleteThread: (threadId) => ipcRenderer.invoke("threads:delete", threadId),

  // Files
  pickFiles: () => ipcRenderer.invoke("files:pick"),

  // Chat
  sendMessage: (threadId, message, files, mode) =>
    ipcRenderer.invoke("chat:send", threadId, message, files, mode),

  // RAG
  uploadDocument: (filePath) => ipcRenderer.invoke("rag:upload", filePath),
  pickFolder: () => ipcRenderer.invoke("rag:pick-folder"),
});
