(function () {
  const ns = (window.App = window.App || {});

  let currentThread = null; // { id, title, messages: [] }

  let chatContainer,
    mainContent,
    messageInput,
    sendButton,
    chatHistoryList,
    chatSearch;

  let stagedFiles = [];
  let selectedMode = "normal";

  // ---- RAG indexing UI ----

  async function indexFilesWithProgress(files) {
    const staging = document.getElementById("file-staging");
    staging.style.display = "flex";
    let totalChunks = 0;

    for (const file of files) {
      const chip = document.createElement("div");
      chip.className = "file-chip rag-indexing";
      const icon = document.createElement("span");
      icon.className = "file-chip-icon";
      icon.textContent = getFileIcon(file.type || (file.ext === "pdf" ? "pdf" : "code"));
      chip.appendChild(icon);
      const name = document.createElement("span");
      name.className = "file-chip-name";
      name.textContent = `Indexing ${file.name}...`;
      chip.appendChild(name);
      staging.appendChild(chip);

      const result = await window.electronAPI.uploadDocument(file.path);
      if (result && result.success) {
        name.textContent = `${file.name} (${result.chunks_indexed} chunks)`;
        chip.classList.remove("rag-indexing");
        chip.classList.add("rag-indexed");
        totalChunks += result.chunks_indexed;
      } else {
        name.textContent = `${file.name} - failed`;
        chip.classList.remove("rag-indexing");
        chip.classList.add("rag-index-error");
      }
    }

    // Auto-clear indexed file chips after 4 seconds
    setTimeout(() => {
      staging.querySelectorAll(".rag-indexed, .rag-index-error").forEach((el) => el.remove());
      if (staging.children.length === 0) {
        staging.style.display = "none";
      }
    }, 4000);

    return totalChunks;
  }

  // ---- RAG attribution rendering ----

  function appendRAGAttribution(messageDiv, sources, chunks) {
    if (chunks && chunks.length > 0) {
      const chunksDiv = document.createElement("div");
      chunksDiv.className = "retrieved-chunks";
      const chunksLabel = document.createElement("strong");
      chunksLabel.textContent = "Retrieved Context:";
      chunksDiv.appendChild(chunksLabel);
      const chunksList = document.createElement("ul");
      chunksList.className = "chunks-list";
      chunks.forEach((chunk) => {
        const li = document.createElement("li");
        const truncated = chunk.length > 200 ? chunk.slice(0, 200) + "..." : chunk;
        li.textContent = `"${truncated}"`;
        chunksList.appendChild(li);
      });
      chunksDiv.appendChild(chunksList);
      messageDiv.appendChild(chunksDiv);
    }

    if (sources && sources.length > 0) {
      const sourceDiv = document.createElement("div");
      sourceDiv.className = "source-attribution";
      const label = document.createElement("strong");
      label.textContent = "Sources:";
      sourceDiv.appendChild(label);
      sourceDiv.appendChild(document.createTextNode(" "));
      sources.forEach((s) => {
        const tag = document.createElement("span");
        tag.className = "source-tag";
        tag.textContent = s;
        sourceDiv.appendChild(tag);
      });
      messageDiv.appendChild(sourceDiv);
    }
  }

  // ---- Thinking indicator ----

  function showThinking() {
    const div = document.createElement("div");
    div.className = "message bot-message thinking-indicator";
    div.id = "thinking-indicator";
    div.innerHTML = '<div class="thinking-dots"><span></span><span></span><span></span></div>';
    chatContainer.appendChild(div);
    chatContainer.scrollTop = chatContainer.scrollHeight;
  }

  function removeThinking() {
    const el = document.getElementById("thinking-indicator");
    if (el) el.remove();
  }

  // ---- File handling ----

  function getFileIcon(type) {
    const icons = { image: "\u{1F5BC}", audio: "\u{1F3B5}", video: "\u{1F3AC}", pdf: "\u{1F4D5}", document: "\u{1F4C4}", code: "\u{1F4BB}" };
    return icons[type] || "\u{1F4CE}";
  }

  function formatFileSize(bytes) {
    if (bytes < 1024) return bytes + " B";
    if (bytes < 1024 * 1024) return (bytes / 1024).toFixed(1) + " KB";
    return (bytes / (1024 * 1024)).toFixed(1) + " MB";
  }

  function createAttachments(files) {
    if (!files || files.length === 0) return null;
    const container = document.createElement("div");
    container.className = "message-attachments";

    files.forEach((file) => {
      const el = document.createElement("div");
      if (file.type === "image" && file.dataUrl) {
        el.className = "attachment attachment-img";
        const img = document.createElement("img");
        img.src = file.dataUrl;
        img.className = "attachment-image";
        el.appendChild(img);
      } else {
        el.className = "attachment attachment-file";
        const icon = document.createElement("span");
        icon.className = "attachment-icon";
        icon.textContent = getFileIcon(file.type);
        el.appendChild(icon);
        const name = document.createElement("span");
        name.className = "attachment-name";
        name.textContent = file.name;
        el.appendChild(name);
        const size = document.createElement("span");
        size.className = "attachment-size";
        size.textContent = formatFileSize(file.size);
        el.appendChild(size);
      }
      container.appendChild(el);
    });

    return container;
  }

  function addStagedFiles(files) {
    stagedFiles.push(...files);
    renderStagedFiles();
  }

  function removeStagedFile(index) {
    stagedFiles.splice(index, 1);
    renderStagedFiles();
  }

  function renderStagedFiles() {
    const staging = document.getElementById("file-staging");
    if (stagedFiles.length === 0) {
      staging.innerHTML = "";
      staging.style.display = "none";
      return;
    }
    staging.style.display = "flex";
    staging.innerHTML = "";
    stagedFiles.forEach((file, i) => {
      const chip = document.createElement("div");
      chip.className = "file-chip";

      if (file.type === "image" && file.dataUrl) {
        const thumb = document.createElement("img");
        thumb.src = file.dataUrl;
        thumb.className = "file-chip-thumb";
        chip.appendChild(thumb);
      } else {
        const icon = document.createElement("span");
        icon.className = "file-chip-icon";
        icon.textContent = getFileIcon(file.type);
        chip.appendChild(icon);
      }

      const name = document.createElement("span");
      name.className = "file-chip-name";
      name.textContent = file.name;
      chip.appendChild(name);

      const remove = document.createElement("button");
      remove.className = "file-chip-remove";
      remove.innerHTML = "&times;";
      remove.addEventListener("click", () => removeStagedFile(i));
      chip.appendChild(remove);

      staging.appendChild(chip);
    });
  }

  // ---- Message rendering ----

  function appendMessage(isUser, content, shouldSave = true, files = null) {
    const messageDiv = document.createElement("div");
    messageDiv.className = `message ${isUser ? "user-message" : "bot-message"}`;

    if (isUser && files && files.length > 0) {
      messageDiv.appendChild(createAttachments(files));
    }

    const contentDiv = document.createElement("div");
    contentDiv.className = "message-content";

    if (isUser) {
      contentDiv.textContent = content;
    } else {
      contentDiv.innerHTML = marked.parse(content);
    }

    messageDiv.appendChild(contentDiv);
    chatContainer.appendChild(messageDiv);
    chatContainer.scrollTop = chatContainer.scrollHeight;

    if (shouldSave && currentThread) {
      currentThread.messages.push({ isUser, content });
    }

    return messageDiv;
  }

  function appendTokenInfo(tokens) {
    if (!tokens) return;
    const infoDiv = document.createElement("div");
    infoDiv.className = "token-info";
    infoDiv.textContent = `Tokens: ${tokens.prompt_tokens} prompt + ${tokens.completion_tokens} completion = ${tokens.total_tokens} total`;
    chatContainer.appendChild(infoDiv);
    chatContainer.scrollTop = chatContainer.scrollHeight;
  }

  async function simulateStreaming(element, text) {
    element.innerHTML = "";
    const tokens = text.split(" ");
    let currentText = "";
    for (const token of tokens) {
      currentText += token + " ";
      element.innerHTML = marked.parse(currentText);
      chatContainer.scrollTop = chatContainer.scrollHeight;
      await new Promise((resolve) => setTimeout(resolve, 20));
    }
  }

  // ---- Sidebar: history ----

  async function refreshHistorySidebar(filter = "") {
    const threads = await window.electronAPI.getThreads();
    chatHistoryList.innerHTML = "";

    if (!threads || threads.length === 0) {
      chatHistoryList.innerHTML = `<li>${filter ? "No matches" : "No history"}</li>`;
      return;
    }

    const filtered = threads.filter((t) =>
      t.title.toLowerCase().includes(filter.toLowerCase())
    );

    if (filtered.length === 0) {
      chatHistoryList.innerHTML = "<li>No matches</li>";
      return;
    }

    filtered.forEach((thread) => {
      const li = document.createElement("li");
      li.dataset.id = thread.id;
      if (currentThread && currentThread.id === thread.id) {
        li.classList.add("active");
      }

      const titleSpan = document.createElement("span");
      titleSpan.className = "session-title";
      titleSpan.textContent = thread.title;
      titleSpan.addEventListener("click", () => loadThread(thread.id));

      const actionsDiv = document.createElement("div");
      actionsDiv.className = "session-actions";

      // Rename button
      const renameBtn = document.createElement("button");
      renameBtn.className = "rename-session-btn";
      renameBtn.innerHTML = "&#9998;"; // pencil
      renameBtn.title = "Rename Chat";
      renameBtn.addEventListener("click", (e) => {
        e.stopPropagation();
        startRename(li, thread);
      });

      // Delete button
      const delBtn = document.createElement("button");
      delBtn.className = "delete-session-btn";
      delBtn.innerHTML = "&#10005;"; // x
      delBtn.title = "Delete Chat";
      delBtn.addEventListener("click", async (e) => {
        e.stopPropagation();
        if (confirm("Are you sure you want to delete this chat?")) {
          await window.electronAPI.deleteThread(thread.id);
          if (currentThread && currentThread.id === thread.id) {
            startNewChat();
          } else {
            await refreshHistorySidebar(chatSearch ? chatSearch.value : "");
          }
        }
      });

      actionsDiv.appendChild(renameBtn);
      actionsDiv.appendChild(delBtn);
      li.appendChild(titleSpan);
      li.appendChild(actionsDiv);
      chatHistoryList.appendChild(li);
    });
  }

  function startRename(li, thread) {
    const titleSpan = li.querySelector(".session-title");
    const actionsDiv = li.querySelector(".session-actions");
    actionsDiv.style.display = "none";

    const input = document.createElement("input");
    input.type = "text";
    input.className = "rename-input";
    input.value = thread.title;

    titleSpan.replaceWith(input);
    input.focus();
    input.select();

    async function finishRename() {
      const newTitle = input.value.trim();
      if (newTitle && newTitle !== thread.title) {
        await window.electronAPI.renameThread(thread.id, newTitle);
        if (currentThread && currentThread.id === thread.id) {
          currentThread.title = newTitle;
        }
      }
      await refreshHistorySidebar(chatSearch ? chatSearch.value : "");
    }

    input.addEventListener("keydown", (e) => {
      if (e.key === "Enter") {
        e.preventDefault();
        finishRename();
      }
      if (e.key === "Escape") {
        refreshHistorySidebar(chatSearch ? chatSearch.value : "");
      }
    });

    input.addEventListener("blur", finishRename);
  }

  // ---- Thread management ----

  async function loadThread(threadId) {
    const thread = await window.electronAPI.getThread(threadId);
    if (!thread) return;

    currentThread = {
      id: thread.id,
      title: thread.title,
      messages: [],
    };

    chatContainer.innerHTML = "";
    mainContent.classList.remove("new-chat-mode");

    thread.messages.forEach((msg) => {
      const isUser = msg.sender === "user";
      const files = isUser && msg.attachments && msg.attachments.length > 0
        ? msg.attachments : null;
      const messageDiv = appendMessage(isUser, msg.content, true, files);
      if (!isUser) {
        appendRAGAttribution(messageDiv, msg.sources, msg.retrieved_chunks);
        appendTokenInfo(msg.tokens);
      }
    });

    messageInput.disabled = false;
    messageInput.value = "";

    requestAnimationFrame(() => {
      setTimeout(() => {
        messageInput.focus();
      }, 100);
    });

    await refreshHistorySidebar(chatSearch ? chatSearch.value : "");
  }

  async function startNewChat() {
    currentThread = null;
    chatContainer.innerHTML = "";
    messageInput.disabled = false;
    messageInput.value = "";
    messageInput.style.height = "auto";

    if (chatSearch) chatSearch.value = "";
    mainContent.classList.add("new-chat-mode");

    setTimeout(() => {
      messageInput.focus();
    }, 350);

    await refreshHistorySidebar();
  }

  // ---- Send message ----

  async function handleSendMessage() {
    const message = messageInput.value.trim();
    if (!message && stagedFiles.length === 0) return;

    if (mainContent.classList.contains("new-chat-mode")) {
      mainContent.classList.remove("new-chat-mode");
    }

    // If no thread yet, create one on the backend
    if (!currentThread) {
      const newThread = await window.electronAPI.createThread();
      if (!newThread) {
        appendMessage(false, "Error: Could not create a new chat thread.", false);
        return;
      }
      currentThread = {
        id: newThread.id,
        title: newThread.title,
        messages: [],
      };
    }

    // Capture and clear staged files
    const attachedFiles = [...stagedFiles];
    stagedFiles = [];
    renderStagedFiles();

    // Show user message with attachments
    appendMessage(true, message, true, attachedFiles);
    messageInput.value = "";
    messageInput.style.height = "auto";

    // Disable input while waiting
    messageInput.disabled = true;
    sendButton.disabled = true;

    showThinking();

    try {
      const filesForBackend = attachedFiles.map((f) => ({
        name: f.name,
        type: f.type,
        dataUrl: f.dataUrl || null,
        textContent: f.textContent || null,
      }));

      const response = await window.electronAPI.sendMessage(
        currentThread.id,
        message,
        filesForBackend,
        selectedMode
      );

      removeThinking();

      // Create bot message with streaming effect
      const messageDiv = document.createElement("div");
      messageDiv.className = "message bot-message";
      const contentDiv = document.createElement("div");
      contentDiv.className = "message-content";
      messageDiv.appendChild(contentDiv);
      chatContainer.appendChild(messageDiv);

      await simulateStreaming(contentDiv, response.message);

      // Show retrieved chunks and source attribution if RAG mode
      appendRAGAttribution(messageDiv, response.sources, response.retrieved_chunks);

      currentThread.messages.push({ isUser: false, content: response.message });

      // Update title if backend auto-titled
      if (response.thread_title) {
        currentThread.title = response.thread_title;
      }

      // Show token usage
      appendTokenInfo(response.tokens);

      chatContainer.scrollTop = chatContainer.scrollHeight;
      await refreshHistorySidebar(chatSearch ? chatSearch.value : "");
    } catch (error) {
      removeThinking();
      console.error("Error:", error);
      appendMessage(false, "Error: Failed to get a response.", false);
    } finally {
      messageInput.disabled = false;
      sendButton.disabled = false;
      messageInput.focus();
    }
  }

  // ---- Init ----

  function init() {
    chatContainer = document.getElementById("chat-container");
    mainContent = document.getElementById("main-content");
    messageInput = document.getElementById("message-input");
    sendButton = document.getElementById("send-button");
    chatHistoryList = document.getElementById("chat-history");
    chatSearch = document.getElementById("chat-search");

    marked.setOptions({ breaks: true, gfm: true });

    // Auto-resize textarea
    messageInput.addEventListener("input", function () {
      this.style.height = "auto";
      this.style.height = this.scrollHeight + "px";

      if (!currentThread || currentThread.messages.length === 0) {
        if (this.value.trim().length > 0) {
          mainContent.classList.remove("new-chat-mode");
        } else {
          mainContent.classList.add("new-chat-mode");
        }
      }
    });

    sendButton.addEventListener("click", handleSendMessage);

    messageInput.addEventListener("keydown", (e) => {
      if (e.key === "Enter" && !e.shiftKey) {
        e.preventDefault();
        handleSendMessage();
      }
    });

    document
      .getElementById("new-chat-btn")
      .addEventListener("click", startNewChat);

    chatSearch.addEventListener("input", async (e) => {
      await refreshHistorySidebar(e.target.value.toLowerCase());
    });

    const uploadBtn = document.getElementById("upload-btn");
    uploadBtn.addEventListener("click", async () => {
      const files = await window.electronAPI.pickFiles();
      if (!files || files.length === 0) return;

      if (selectedMode === "normal") {
        // Normal mode: stage files for inline injection into the message
        addStagedFiles(files);
      } else {
        // RAG mode: index PDF/TXT into knowledge base (persistent)
        const ragExts = ["pdf", "txt", "docx", "pptx", "xlsx"];
        const indexable = files.filter((f) => ragExts.includes(f.ext));
        const nonIndexable = files.filter((f) => !ragExts.includes(f.ext));

        if (nonIndexable.length > 0) {
          // Non-indexable files still get staged for inline injection
          addStagedFiles(nonIndexable);
        }

        if (indexable.length > 0) {
          await indexFilesWithProgress(indexable);
        }
      }
    });

    // RAG folder upload
    const folderBtn = document.getElementById("upload-folder-btn");
    folderBtn.addEventListener("click", async () => {
      const result = await window.electronAPI.pickFolder();
      if (!result || !result.files || result.files.length === 0) return;

      // Show folder name as a header chip, then index all files
      const staging = document.getElementById("file-staging");
      staging.style.display = "flex";
      const headerChip = document.createElement("div");
      headerChip.className = "file-chip rag-indexing";
      const folderIcon = document.createElement("span");
      folderIcon.className = "file-chip-icon";
      folderIcon.textContent = "\u{1F4C1}";
      headerChip.appendChild(folderIcon);
      const folderName = document.createElement("span");
      folderName.className = "file-chip-name";
      folderName.textContent = `${result.folder}/ (${result.files.length} files)`;
      headerChip.appendChild(folderName);
      staging.appendChild(headerChip);

      const totalChunks = await indexFilesWithProgress(result.files);

      // Update header chip with final result
      folderName.textContent = `${result.folder}/ (${result.files.length} files, ${totalChunks} chunks)`;
      headerChip.classList.remove("rag-indexing");
      headerChip.classList.add("rag-indexed");

      setTimeout(() => {
        headerChip.remove();
        if (staging.children.length === 0) {
          staging.style.display = "none";
        }
      }, 4000);
    });

    // RAG toggle
    const ragToggle = document.getElementById("rag-toggle");
    const modeLabel = document.getElementById("mode-label");
    ragToggle.addEventListener("change", () => {
      selectedMode = ragToggle.checked ? "rag" : "normal";
      modeLabel.textContent = ragToggle.checked ? "RAG" : "Normal";
      modeLabel.classList.toggle("rag-active", ragToggle.checked);
      uploadBtn.title = ragToggle.checked
        ? "Upload documents to RAG knowledge base (PDF, DOCX, PPTX, XLSX, TXT)"
        : "Attach files to message";
      folderBtn.style.display = ragToggle.checked ? "" : "none";
    });

    document.getElementById("logout-btn").addEventListener("click", async () => {
      await window.electronAPI.logout();
    });

    // Initial load
    (async () => {
      await refreshHistorySidebar();
      mainContent.classList.add("new-chat-mode");
      chatContainer.innerHTML = "";
    })();
  }

  ns.ChatManager = { init, appendMessage };
})();
