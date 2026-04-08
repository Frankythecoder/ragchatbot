# RAG System Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add Retrieval-Augmented Generation (RAG) to the existing Cortex chatbot, with a Normal/RAG toggle, document upload/indexing, and source attribution.

**Architecture:** Documents uploaded via the existing file picker are sent to a new `/api/upload-document/` endpoint that extracts text, chunks it, embeds with `all-MiniLM-L6-v2`, and stores in a per-user FAISS index. The chat endpoint gains a `mode` parameter: when `"rag"`, it embeds the query, retrieves top-3 chunks, injects them into the system prompt, and returns source filenames alongside the AI response. The frontend adds a toggle switch and renders sources below RAG responses.

**Tech Stack:** Django REST Framework, FAISS (faiss-cpu), Sentence Transformers (all-MiniLM-L6-v2), pypdf, Electron/JS frontend

---

## File Structure

| Action | Path | Responsibility |
|--------|------|----------------|
| Modify | `backend/requirements.txt` | Add faiss-cpu, sentence-transformers, pypdf |
| Modify | `backend/chatapp/settings.py` | Add RAG config constants |
| Create | `backend/core/rag.py` | RAG engine: text extraction, chunking, embedding, FAISS index management, retrieval |
| Modify | `backend/core/views.py` | Add `upload_document` endpoint; modify `send_message` to accept `mode` and use RAG |
| Modify | `backend/core/urls.py` | Add route for `/upload-document/` |
| Modify | `frontend/src/services/apiService.js` | Add `uploadDocument()` method; add `mode` param to `sendMessage()` |
| Modify | `frontend/src/preload.js` | Add `uploadDocument` and pass `mode` through `sendMessage` |
| Modify | `frontend/src/index.js` | Add IPC handlers for `rag:upload` and pass `mode` through `chat:send` |
| Modify | `frontend/src/modules/chatManager.js` | Add RAG toggle, wire upload to RAG endpoint, render sources |
| Modify | `frontend/src/index.html` | Add toggle switch markup in input area |
| Modify | `frontend/src/index.css` | Add styles for toggle switch and sources section |

---

### Task 1: Backend Dependencies and Configuration

**Files:**
- Modify: `backend/requirements.txt`
- Modify: `backend/chatapp/settings.py:100-103`

- [ ] **Step 1: Add RAG dependencies to requirements.txt**

Append to `backend/requirements.txt` after the last line:

```
faiss-cpu>=1.7
sentence-transformers>=2.2
pypdf>=3.0
```

Full file should be:

```
django>=4.2,<5.0
djangorestframework>=3.14
djangorestframework-simplejwt>=5.3
openai>=1.0
django-cors-headers>=4.3
python-dotenv>=1.0
faiss-cpu>=1.7
sentence-transformers>=2.2
pypdf>=3.0
```

- [ ] **Step 2: Add RAG configuration to settings.py**

Add after line 103 (`MAX_HISTORY_MESSAGES = ...`):

```python
# --- RAG ---
RAG_CHUNK_SIZE = int(os.environ.get("RAG_CHUNK_SIZE", "500"))
RAG_CHUNK_OVERLAP = int(os.environ.get("RAG_CHUNK_OVERLAP", "100"))
RAG_TOP_K = int(os.environ.get("RAG_TOP_K", "3"))
RAG_EMBEDDING_MODEL = os.environ.get("RAG_EMBEDDING_MODEL", "all-MiniLM-L6-v2")
RAG_INDEX_DIR = os.path.join(BASE_DIR, "rag_indices")
```

- [ ] **Step 3: Install the new dependencies**

Run:
```bash
cd backend && pip install -r requirements.txt
```

Expected: all packages install successfully, including `faiss-cpu`, `sentence-transformers`, and `pypdf`.

- [ ] **Step 4: Commit**

```bash
git add backend/requirements.txt backend/chatapp/settings.py
git commit -m "feat: add RAG dependencies and configuration"
```

---

### Task 2: RAG Engine Module

**Files:**
- Create: `backend/core/rag.py`

This module encapsulates all RAG logic: text extraction, chunking, embedding, FAISS index CRUD, and retrieval.

- [ ] **Step 1: Create the RAG engine**

Create `backend/core/rag.py` with the following content:

```python
import os
import json
import numpy as np
import faiss
from pypdf import PdfReader
from sentence_transformers import SentenceTransformer
from django.conf import settings

_model = None


def get_embedding_model():
    global _model
    if _model is None:
        _model = SentenceTransformer(settings.RAG_EMBEDDING_MODEL)
    return _model


def extract_text(file_path):
    """Extract text from a PDF or TXT file."""
    if file_path.lower().endswith(".pdf"):
        reader = PdfReader(file_path)
        return "\n".join(page.extract_text() or "" for page in reader.pages)
    else:
        with open(file_path, "r", encoding="utf-8", errors="ignore") as f:
            return f.read()


def chunk_text(text, chunk_size=None, overlap=None):
    """Split text into overlapping chunks."""
    chunk_size = chunk_size or settings.RAG_CHUNK_SIZE
    overlap = overlap or settings.RAG_CHUNK_OVERLAP
    chunks = []
    start = 0
    while start < len(text):
        end = start + chunk_size
        chunks.append(text[start:end])
        start += chunk_size - overlap
    return chunks


def _user_index_dir(user_id):
    """Return the directory for a user's FAISS index."""
    path = os.path.join(settings.RAG_INDEX_DIR, str(user_id))
    os.makedirs(path, exist_ok=True)
    return path


def _load_index(user_id):
    """Load a user's FAISS index and metadata. Creates new if not found."""
    index_dir = _user_index_dir(user_id)
    index_path = os.path.join(index_dir, "index.faiss")
    meta_path = os.path.join(index_dir, "metadata.json")

    if os.path.exists(index_path) and os.path.exists(meta_path):
        index = faiss.read_index(index_path)
        with open(meta_path, "r") as f:
            metadata = json.load(f)
    else:
        dim = get_embedding_model().get_sentence_embedding_dimension()
        index = faiss.IndexFlatL2(dim)
        metadata = []

    return index, metadata


def _save_index(user_id, index, metadata):
    """Persist a user's FAISS index and metadata to disk."""
    index_dir = _user_index_dir(user_id)
    faiss.write_index(index, os.path.join(index_dir, "index.faiss"))
    with open(os.path.join(index_dir, "metadata.json"), "w") as f:
        json.dump(metadata, f)


def index_document(user_id, filename, text):
    """Chunk, embed, and add a document to the user's FAISS index."""
    chunks = chunk_text(text)
    if not chunks:
        return 0

    model = get_embedding_model()
    embeddings = model.encode(chunks, normalize_embeddings=True)
    embeddings = np.array(embeddings, dtype="float32")

    index, metadata = _load_index(user_id)
    index.add(embeddings)

    for chunk in chunks:
        metadata.append({"filename": filename, "text": chunk})

    _save_index(user_id, index, metadata)
    return len(chunks)


def retrieve(user_id, query, top_k=None):
    """Embed the query and retrieve the top-k most relevant chunks."""
    top_k = top_k or settings.RAG_TOP_K
    index, metadata = _load_index(user_id)

    if index.ntotal == 0:
        return []

    model = get_embedding_model()
    query_vec = model.encode([query], normalize_embeddings=True)
    query_vec = np.array(query_vec, dtype="float32")

    distances, indices = index.search(query_vec, min(top_k, index.ntotal))

    results = []
    for i in indices[0]:
        if 0 <= i < len(metadata):
            results.append(metadata[i])
    return results
```

- [ ] **Step 2: Verify the module imports**

Run:
```bash
cd backend && python -c "from core.rag import extract_text, chunk_text, index_document, retrieve; print('OK')"
```

Expected: `OK` printed with no import errors.

- [ ] **Step 3: Commit**

```bash
git add backend/core/rag.py
git commit -m "feat: add RAG engine with FAISS indexing and retrieval"
```

---

### Task 3: Upload Document Endpoint

**Files:**
- Modify: `backend/core/views.py:1-16` (imports), append new view after line 285
- Modify: `backend/core/urls.py:1-10`

- [ ] **Step 1: Add the upload_document view to views.py**

Add this import at the top of `backend/core/views.py`, after the existing imports (after line 15):

```python
from .rag import extract_text, index_document, retrieve
```

Then append this view after the `send_message` function (after line 285):

```python
# ---------------------------------------------------------------------------
# Document Upload (RAG)
# ---------------------------------------------------------------------------


@api_view(["POST"])
@permission_classes([IsAuthenticated])
def upload_document(request):
    file = request.FILES.get("file")
    if not file:
        return Response(
            {"detail": "No file provided."},
            status=status.HTTP_400_BAD_REQUEST,
        )

    filename = file.name.lower()
    if not (filename.endswith(".pdf") or filename.endswith(".txt")):
        return Response(
            {"detail": "Only PDF and TXT files are supported."},
            status=status.HTTP_400_BAD_REQUEST,
        )

    # Write to a temp file for processing
    import tempfile, os

    suffix = ".pdf" if filename.endswith(".pdf") else ".txt"
    with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
        for chunk in file.chunks():
            tmp.write(chunk)
        tmp_path = tmp.name

    try:
        text = extract_text(tmp_path)
        if not text.strip():
            return Response(
                {"detail": "Could not extract text from file."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        chunks_added = index_document(request.user.id, file.name, text)
    finally:
        os.unlink(tmp_path)

    return Response({
        "success": True,
        "filename": file.name,
        "chunks_indexed": chunks_added,
    })
```

- [ ] **Step 2: Add the URL route**

In `backend/core/urls.py`, add the new route. The full file becomes:

```python
from django.urls import path
from . import views

urlpatterns = [
    path("threads/", views.thread_list, name="thread-list"),
    path("threads/<int:thread_id>/", views.thread_detail, name="thread-detail"),
    path(
        "threads/<int:thread_id>/chat/", views.send_message, name="send-message"
    ),
    path("upload-document/", views.upload_document, name="upload-document"),
]
```

- [ ] **Step 3: Test the endpoint manually**

Start the server:
```bash
cd backend && python manage.py runserver
```

In another terminal, test with a text file:
```bash
echo "This is a test document about machine learning." > /tmp/test.txt
curl -X POST http://localhost:8000/api/upload-document/ \
  -H "Authorization: Bearer <your-access-token>" \
  -F "file=@/tmp/test.txt"
```

Expected response:
```json
{"success": true, "filename": "test.txt", "chunks_indexed": 1}
```

- [ ] **Step 4: Commit**

```bash
git add backend/core/views.py backend/core/urls.py
git commit -m "feat: add /api/upload-document/ endpoint for RAG indexing"
```

---

### Task 4: RAG Mode in Chat Endpoint

**Files:**
- Modify: `backend/core/views.py:178-285` (the `send_message` function)

- [ ] **Step 1: Modify send_message to accept mode and use RAG**

Replace the `send_message` function (lines 178-285) with this version. Changes are:
1. Read `mode` from request data (line 3 of the function)
2. When `mode == "rag"`, retrieve chunks and build a RAG system prompt (after building conversation history)
3. Include `sources` in the response

Replace the entire `send_message` function:

```python
@api_view(["POST"])
@permission_classes([IsAuthenticated])
def send_message(request, thread_id):
    try:
        thread = ChatThread.objects.get(id=thread_id, user=request.user)
    except ChatThread.DoesNotExist:
        return Response(
            {"detail": "Thread not found."}, status=status.HTTP_404_NOT_FOUND
        )

    content = request.data.get("message", "").strip()
    files = request.data.get("files", []) or []
    mode = request.data.get("mode", "normal")

    if not content and not files:
        return Response(
            {"detail": "Message cannot be empty."},
            status=status.HTTP_400_BAD_REQUEST,
        )

    # Save user message (text only for DB)
    Message.objects.create(
        thread=thread, sender="user", content=content or "[Files attached]"
    )

    # Auto-title on first user message
    user_msg_count = thread.messages.filter(sender="user").count()
    if user_msg_count == 1:
        title_src = content if content else (
            files[0].get("name", "New Chat") if files else "New Chat"
        )
        thread.title = title_src[:50] + ("..." if len(title_src) > 50 else "")
        thread.save()

    # Build conversation history for LLM (token optimization)
    all_messages = list(thread.messages.order_by("timestamp"))
    max_msgs = settings.MAX_HISTORY_MESSAGES
    if len(all_messages) > max_msgs:
        all_messages = all_messages[-max_msgs:]

    # Build system prompt — RAG or normal
    sources = []
    if mode == "rag" and content:
        results = retrieve(request.user.id, content)
        if results:
            context_text = "\n\n---\n\n".join(r["text"] for r in results)
            sources = list(dict.fromkeys(r["filename"] for r in results))
            system_content = (
                "Answer ONLY using the context below. "
                "If the answer is not found in the context, say 'I don't know.'\n\n"
                f"Context:\n{context_text}"
            )
        else:
            system_content = (
                "No documents have been indexed yet. "
                "Tell the user to upload documents first for RAG mode."
            )
    else:
        system_content = "You are a helpful AI assistant."

    conversation = [{"role": "system", "content": system_content}]

    # Previous messages as plain text
    for msg in all_messages[:-1]:
        role = "user" if msg.sender == "user" else "assistant"
        conversation.append({"role": role, "content": msg.content})

    # Current user message — may include file content for the LLM
    if files:
        user_parts = []
        if content:
            user_parts.append({"type": "text", "text": content})
        for f in files:
            if f.get("type") == "image" and f.get("dataUrl"):
                user_parts.append(
                    {"type": "image_url", "image_url": {"url": f["dataUrl"]}}
                )
            elif f.get("textContent"):
                user_parts.append(
                    {
                        "type": "text",
                        "text": (
                            f"--- File: {f['name']} ---\n"
                            f"{f['textContent']}\n"
                            f"--- End of {f['name']} ---"
                        ),
                    }
                )
            else:
                user_parts.append(
                    {
                        "type": "text",
                        "text": f"[Attached file: {f['name']} ({f.get('type', 'unknown')} file)]",
                    }
                )
        conversation.append({"role": "user", "content": user_parts})
    else:
        conversation.append({"role": "user", "content": content})

    # Call OpenAI
    tokens_used = None
    try:
        ai_client = get_openai_client()
        response = ai_client.chat.completions.create(
            model=settings.OPENAI_MODEL,
            messages=conversation,
        )
        ai_content = response.choices[0].message.content
        tokens_used = {
            "prompt_tokens": response.usage.prompt_tokens,
            "completion_tokens": response.usage.completion_tokens,
            "total_tokens": response.usage.total_tokens,
        }
    except Exception as e:
        ai_content = f"I'm sorry, I encountered an error: {str(e)}"

    # Save AI response
    Message.objects.create(thread=thread, sender="ai", content=ai_content)
    thread.save()  # bumps updated_at

    return Response(
        {
            "message": ai_content,
            "tokens": tokens_used,
            "thread_title": thread.title,
            "sources": sources,
        }
    )
```

- [ ] **Step 2: Verify the server starts**

Run:
```bash
cd backend && python manage.py runserver
```

Expected: server starts without errors.

- [ ] **Step 3: Commit**

```bash
git add backend/core/views.py
git commit -m "feat: add RAG mode to chat endpoint with context injection and sources"
```

---

### Task 5: Frontend API Service and IPC Layer

**Files:**
- Modify: `frontend/src/services/apiService.js:162-182` (sendMessage) and append uploadDocument
- Modify: `frontend/src/preload.js:23-25`
- Modify: `frontend/src/index.js:142-157` (chat handler) and add rag:upload handler

- [ ] **Step 1: Add uploadDocument and update sendMessage in apiService.js**

In `frontend/src/services/apiService.js`, replace the `sendMessage` method (lines 162-182) with:

```javascript
  async sendMessage(threadId, message, accessToken, files = [], mode = "normal") {
    try {
      const res = await fetch(`${BACKEND_URL}/api/threads/${threadId}/chat/`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          Authorization: `Bearer ${accessToken}`,
        },
        body: JSON.stringify({ message, files: files || [], mode }),
      });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      return await res.json();
    } catch (error) {
      console.error("ApiService.sendMessage error:", error);
      return {
        message: `Could not reach the backend. Make sure the Django server is running.\n\nError: ${error.message}`,
        tokens: null,
        thread_title: null,
        sources: [],
      };
    }
  }
```

Then add the `uploadDocument` method right before the closing `}` of the class (before line 183 which is `}`):

```javascript
  async uploadDocument(filePath, accessToken) {
    const fs = require("node:fs");
    const path = require("node:path");
    const filename = path.basename(filePath);

    const fileBuffer = fs.readFileSync(filePath);
    const formData = new FormData();
    formData.append("file", new Blob([fileBuffer]), filename);

    try {
      const res = await fetch(`${BACKEND_URL}/api/upload-document/`, {
        method: "POST",
        headers: {
          Authorization: `Bearer ${accessToken}`,
        },
        body: formData,
      });
      if (!res.ok) {
        const data = await res.json();
        throw new Error(data.detail || `HTTP ${res.status}`);
      }
      return await res.json();
    } catch (error) {
      console.error("ApiService.uploadDocument error:", error);
      return { success: false, message: error.message };
    }
  }
```

- [ ] **Step 2: Update preload.js to expose new APIs**

Replace the Chat section (lines 23-25) and add the new methods. The full file becomes:

```javascript
const { contextBridge, ipcRenderer } = require("electron");

contextBridge.exposeInMainWorld("electronAPI", {
  // Auth
  login: (email, password) => ipcRenderer.invoke("auth:login", email, password),
  register: (username, email, password) =>
    ipcRenderer.invoke("auth:register", username, email, password),
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
});
```

- [ ] **Step 3: Update index.js IPC handlers**

In `frontend/src/index.js`, replace the chat handler (lines 142-157) with:

```javascript
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
```

- [ ] **Step 4: Commit**

```bash
git add frontend/src/services/apiService.js frontend/src/preload.js frontend/src/index.js
git commit -m "feat: add RAG upload IPC and mode parameter to chat pipeline"
```

---

### Task 6: Frontend Toggle Switch and HTML

**Files:**
- Modify: `frontend/src/index.html:98-111` (input-row area)
- Modify: `frontend/src/index.css` (append new styles)

- [ ] **Step 1: Add the toggle switch HTML**

In `frontend/src/index.html`, replace the `<div class="input-row">` block (lines 98-111) with:

```html
          <div class="mode-toggle-row">
            <label class="mode-toggle" title="Switch between Normal and RAG mode">
              <input type="checkbox" id="rag-toggle" />
              <span class="mode-slider"></span>
            </label>
            <span id="mode-label" class="mode-label">Normal</span>
          </div>
          <div class="input-row">
            <button id="upload-btn" title="Attach files">
              <svg viewBox="0 0 24 24" width="22" height="22">
                <path fill="currentColor"
                  d="M16.5,6V17.5A4,4 0 0,1 12.5,21.5A4,4 0 0,1 8.5,17.5V5A2.5,2.5 0 0,1 11,2.5A2.5,2.5 0 0,1 13.5,5V15.5A1,1 0 0,1 12.5,16.5A1,1 0 0,1 11.5,15.5V6H10V15.5A2.5,2.5 0 0,1 12.5,18A2.5,2.5 0 0,1 15,15.5V5A4,4 0 0,1 11,1A4,4 0 0,1 7,5V17.5A5.5,5.5 0 0,0 12.5,23A5.5,5.5 0 0,0 18,17.5V6H16.5Z" />
              </svg>
            </button>
            <textarea id="message-input" placeholder="Type your message..." rows="1"></textarea>
            <button id="send-button">
              <svg viewBox="0 0 24 24" width="24" height="24">
                <path fill="currentColor" d="M2,21L23,12L2,3V10L17,12L2,14V21Z" />
              </svg>
            </button>
          </div>
```

- [ ] **Step 2: Add toggle and source styles to index.css**

Append the following to the end of `frontend/src/index.css`:

```css
/* ========== RAG Mode Toggle ========== */
.mode-toggle-row {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 4px 8px 6px 8px;
}

.mode-toggle {
  position: relative;
  display: inline-block;
  width: 40px;
  height: 22px;
  flex-shrink: 0;
}

.mode-toggle input {
  opacity: 0;
  width: 0;
  height: 0;
}

.mode-slider {
  position: absolute;
  cursor: pointer;
  top: 0;
  left: 0;
  right: 0;
  bottom: 0;
  background-color: var(--pill-bg);
  border: 1px solid var(--border-color);
  border-radius: 22px;
  transition: background-color 0.3s;
}

.mode-slider::before {
  content: "";
  position: absolute;
  height: 16px;
  width: 16px;
  left: 2px;
  bottom: 2px;
  background-color: #8e8ea0;
  border-radius: 50%;
  transition: transform 0.3s, background-color 0.3s;
}

.mode-toggle input:checked + .mode-slider {
  background-color: rgba(16, 163, 127, 0.2);
  border-color: var(--accent-color);
}

.mode-toggle input:checked + .mode-slider::before {
  transform: translateX(18px);
  background-color: var(--accent-color);
}

.mode-label {
  font-size: 0.75rem;
  color: #8e8ea0;
  user-select: none;
}

.mode-label.rag-active {
  color: var(--accent-color);
  font-weight: 600;
}

/* ========== Source Attribution ========== */
.source-attribution {
  margin-top: 8px;
  padding-top: 8px;
  border-top: 1px solid var(--border-color);
  font-size: 0.8rem;
  color: #8e8ea0;
}

.source-attribution strong {
  color: var(--accent-color);
}

.source-tag {
  display: inline-block;
  background: var(--pill-bg);
  border-radius: 4px;
  padding: 2px 6px;
  margin: 2px 3px;
  font-size: 0.75rem;
  color: var(--text-main);
}
```

- [ ] **Step 3: Commit**

```bash
git add frontend/src/index.html frontend/src/index.css
git commit -m "feat: add RAG toggle switch and source attribution styles"
```

---

### Task 7: Chat Manager — Toggle, Upload Wiring, and Source Rendering

**Files:**
- Modify: `frontend/src/modules/chatManager.js`

This is the largest change. Three additions:
1. Toggle state management and label update
2. Upload button wires PDF/TXT files to the RAG upload endpoint
3. Source attribution rendering after bot messages

- [ ] **Step 1: Add selectedMode state and toggle wiring**

In `frontend/src/modules/chatManager.js`, after the `let stagedFiles = [];` line (line 13), add:

```javascript
  let selectedMode = "normal";
```

- [ ] **Step 2: Update the init function to wire the toggle**

In the `init()` function, after the upload-btn event listener (after line 473), add:

```javascript
    // RAG toggle
    const ragToggle = document.getElementById("rag-toggle");
    const modeLabel = document.getElementById("mode-label");
    ragToggle.addEventListener("change", () => {
      selectedMode = ragToggle.checked ? "rag" : "normal";
      modeLabel.textContent = ragToggle.checked ? "RAG" : "Normal";
      modeLabel.classList.toggle("rag-active", ragToggle.checked);
    });
```

- [ ] **Step 3: Update the upload button handler to also index for RAG**

Replace the upload-btn event listener (lines 468-473) with:

```javascript
    document.getElementById("upload-btn").addEventListener("click", async () => {
      const files = await window.electronAPI.pickFiles();
      if (files && files.length > 0) {
        addStagedFiles(files);

        // If in RAG mode, also index PDF/TXT files
        if (selectedMode === "rag") {
          for (const file of files) {
            if (file.ext === "pdf" || file.ext === "txt") {
              const result = await window.electronAPI.uploadDocument(file.path);
              if (result && result.success) {
                console.log(`Indexed ${file.name}: ${result.chunks_indexed} chunks`);
              }
            }
          }
        }
      }
    });
```

- [ ] **Step 4: Pass mode through sendMessage call**

In the `handleSendMessage()` function, replace the `sendMessage` call (lines 384-388):

```javascript
      const response = await window.electronAPI.sendMessage(
        currentThread.id,
        message,
        filesForBackend
      );
```

with:

```javascript
      const response = await window.electronAPI.sendMessage(
        currentThread.id,
        message,
        filesForBackend,
        selectedMode
      );
```

- [ ] **Step 5: Add source attribution rendering after the streaming response**

In `handleSendMessage()`, after the `simulateStreaming` call and `currentThread.messages.push(...)` line (after line 402), add source rendering. Find this block:

```javascript
      await simulateStreaming(contentDiv, response.message);

      currentThread.messages.push({ isUser: false, content: response.message });
```

And replace it with:

```javascript
      await simulateStreaming(contentDiv, response.message);

      // Show source attribution if RAG mode returned sources
      if (response.sources && response.sources.length > 0) {
        const sourceDiv = document.createElement("div");
        sourceDiv.className = "source-attribution";
        sourceDiv.innerHTML =
          "<strong>Sources:</strong> " +
          response.sources
            .map((s) => `<span class="source-tag">${s}</span>`)
            .join("");
        messageDiv.appendChild(sourceDiv);
      }

      currentThread.messages.push({ isUser: false, content: response.message });
```

- [ ] **Step 6: Commit**

```bash
git add frontend/src/modules/chatManager.js
git commit -m "feat: wire RAG toggle, document upload indexing, and source attribution"
```

---

### Task 8: End-to-End Verification

- [ ] **Step 1: Start the backend**

```bash
cd backend && python manage.py runserver
```

- [ ] **Step 2: Start the frontend**

```bash
cd frontend && npm start
```

- [ ] **Step 3: Test Normal mode**

1. Log in
2. Ensure toggle says "Normal"
3. Send a message
4. Verify: AI responds normally, no sources shown

- [ ] **Step 4: Test RAG mode — upload and query**

1. Click the toggle to "RAG"
2. Click the attach button, select a PDF or TXT file
3. Verify in the console: `Indexed <filename>: N chunks`
4. Type a question related to the uploaded document content
5. Verify: AI response uses document context, Sources section shows the filename

- [ ] **Step 5: Test RAG mode — no documents**

1. Create a new thread in RAG mode
2. Send a message without uploading any documents
3. Verify: AI tells the user to upload documents first

- [ ] **Step 6: Commit final state**

```bash
git add -A
git commit -m "feat: complete RAG system with toggle, upload, and source attribution"
```
