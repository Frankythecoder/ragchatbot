# Cortex — AI Chat & RAG Assistant

Cortex is a cross-platform desktop AI assistant that pairs an Electron frontend
with a Django REST backend. It supports two complementary modes: a **Normal
chat** mode powered by OpenAI's Chat Completions API with multi-file
attachments (text, code, and image inputs), and a **Retrieval-Augmented
Generation (RAG)** mode that answers questions grounded in your own documents
using a per-user FAISS vector index.

---

## Table of Contents

- [Features](#features)
- [Architecture](#architecture)
- [Tech Stack](#tech-stack)
- [Project Structure](#project-structure)
- [Prerequisites](#prerequisites)
- [Installation](#installation)
- [Configuration](#configuration)
- [Running the Application](#running-the-application)
- [Packaging for Distribution](#packaging-for-distribution)
- [Authentication Flow](#authentication-flow)
- [How RAG Works](#how-rag-works)
- [Supported File Formats](#supported-file-formats)
- [API Reference](#api-reference)
- [Data Model](#data-model)
- [Environment Variables](#environment-variables)
- [Troubleshooting](#troubleshooting)
- [License](#license)

---

## Features

**Chat experience**
- Two chat modes: **Normal** (general assistant with history and attachments)
  and **RAG** (answers grounded in your uploaded documents).
- Streaming-style response rendering with Markdown support.
- Automatic, LLM-generated chat titles after the first exchange
  (ChatGPT-style).
- Persistent chat history with per-thread rename, delete, and search.
- Per-message token usage breakdown (prompt / completion / total).

**Attachments**
- Inline attachments for Normal mode: images (sent to the vision-capable
  model as data URLs), plain text, and source code files are embedded into
  the prompt; other file types are referenced by name.
- RAG indexing for PDFs, DOCX, PPTX, XLSX, and TXT files — either file by
  file or by recursively scanning an entire folder.

**RAG pipeline**
- Per-user FAISS index, isolated on disk.
- Sentence-boundary-aware chunking with configurable size and overlap.
- Hybrid retrieval: semantic similarity (L2 on normalized embeddings) blended
  with keyword hit re-ranking.
- Per-document diversity pass so answers cite multiple sources when relevant.
- Source attribution and retrieved-chunk previews rendered in the UI.

**Authentication**
- Sign-in, sign-up, and sign-out handled by Django's built-in auth views
  (`LoginView`, `LogoutView`, and a `UserCreationForm`-based signup view).
- Password visibility toggle on every password field.
- JWT access / refresh tokens (with rotation and blacklist) for all API
  calls made from the desktop shell.
- Sessions persist across app restarts via encrypted token storage in the
  Electron user-data directory.

**UX**
- Light and dark themes with persisted preference.
- Collapsible sidebar, chat search, file staging chips, and a welcome
  screen for new chats.
- CSP-safe preload script with `contextBridge` for secure IPC.

---

## Architecture

```
┌────────────────────────────────────────────────────────────────────┐
│                        Electron Desktop App                         │
│                                                                     │
│   ┌──────────────┐    IPC    ┌────────────────────────────────┐    │
│   │  Renderer    │ ────────► │  Main process (Node / Electron)│    │
│   │  (chat UI)   │ ◄──────── │  - token store (encrypted disk)│    │
│   └──────────────┘           │  - BrowserWindow navigation    │    │
│                              │  - file/folder pickers         │    │
│                              │  - apiService (fetch)          │    │
│                              └────────────────┬───────────────┘    │
└──────────────────────────────────────────────────┼─────────────────┘
                                                   │ HTTPS/HTTP + JWT
                                                   ▼
┌────────────────────────────────────────────────────────────────────┐
│                        Django Backend (REST)                        │
│                                                                     │
│  /accounts/*   ─ Django auth: LoginView / LogoutView / SignUpView   │
│  /auth-complete/ ─ Session → JWT bridge (issues access & refresh)   │
│  /api/threads/   ─ CRUD for chat threads                            │
│  /api/threads/<id>/chat/ ─ Send message, run LLM, persist turn      │
│  /api/upload-document/   ─ Extract → chunk → embed → FAISS index    │
│  /api/jwt-logout/        ─ Blacklist refresh token                  │
│                                                                     │
│  ┌────────────┐   ┌──────────────┐   ┌────────────────────────┐    │
│  │   SQLite   │   │  OpenAI API  │   │  FAISS (per-user dir)  │    │
│  │ users /    │   │  chat.compl. │   │  + sentence-transformers│   │
│  │ threads /  │   │              │   │  embeddings            │    │
│  │ messages   │   │              │   │                        │    │
│  └────────────┘   └──────────────┘   └────────────────────────┘    │
└────────────────────────────────────────────────────────────────────┘
```

The Electron shell loads Django's own login page at startup (when no JWT is
stored). After a successful Django login, the backend renders an
`auth_complete` page that issues JWT tokens and hands them to the Electron
main process through the preload `electronAPI` bridge. From that point on,
the desktop app navigates to the chat UI (`index.html`) and authenticates
every API call with its JWT access token.

---

## Tech Stack

**Frontend (Electron / Renderer)**
- Electron 40
- Electron Forge (packaging & distribution)
- Vanilla JavaScript (no framework) with a small module system
- `marked` for Markdown rendering

**Backend (Django)**
- Django 4.2 with the built-in auth system
- Django REST Framework
- `djangorestframework-simplejwt` (+ token blacklist app)
- `django-cors-headers`

**AI & RAG**
- OpenAI Python SDK (Chat Completions, default model `gpt-4o-mini`)
- FAISS (CPU) for approximate nearest-neighbour search
- `sentence-transformers` (default model `all-MiniLM-L6-v2`) for embeddings
- `pypdf`, `python-docx`, `python-pptx`, `openpyxl` for text extraction

**Storage**
- SQLite (users, threads, messages, JWT blacklist)
- Filesystem FAISS indexes (one directory per user under `backend/rag_indices/`)

---

## Project Structure

```
ragchatbot/
├── backend/
│   ├── manage.py
│   ├── requirements.txt
│   ├── .env.example
│   ├── db.sqlite3                     # Created on first migrate
│   ├── rag_indices/                   # Per-user FAISS indexes (gitignored)
│   ├── chatapp/                       # Django project
│   │   ├── settings.py
│   │   ├── urls.py
│   │   ├── asgi.py
│   │   └── wsgi.py
│   └── core/                          # Main Django app
│       ├── models.py                  # ChatThread, Message
│       ├── serializers.py
│       ├── views.py                   # Auth, threads, chat, upload
│       ├── urls.py                    # /api/* routes
│       ├── auth_urls.py               # /accounts/* routes
│       ├── migrations/
│       ├── templates/registration/    # login, signup, logout, auth_complete
│       └── llm/
│           ├── embeddings.py          # SentenceTransformer lazy loader
│           ├── vector_store.py        # FAISS load/save per user
│           ├── rag_pipeline.py        # Extract, chunk, index, retrieve
│           ├── normal_llm.py          # Prompt builder for chat mode
│           └── title_generator.py     # Prompt builder for auto-titling
│
└── frontend/
    ├── package.json
    ├── forge.config.js
    └── src/
        ├── index.js                   # Electron main process
        ├── preload.js                 # contextBridge → window.electronAPI
        ├── index.html / index.css     # Chat UI
        ├── renderer.js                # Renderer entry
        ├── modules/
        │   ├── chatManager.js         # Chat history, send, RAG indexing UI
        │   ├── themeManager.js        # Light/dark toggle, persistence
        │   └── uiHelpers.js           # Sidebar, scroll, misc UI
        └── services/
            └── apiService.js          # fetch() wrappers for the Django API
```

---

## Prerequisites

- **Python 3.10 or newer**
- **Node.js 18 or newer** (and npm)
- **OpenAI API key** with access to a Chat Completions model
- On Windows, the first launch of `sentence-transformers` will download the
  embedding model (~90 MB). Keep an internet connection available for that
  initial run.

---

## Installation

Clone the repository:

```bash
git clone https://github.com/Frankythecoder/ragchatbot.git
cd ragchatbot
```

### 1. Backend

```bash
cd backend
python -m venv .venv

# Windows
.venv\Scripts\activate
# macOS / Linux
source .venv/bin/activate

pip install -r requirements.txt
cp .env.example .env        # then edit .env — see Configuration
python manage.py migrate
python manage.py createsuperuser   # optional, for /admin access
```

### 2. Frontend

```bash
cd ../frontend
npm install
```

---

## Configuration

Create `backend/.env` (copy from `.env.example`) and fill in:

```env
DJANGO_SECRET_KEY=replace-with-a-long-random-string
DJANGO_DEBUG=True
OPENAI_API_KEY=sk-...
OPENAI_MODEL=gpt-4o-mini
MAX_HISTORY_MESSAGES=20
```

See [Environment Variables](#environment-variables) for the full list,
including RAG-tuning knobs.

> **Security note:** never commit `.env`. The default `SECRET_KEY` in
> `settings.py` is clearly marked insecure and is for development only.
> Set `DJANGO_DEBUG=False` and provide a strong `DJANGO_SECRET_KEY` for any
> non-local deployment.

---

## Running the Application

You need **two terminals** — one for the backend, one for the Electron shell.

**Terminal 1 — Django API**

```bash
cd backend
# Activate the virtualenv (see Installation)
python manage.py runserver
# Django is now serving http://localhost:8000
```

**Terminal 2 — Electron app**

```bash
cd frontend
npm start
```

The Electron window opens at Django's login page
(`http://localhost:8000/accounts/login/`). Create an account, sign in, and
the app will hand off to the chat UI automatically.

---

## Packaging for Distribution

The frontend is wired up with Electron Forge. Platform-specific installers
can be produced with:

```bash
cd frontend
npm run make
```

Makers configured out of the box:

| Platform | Maker                           |
| -------- | ------------------------------- |
| Windows  | `@electron-forge/maker-squirrel`|
| macOS    | `@electron-forge/maker-zip`     |
| Debian   | `@electron-forge/maker-deb`     |
| RPM      | `@electron-forge/maker-rpm`     |

Packaged builds still require a reachable Django backend. For a real
deployment, host Django somewhere (e.g. behind Gunicorn + Nginx), update
`BACKEND_URL` in `frontend/src/index.js` and
`frontend/src/services/apiService.js`, and rebuild.

---

## Authentication Flow

Cortex uses Django's built-in authentication for the user-facing pages and
JWT for programmatic API access:

1. Electron starts. If no saved tokens exist, the main process loads
   `http://localhost:8000/accounts/login/` (Django's `LoginView`).
2. New users click **Create account**, which submits to
   `/accounts/signup/`. The view uses `SignUpForm` — a subclass of Django's
   `UserCreationForm` that requires a unique email alongside the standard
   username / password fields.
3. On successful login, Django redirects to `/auth-complete/`. That view
   is `@login_required`, mints a JWT pair via `RefreshToken.for_user()`,
   and renders a template whose inline script calls
   `window.electronAPI.storeTokens(...)` followed by `navigateToChat()`.
4. The Electron main process persists the tokens to the user-data directory
   and swaps the window to the chat UI (`index.html`).
5. From that point on, every API request carries
   `Authorization: Bearer <access_token>`.
6. On logout, the Electron shell POSTs to `/api/jwt-logout/` to blacklist
   the refresh token, clears local token storage, then navigates to
   `/accounts/logout/` so Django's `LogoutView` clears the session cookie
   and redirects back to the login page.

Tokens:
- Access token lifetime: **1 day**
- Refresh token lifetime: **7 days**
- Refresh rotation: **enabled**, old refresh tokens are blacklisted on use.

---

## How RAG Works

When you upload a document in RAG mode, Cortex:

1. **Extracts** raw text using the appropriate library
   (`pypdf`, `python-docx`, `python-pptx`, `openpyxl`, or plain read).
2. **Normalizes** whitespace and paragraph breaks, then splits into
   sentence-aware chunks (`RAG_CHUNK_SIZE`, overlap `RAG_CHUNK_OVERLAP`).
3. **Embeds** each chunk with `sentence-transformers`
   (default `all-MiniLM-L6-v2`, L2-normalized).
4. **Stores** embeddings in a per-user FAISS `IndexFlatL2` under
   `backend/rag_indices/<user_id>/`, alongside a `metadata.json` that maps
   each vector back to its source filename and text. Re-uploading the
   same filename replaces the old chunks for that document rather than
   duplicating them.

When you ask a question in RAG mode, Cortex:

1. Embeds the query with the same model.
2. Searches FAISS for `RAG_TOP_K * 3` candidate chunks.
3. **Re-ranks** them by blending semantic similarity with keyword hit
   score (stop-word-filtered query terms).
4. Applies a **diversity pass** so at least one chunk per document makes
   it through before filling remaining slots with the best overall hits.
5. Builds a constrained prompt that labels each chunk with
   `[Document: filename]`, instructs the model to quote and cite, and
   falls back to `"I don't know. The answer to your question was not
   found in the uploaded documents."` when the retrieved context is
   unrelated.
6. Returns the answer along with the list of cited sources and the
   retrieved chunks (shown in the UI under the assistant message).

All RAG knobs are exposed as environment variables — see below.

---

## Supported File Formats

**RAG indexing (persistent knowledge base):**

| Extension | Library used    |
| --------- | --------------- |
| `.pdf`    | `pypdf`         |
| `.docx`   | `python-docx`   |
| `.pptx`   | `python-pptx`   |
| `.xlsx`   | `openpyxl`      |
| `.txt`    | built-in        |

**Normal-mode inline attachments:**
- Images (`jpg`, `jpeg`, `png`, `gif`, `bmp`, `webp`, `svg`, `ico`) under
  10 MB — embedded as data URLs and sent to the vision-capable OpenAI
  model.
- Text-like and source files (`txt`, `md`, `csv`, `log`, `ini`, `cfg`,
  `conf`, `env`, plus a broad list of programming languages) — content
  inlined into the prompt.
- Other types (audio, video, generic documents) — referenced by name
  only; their metadata is stored with the message for display purposes.

The Django upload endpoint caps request bodies at 50 MB
(`DATA_UPLOAD_MAX_MEMORY_SIZE`).

---

## API Reference

All routes below are served by the Django backend at
`http://localhost:8000` during development.

### Auth (server-rendered)

| Method | Path                  | Description                                                   |
| ------ | --------------------- | ------------------------------------------------------------- |
| GET/POST | `/accounts/login/`  | Django `LoginView` (username + password).                     |
| GET/POST | `/accounts/logout/` | Django `LogoutView`. Redirects to `/accounts/login/`.         |
| GET/POST | `/accounts/signup/` | Custom `SignUpView` built on `UserCreationForm`.              |
| GET      | `/auth-complete/`   | `@login_required` bridge that emits JWTs to the Electron shell.|

### JSON API (JWT-authenticated)

All endpoints below require `Authorization: Bearer <access_token>` unless
noted.

| Method | Path                                   | Description                                                                    |
| ------ | -------------------------------------- | ------------------------------------------------------------------------------ |
| POST   | `/api/jwt-logout/`                     | Blacklists the supplied `refresh_token`.                                       |
| GET    | `/api/threads/`                        | List the current user's chat threads.                                          |
| POST   | `/api/threads/`                        | Create a new empty thread.                                                     |
| GET    | `/api/threads/<id>/`                   | Thread detail (includes all messages, sources, retrieved chunks, token usage). |
| PATCH  | `/api/threads/<id>/`                   | Rename a thread (`{"title": "..."}`).                                          |
| DELETE | `/api/threads/<id>/`                   | Delete a thread and its messages (cascade).                                    |
| POST   | `/api/threads/<id>/chat/`              | Send a message. Body: `{ "message", "files", "mode": "normal" \| "rag" }`.     |
| POST   | `/api/upload-document/`                | Multipart upload (`file`, optional `file_path`). Indexes into the user's FAISS store. |

**Example — send a message:**

```http
POST /api/threads/42/chat/ HTTP/1.1
Authorization: Bearer <access_token>
Content-Type: application/json

{
  "message": "Summarize the uploaded PDF",
  "mode": "rag",
  "files": []
}
```

Response:

```json
{
  "message": "...assistant reply...",
  "tokens": { "prompt_tokens": 523, "completion_tokens": 128, "total_tokens": 651 },
  "thread_title": "Uploaded PDF Summary",
  "sources": ["report-q1.pdf"],
  "retrieved_chunks": ["...excerpt one...", "...excerpt two..."]
}
```

---

## Data Model

**`User`** — Django's built-in user, unchanged. Authentication is by
username; the signup form also captures a unique email.

**`ChatThread`**

| Field        | Type                    | Notes                                    |
| ------------ | ----------------------- | ---------------------------------------- |
| `user`       | FK → `auth.User`        | Cascade delete.                          |
| `title`      | `CharField(max=255)`    | Defaults to `"New Chat"`; auto-filled by the title-generator after the first exchange. |
| `created_at` | `DateTimeField`         | Auto-set.                                |
| `updated_at` | `DateTimeField`         | Bumped on every message.                 |

**`Message`**

| Field               | Type                     | Notes                                                   |
| ------------------- | ------------------------ | ------------------------------------------------------- |
| `thread`            | FK → `ChatThread`        | Cascade delete.                                         |
| `sender`            | `"user"` \| `"ai"`       |                                                         |
| `content`           | `TextField`              |                                                         |
| `sources`           | `JSONField` (list)       | RAG only — filenames that were cited.                   |
| `retrieved_chunks`  | `JSONField` (list)       | RAG only — raw chunk text surfaced in the UI.           |
| `tokens`            | `JSONField` (nullable)   | `{prompt_tokens, completion_tokens, total_tokens}`.     |
| `attachments`       | `JSONField` (list)       | `{name, type, size}` per attached file.                 |
| `timestamp`         | `DateTimeField`          | Auto-set; default message ordering.                     |

---

## Environment Variables

All variables are read from `backend/.env` (via `python-dotenv`) or the
process environment.

| Variable                | Default              | Purpose                                                 |
| ----------------------- | -------------------- | ------------------------------------------------------- |
| `DJANGO_SECRET_KEY`     | insecure dev default | Django cryptographic secret. **Set in production.**     |
| `DJANGO_DEBUG`          | `True`               | Set to `False` in production.                           |
| `OPENAI_API_KEY`        | — (required)         | Your OpenAI API key.                                    |
| `OPENAI_MODEL`          | `gpt-4o-mini`        | Chat Completions model name.                            |
| `MAX_HISTORY_MESSAGES`  | `20`                 | Max previous turns sent with each chat request.         |
| `RAG_CHUNK_SIZE`        | `2000`               | Target characters per chunk.                            |
| `RAG_CHUNK_OVERLAP`     | `300`                | Overlap (in chars, approximated via word slicing).      |
| `RAG_TOP_K`             | `8`                  | Chunks surfaced to the LLM per RAG query.               |
| `RAG_EMBEDDING_MODEL`   | `all-MiniLM-L6-v2`   | Any `sentence-transformers` model id.                   |

---

## Troubleshooting

**The Electron window shows "Cannot GET" or a connection error.**
The Django backend isn't running or isn't reachable at
`http://localhost:8000`. Start it with `python manage.py runserver`.

**Login succeeds but the chat UI never opens.**
The `auth_complete` template relies on `window.electronAPI`, which is only
exposed by the Electron preload script. Make sure you're reaching the app
through the Electron shell (`npm start`) rather than a regular browser.

**"OPENAI_API_KEY" errors on first message.**
Set `OPENAI_API_KEY` in `backend/.env` and restart `runserver`. Environment
variables are loaded at process start.

**First RAG upload takes a while.**
The embedding model is downloaded on first use (~90 MB). Subsequent
uploads reuse the cached model and are fast.

**RAG mode answers "I don't know" for questions you expect it to answer.**
The retrieved chunks were judged unrelated to the question. Try:
- Uploading more documents or more relevant excerpts,
- Raising `RAG_TOP_K`,
- Lowering `RAG_CHUNK_SIZE` for finer-grained retrieval,
- Rephrasing the question with keywords that appear in the source text.

**Logout deprecation warning from Django.**
Django 4.2 still allows `GET /accounts/logout/` but marks it deprecated.
The app opts in explicitly via `http_method_names=["get", "post", "options"]`.
When upgrading to Django 5+, switch the Electron logout handler to POST.

**Port 8000 already in use.**
Run Django on a different port with
`python manage.py runserver 0.0.0.0:8001` and update `BACKEND_URL` in
`frontend/src/index.js` and `frontend/src/services/apiService.js`.

---

## License

MIT © Frankythecoder
