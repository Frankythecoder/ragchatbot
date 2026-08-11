// Web API client — replaces the Electron `window.electronAPI` IPC bridge.
// All requests are same-origin and authenticated via Django's session cookie.
// CSRF token is rendered into the page by Django and exposed as
// `window.CORTEX_CSRF_TOKEN`.
(function () {
  const ns = (window.App = window.App || {});

  function csrfToken() {
    return window.CORTEX_CSRF_TOKEN || "";
  }

  async function request(path, options = {}) {
    const opts = Object.assign({ credentials: "same-origin" }, options);
    opts.headers = Object.assign({}, options.headers || {});
    const method = (opts.method || "GET").toUpperCase();
    if (method !== "GET" && method !== "HEAD") {
      opts.headers["X-CSRFToken"] = csrfToken();
    }
    const res = await fetch(path, opts);
    if (res.status === 401 || res.status === 403) {
      // Session expired — bounce back to login.
      window.location.href = "/accounts/login/?next=/";
      throw new Error(`Auth required (${res.status})`);
    }
    return res;
  }

  async function getThreads() {
    try {
      const res = await request("/api/threads/");
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      return await res.json();
    } catch (e) {
      console.error("getThreads:", e);
      return [];
    }
  }

  async function createThread() {
    try {
      const res = await request("/api/threads/", { method: "POST" });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      return await res.json();
    } catch (e) {
      console.error("createThread:", e);
      return null;
    }
  }

  async function getThread(threadId) {
    try {
      const res = await request(`/api/threads/${threadId}/`);
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      return await res.json();
    } catch (e) {
      console.error("getThread:", e);
      return null;
    }
  }

  async function renameThread(threadId, title) {
    try {
      const res = await request(`/api/threads/${threadId}/`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ title }),
      });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      return await res.json();
    } catch (e) {
      console.error("renameThread:", e);
      return null;
    }
  }

  async function deleteThread(threadId) {
    try {
      const res = await request(`/api/threads/${threadId}/`, { method: "DELETE" });
      return res.ok || res.status === 204;
    } catch (e) {
      console.error("deleteThread:", e);
      return false;
    }
  }

  async function sendMessage(threadId, message, files = []) {
    try {
      const res = await request(`/api/threads/${threadId}/chat/`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ message, files: files || [] }),
      });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      return await res.json();
    } catch (e) {
      console.error("sendMessage:", e);
      return {
        message: `Could not reach the backend.\n\nError: ${e.message}`,
        tokens: null,
        thread_title: null,
        sources: [],
        retrieved_chunks: [],
      };
    }
  }

  // Browser equivalent of the Electron file-pick handler: takes a list of
  // browser File objects and produces the same descriptor shape the rest of
  // the UI expects ({ name, ext, size, type, dataUrl?, textContent?, file }).
  // The original `path` field is dropped (browsers don't expose it); the raw
  // File is kept on the descriptor so uploadDocument can stream it.
  async function describeFiles(fileList) {
    const out = [];
    for (const file of Array.from(fileList || [])) {
      const name = file.name;
      const ext = (name.includes(".") ? name.split(".").pop() : "").toLowerCase();
      const size = file.size;

      let type = "other";
      if (["jpg", "jpeg", "png", "gif", "bmp", "webp", "svg", "ico"].includes(ext)) type = "image";
      else if (["mp3", "wav", "ogg", "flac", "aac", "m4a", "wma"].includes(ext)) type = "audio";
      else if (["mp4", "webm", "avi", "mov", "mkv", "wmv"].includes(ext)) type = "video";
      else if (ext === "pdf") type = "pdf";
      else if (["doc", "docx", "ppt", "pptx", "xls", "xlsx", "odt", "ods", "odp"].includes(ext)) type = "document";
      else if (["js", "ts", "jsx", "tsx", "py", "java", "c", "cpp", "h", "cs", "go", "rb", "php", "html", "css", "json", "xml", "yaml", "yml", "md", "txt", "sh", "bat", "sql", "rs", "swift", "kt", "r", "lua"].includes(ext)) type = "code";

      let dataUrl = null;
      if (type === "image" && size < 10 * 1024 * 1024) {
        dataUrl = await readAsDataURL(file);
      }

      let textContent = null;
      if (type === "code" || ["txt", "md", "csv", "log", "ini", "cfg", "conf", "env"].includes(ext)) {
        try {
          textContent = await readAsText(file);
        } catch (_) {}
      }

      out.push({ name, ext, size, type, dataUrl, textContent, file });
    }
    return out;
  }

  function readAsDataURL(file) {
    return new Promise((resolve, reject) => {
      const reader = new FileReader();
      reader.onload = () => resolve(reader.result);
      reader.onerror = () => reject(reader.error);
      reader.readAsDataURL(file);
    });
  }

  function readAsText(file) {
    return new Promise((resolve, reject) => {
      const reader = new FileReader();
      reader.onload = () => resolve(reader.result);
      reader.onerror = () => reject(reader.error);
      reader.readAsText(file);
    });
  }

  // Folder pick (via <input webkitdirectory>) — keep the same shape the
  // Electron handler returned: { folder, files: [{ name, path, ext }] }.
  // Only the RAG-supported extensions are kept.
  function describeFolder(fileList) {
    const files = Array.from(fileList || []);
    if (files.length === 0) return { folder: "", files: [] };

    const ragExts = ["pdf", "txt", "docx", "pptx", "xlsx"];
    const out = [];
    let folder = "";

    for (const f of files) {
      // webkitRelativePath gives "folderName/.../file.ext"
      const rel = f.webkitRelativePath || f.name;
      if (!folder && rel.includes("/")) {
        folder = rel.split("/")[0];
      }
      const ext = (f.name.includes(".") ? f.name.split(".").pop() : "").toLowerCase();
      if (ragExts.includes(ext)) {
        out.push({ name: f.name, path: rel, ext, file: f });
      }
    }

    if (!folder) folder = "selection";
    return { folder, files: out };
  }

  async function uploadDocument(fileDescriptor) {
    // fileDescriptor: { name, file, path? }
    const formData = new FormData();
    formData.append("file", fileDescriptor.file, fileDescriptor.name);
    formData.append("file_path", fileDescriptor.path || fileDescriptor.name);

    try {
      const res = await request("/api/upload-document/", {
        method: "POST",
        body: formData,
      });
      if (!res.ok) {
        let detail = `HTTP ${res.status}`;
        try {
          const data = await res.json();
          detail = data.detail || detail;
        } catch (_) {}
        throw new Error(detail);
      }
      return await res.json();
    } catch (e) {
      console.error("uploadDocument:", e);
      return { success: false, message: e.message };
    }
  }

  ns.Api = {
    getThreads,
    createThread,
    getThread,
    renameThread,
    deleteThread,
    sendMessage,
    describeFiles,
    describeFolder,
    uploadDocument,
  };
})();
