# Cortex — AI Chat & RAG Assistant

Cortex is a Django web application that delivers two complementary chat
modes: a **Normal chat** mode powered by OpenAI's Chat Completions API with
multi-file attachments (text, code, and image inputs), and a
**Retrieval-Augmented Generation (RAG)** mode that answers questions
grounded in your own documents using a per-user FAISS vector index.

The app runs as a single Django/Gunicorn web service and is ready to deploy
on [Render](https://render.com/) with the included `render.yaml` blueprint.

---

## Table of Contents

- [Features](#features)
- [Architecture](#architecture)
- [Tech Stack](#tech-stack)
- [Project Structure](#project-structure)
- [Prerequisites](#prerequisites)
- [Local Development](#local-development)
- [Deploying to Render](#deploying-to-render)
- [Configuration](#configuration)
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
  file or by recursively scanning an entire folder via the browser's
  directory picker.

**RAG pipeline**
- Per-user FAISS index, isolated on disk (or on a persistent disk in
  production).
- Sentence-boundary-aware chunking with configurable size and overlap.
- Hybrid retrieval: semantic similarity (L2 on normalized embeddings)
  blended with keyword hit re-ranking.
- Per-document diversity pass so answers cite multiple sources when relevant.
- Source attribution and retrieved-chunk previews rendered in the UI.

**Authentication**
- Sign-in, sign-up, and sign-out handled by Django's built-in auth views
  (`LoginView`, `LogoutView`, and a `UserCreationForm`-based signup view).
- Password visibility toggle on every password field.
- Session-based authentication for the API; the chat UI is served from the
  same origin so the session cookie + CSRF token are all that's needed.

**UX**
- Light and dark themes with persisted preference.
- Collapsible sidebar, chat search, file staging chips, and a welcome
  screen for new chats.

---

## Architecture

```
                        ┌────────────────────────┐
                        │   Browser (Chat SPA)   │
                        │  HTML + CSS + vanilla  │
                        │  JS, served by Django  │
                        └───────────┬────────────┘
                                    │ HTTPS, same-origin
                                    │ session cookie + CSRF
                                    ▼
┌──────────────────────────────────────────────────────────────────┐
│                  Django + Gunicorn (single service)              │
│                                                                  │
│   /                ─ chat UI (login_required, renders template)  │
│   /accounts/*      ─ Django auth: Login, Logout, SignUp          │
│   /api/threads/    ─ CRUD for chat threads                       │
│   /api/threads/<id>/chat/ ─ Send message, run LLM, persist turn  │
│   /api/upload-document/   ─ Extract → chunk → embed → FAISS      │
│                                                                  │
│   Whitenoise serves /static/ in production.                      │
│                                                                  │
│  ┌────────────┐   ┌──────────────┐   ┌────────────────────────┐  │
│  │ SQLite or  │   │  OpenAI API  │   │ FAISS (per-user dir)   │  │
│  │ Postgres   │   │  chat.compl. │   │ + sentence-transformers│  │
│  │ users /    │   │              │   │ embeddings             │  │
│  │ threads /  │   │              │   │                        │  │
│  │ messages   │   │              │   │                        │  │
│  └────────────┘   └──────────────┘   └────────────────────────┘  │
└──────────────────────────────────────────────────────────────────┘
```

Unauthenticated visitors are bounced to `/accounts/login/`. After a
successful login, Django redirects to `/`, which renders the single-page
chat UI. From the browser, every API call goes to the same origin and
authenticates with the session cookie.

---

## Tech Stack

**Frontend (browser, no build step)**
- Vanilla JavaScript (no framework) with a small module system
- Served as Django templates + static files (Whitenoise in production)
- `marked` for Markdown rendering (loaded from a CDN)

**Backend**
- Django 4.2 with the built-in auth system
- Django REST Framework (session authentication)
- Gunicorn (WSGI server in production)
- Whitenoise (static-file serving in production)

**AI & RAG**
- OpenAI Python SDK (Chat Completions, default model `gpt-4o-mini`)
- FAISS (CPU) for approximate nearest-neighbour search
- OpenAI Embeddings API (default model `text-embedding-3-small`, 1536-dim)
- `pypdf`, `python-docx`, `python-pptx`, `openpyxl` for text extraction

**Storage**
- SQLite locally; Postgres in production (auto-switched via `DATABASE_URL`)
- Filesystem FAISS indexes (one directory per user under `RAG_INDEX_DIR`)

---

## Project Structure

```
ragchatbot/
├── render.yaml                       # Render blueprint
├── README.md
└── backend/
    ├── manage.py
    ├── requirements.txt
    ├── build.sh                      # Render build step
    ├── runtime.txt                   # Python version pin
    ├── .env.example
    ├── db.sqlite3                    # Created on first migrate (local dev)
    ├── rag_indices/                  # Per-user FAISS indexes (gitignored)
    ├── chatapp/                      # Django project
    │   ├── settings.py
    │   ├── urls.py
    │   ├── asgi.py
    │   └── wsgi.py
    └── core/                         # Main Django app
        ├── models.py                 # ChatThread, Message
        ├── serializers.py
        ├── views.py                  # chat_view, auth, threads, chat, upload
        ├── urls.py                   # /api/* routes
        ├── auth_urls.py              # /accounts/* routes
        ├── migrations/
        ├── templates/
        │   ├── chat.html             # SPA shell (rendered for /)
        │   └── registration/         # login, signup, logged_out
        ├── static/core/
        │   ├── css/index.css
        │   └── js/
        │       ├── api.js            # fetch() wrappers (session + CSRF)
        │       ├── chatManager.js    # Chat history, send, RAG indexing UI
        │       ├── themeManager.js   # Light/dark toggle, persistence
        │       ├── uiHelpers.js      # Sidebar, scroll, misc UI
        │       └── renderer.js       # Entry point
        └── llm/
            ├── embeddings.py
            ├── vector_store.py
            ├── rag_pipeline.py
            ├── normal_llm.py
            └── title_generator.py
```

---

## Prerequisites

- **Python 3.10 or newer** (3.11 recommended; Render uses 3.11.9 per
  `runtime.txt`).
- **OpenAI API key** with access to a Chat Completions model.
- The first launch of `sentence-transformers` downloads the embedding
  model (~90 MB). Keep an internet connection available for that initial
  run.

---

## Local Development

Clone the repository and set up the backend:

```bash
git clone https://github.com/Frankythecoder/ragchatbot.git
cd ragchatbot/backend

python -m venv .venv
# Windows
.venv\Scripts\activate
# macOS / Linux
source .venv/bin/activate

pip install -r requirements.txt
cp .env.example .env        # edit and set OPENAI_API_KEY
python manage.py migrate
python manage.py createsuperuser   # optional, for /admin access
python manage.py runserver
```

Open <http://localhost:8000/>. You'll be redirected to the login page;
create an account at <http://localhost:8000/accounts/signup/> and you're in.

---

## Deploying to Render

The repo includes a `render.yaml` blueprint that provisions:

1. A **Python web service** running Django + Gunicorn (serves the chat UI
   and the JSON API).
2. A **managed Postgres database** (`DATABASE_URL` is wired in
   automatically).
3. A **1 GB persistent disk** mounted at `/var/data` so per-user FAISS
   indexes survive deploys.

Deployment steps:

1. Push this repo to GitHub.
2. In the Render dashboard, choose **New → Blueprint** and point it at the
   repository.
3. Render detects `render.yaml` and creates the web service + database.
4. Set `OPENAI_API_KEY` in the web service's environment variables
   (the blueprint marks it `sync: false` so you can fill it in by hand).
5. Trigger a deploy. The build step runs `pip install`, `collectstatic`,
   and `migrate` automatically.
6. Once the service is live, visit the assigned `*.onrender.com` URL,
   sign up, and start chatting.

> **Note on the embedding model.** On the first RAG upload, the
> `sentence-transformers` model (~90 MB) is downloaded into the container.
> Subsequent uploads reuse it for the lifetime of the dyno. Restarts
> re-download it unless you cache it on the persistent disk by setting
> `SENTENCE_TRANSFORMERS_HOME=/var/data/st_cache` in the env vars.

### Free Postgres lifetime

Render's free Postgres tier expires after 90 days. For long-term use,
upgrade the database plan in `render.yaml` (`plan: starter` or higher)
or bring your own Postgres URL via the `DATABASE_URL` env var.

---

## Configuration

Local development reads `backend/.env` via `python-dotenv`. In production,
set the same variables in the Render dashboard. See
[Environment Variables](#environment-variables) for the full list.

> **Security note:** never commit `.env`. The default `SECRET_KEY` in
> `settings.py` is clearly marked insecure and is for development only.
> Set `DJANGO_DEBUG=False` and provide a strong `DJANGO_SECRET_KEY` for any
> non-local deployment. The Render blueprint generates one automatically.

---

## Authentication Flow

Cortex uses Django's built-in session authentication for both the chat UI
and the JSON API (same-origin):

1. A request to `/` hits `chat_view`, which is `@login_required`.
2. Unauthenticated users are redirected to `/accounts/login/` (Django's
   `LoginView`). New users click **Create account**, which submits to
   `/accounts/signup/` (custom `SignUpForm` extending `UserCreationForm`
   with a required, unique email).
3. On successful login, Django redirects to `/` and the chat template is
   rendered.
4. From that point on, every `fetch()` call from the browser is
   same-origin, carries the session cookie, and includes the
   `X-CSRFToken` header (the token is rendered into the page).
5. Logout submits a POST to `/accounts/logout/` (via a `<form>` in the
   settings dropdown) — Django's `LogoutView` clears the session cookie
   and redirects to `/accounts/login/`.

---

## How RAG Works

When you upload a document in RAG mode, Cortex:

1. **Extracts** raw text using the appropriate library
   (`pypdf`, `python-docx`, `python-pptx`, `openpyxl`, or plain read).
2. **Normalizes** whitespace and paragraph breaks, then splits into
   sentence-aware chunks (`RAG_CHUNK_SIZE`, overlap `RAG_CHUNK_OVERLAP`).
3. **Embeds** each chunk via the OpenAI Embeddings API
   (default `text-embedding-3-small`, 1536-dim, L2-normalized). This keeps
   the worker process light enough to fit on small/free hosting tiers —
   no local PyTorch model.
4. **Stores** embeddings in a per-user FAISS `IndexFlatL2` under
   `RAG_INDEX_DIR/<user_id>/`, alongside a `metadata.json` that maps each
   vector back to its source filename and text. Re-uploading the same
   filename replaces the old chunks for that document rather than
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

All routes are served by the Django backend at the same origin as the chat
UI. Local dev: <http://localhost:8000>. Production: `https://<your-app>.onrender.com`.

### Auth (server-rendered)

| Method | Path                  | Description                                                   |
| ------ | --------------------- | ------------------------------------------------------------- |
| GET/POST | `/accounts/login/`  | Django `LoginView` (username + password).                     |
| POST     | `/accounts/logout/` | Django `LogoutView`. Redirects to `/accounts/login/`.         |
| GET/POST | `/accounts/signup/` | Custom `SignUpView` built on `UserCreationForm`.              |
| GET      | `/`                 | `@login_required` chat UI.                                    |

### JSON API (session-authenticated)

All endpoints below require an authenticated session and a valid
`X-CSRFToken` header on write methods.

| Method | Path                                   | Description                                                                    |
| ------ | -------------------------------------- | ------------------------------------------------------------------------------ |
| GET    | `/api/threads/`                        | List the current user's chat threads.                                          |
| POST   | `/api/threads/`                        | Create a new empty thread.                                                     |
| GET    | `/api/threads/<id>/`                   | Thread detail (includes all messages, sources, retrieved chunks, token usage). |
| PATCH  | `/api/threads/<id>/`                   | Rename a thread (`{"title": "..."}`).                                          |
| DELETE | `/api/threads/<id>/`                   | Delete a thread and its messages (cascade).                                    |
| POST   | `/api/threads/<id>/chat/`              | Send a message. Body: `{ "message", "files", "mode": "normal" \| "rag" }`.     |
| POST   | `/api/upload-document/`                | Multipart upload (`file`, optional `file_path`). Indexes into the user's FAISS store. |

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

| Variable                      | Default              | Purpose                                                 |
| ----------------------------- | -------------------- | ------------------------------------------------------- |
| `DJANGO_SECRET_KEY`           | insecure dev default | Django cryptographic secret. **Set in production.**     |
| `DJANGO_DEBUG`                | `True`               | Set to `False` in production.                           |
| `DJANGO_ALLOWED_HOSTS`        | `localhost,127.0.0.1`| Comma-separated hostnames.                              |
| `DJANGO_CSRF_TRUSTED_ORIGINS` | — (empty)            | Comma-separated full origins (e.g. `https://x.onrender.com`). |
| `DATABASE_URL`                | — (unset → SQLite)   | Postgres URL. Render's blueprint fills this in.         |
| `OPENAI_API_KEY`              | — (required)         | Your OpenAI API key.                                    |
| `OPENAI_MODEL`                | `gpt-4o-mini`        | Chat Completions model name.                            |
| `MAX_HISTORY_MESSAGES`        | `20`                 | Max previous turns sent with each chat request.         |
| `RAG_CHUNK_SIZE`              | `2000`               | Target characters per chunk.                            |
| `RAG_CHUNK_OVERLAP`           | `300`                | Overlap (in chars, approximated via word slicing).      |
| `RAG_TOP_K`                   | `8`                  | Chunks surfaced to the LLM per RAG query.               |
| `RAG_EMBEDDING_MODEL`         | `text-embedding-3-small` | OpenAI embedding model id.                          |
| `RAG_EMBEDDING_DIM`           | `1536`               | Vector dimension. `text-embedding-3-*` supports reducing this. |
| `RAG_INDEX_DIR`               | `backend/rag_indices`| Where per-user FAISS indexes are written.               |

---

## Troubleshooting

**The browser shows "DisallowedHost" or "CSRF verification failed".**
Set `DJANGO_ALLOWED_HOSTS` to include your hostname and
`DJANGO_CSRF_TRUSTED_ORIGINS` to include the full `https://...` origin.
On Render, the blueprint sets `RENDER_EXTERNAL_HOSTNAME` automatically;
`settings.py` already trusts it.

**"OPENAI_API_KEY" errors on first message.**
Set `OPENAI_API_KEY` in `backend/.env` (local) or the Render dashboard
(production) and restart. Environment variables are loaded at process
start.

**First RAG upload takes a while.**
The embedding model is downloaded on first use (~90 MB). Subsequent
uploads reuse the cached model and are fast. To survive restarts on
Render, point `SENTENCE_TRANSFORMERS_HOME` at the persistent disk:
`SENTENCE_TRANSFORMERS_HOME=/var/data/st_cache`.

**RAG mode answers "I don't know" for questions you expect it to answer.**
The retrieved chunks were judged unrelated to the question. Try:
- Uploading more documents or more relevant excerpts,
- Raising `RAG_TOP_K`,
- Lowering `RAG_CHUNK_SIZE` for finer-grained retrieval,
- Rephrasing the question with keywords that appear in the source text.

**Static files 404 in production.**
The build step runs `python manage.py collectstatic --noinput`. If you
deploy without running build, no static files will be served. Whitenoise
serves them at `/static/...`.

---

## License

MIT © Frankythecoder
