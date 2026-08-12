import os
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

BASE_DIR = Path(__file__).resolve().parent.parent

SECRET_KEY = os.environ.get(
    "DJANGO_SECRET_KEY", "django-insecure-change-me-in-production"
)

DEBUG = os.environ.get("DJANGO_DEBUG", "True").lower() == "true"

# Comma-separated list of hostnames, e.g.
# "cortex.onrender.com,localhost,127.0.0.1"
ALLOWED_HOSTS = [
    h.strip()
    for h in os.environ.get("DJANGO_ALLOWED_HOSTS", "localhost,127.0.0.1").split(",")
    if h.strip()
]

# Render injects the external hostname here; trust it automatically.
RENDER_EXTERNAL_HOSTNAME = os.environ.get("RENDER_EXTERNAL_HOSTNAME")
if RENDER_EXTERNAL_HOSTNAME and RENDER_EXTERNAL_HOSTNAME not in ALLOWED_HOSTS:
    ALLOWED_HOSTS.append(RENDER_EXTERNAL_HOSTNAME)

# Required for cross-origin POST/PATCH/DELETE when behind HTTPS (Render).
CSRF_TRUSTED_ORIGINS = [
    o.strip()
    for o in os.environ.get("DJANGO_CSRF_TRUSTED_ORIGINS", "").split(",")
    if o.strip()
]
if RENDER_EXTERNAL_HOSTNAME:
    CSRF_TRUSTED_ORIGINS.append(f"https://{RENDER_EXTERNAL_HOSTNAME}")

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "rest_framework",
    "core",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    # Whitenoise — serves static files in production. Must come immediately
    # after SecurityMiddleware.
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "chatapp.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.debug",
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]

WSGI_APPLICATION = "chatapp.wsgi.application"

# Default to SQLite locally; on Render, DATABASE_URL is set and we use Postgres.
DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": BASE_DIR / "db.sqlite3",
    }
}

DATABASE_URL = os.environ.get("DATABASE_URL")
if DATABASE_URL:
    import dj_database_url

    # conn_health_checks: ping the connection before use so Neon's
    # auto-suspended compute doesn't surface a "connection closed" error
    # to the user after >5 min of idle.
    DATABASES["default"] = dj_database_url.parse(
        DATABASE_URL,
        conn_max_age=600,
        conn_health_checks=True,
        ssl_require=True,
    )

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
]

LANGUAGE_CODE = "en-us"
TIME_ZONE = "UTC"
USE_I18N = True
USE_TZ = True

# --- Static files (Whitenoise) ---
STATIC_URL = "/static/"
STATIC_ROOT = BASE_DIR / "staticfiles"
STATICFILES_STORAGE = "whitenoise.storage.CompressedManifestStaticFilesStorage"

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# --- Django auth ---
LOGIN_URL = "/accounts/login/"
LOGIN_REDIRECT_URL = "/"
LOGOUT_REDIRECT_URL = "/accounts/login/"

# --- Session lifetime: stay logged in until manual logout ---
# Signed-cookie backend: the whole session lives in the cookie itself,
# signed with SECRET_KEY. No server-side state to lose, so the user stays
# logged in across server restarts AND browser restarts. Same UX as the
# Electron app, which persisted JWT tokens to disk.
SESSION_ENGINE = "django.contrib.sessions.backends.signed_cookies"
SESSION_COOKIE_AGE = 60 * 60 * 24 * 365  # 1 year
SESSION_SAVE_EVERY_REQUEST = True        # roll the expiry on every request
SESSION_EXPIRE_AT_BROWSER_CLOSE = False  # don't tie cookie to browser session

# --- Django REST Framework ---
# Session auth: the chat UI is served from the same origin as the API, so the
# session cookie + CSRF token are all that's needed.
REST_FRAMEWORK = {
    "DEFAULT_AUTHENTICATION_CLASSES": [
        "rest_framework.authentication.SessionAuthentication",
    ],
    "DEFAULT_PERMISSION_CLASSES": [
        "rest_framework.permissions.IsAuthenticated",
    ],
}

DATA_UPLOAD_MAX_MEMORY_SIZE = 52428800  # 50 MB

# Route uncaught view exceptions to stdout so Render's free-tier "Logs" view
# (which only surfaces gunicorn's stdout, not Python's stderr) shows tracebacks.
LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "handlers": {
        "console": {"class": "logging.StreamHandler"},
    },
    "loggers": {
        "django.request": {
            "handlers": ["console"],
            "level": "ERROR",
            "propagate": False,
        },
    },
}

# --- Production security flags (auto-enabled when DEBUG is False) ---
if not DEBUG:
    SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
    SECURE_SSL_REDIRECT = (
        os.environ.get("DJANGO_SECURE_SSL_REDIRECT", "True").lower() == "true"
    )
    SESSION_COOKIE_SECURE = True
    CSRF_COOKIE_SECURE = True
    SECURE_HSTS_SECONDS = int(os.environ.get("DJANGO_SECURE_HSTS_SECONDS", "0"))
    SECURE_HSTS_INCLUDE_SUBDOMAINS = SECURE_HSTS_SECONDS > 0
    SECURE_HSTS_PRELOAD = SECURE_HSTS_SECONDS > 0
    X_FRAME_OPTIONS = "DENY"
    SECURE_CONTENT_TYPE_NOSNIFF = True

# --- OpenAI ---
OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY", "").strip()
OPENAI_MODEL = os.environ.get("OPENAI_MODEL", "gpt-4o-mini")
MAX_HISTORY_MESSAGES = int(os.environ.get("MAX_HISTORY_MESSAGES", "20"))

# --- Access control ---
# Non-superuser accounts are capped at this many chat requests per calendar
# day (UTC). Superusers are unlimited and are the only accounts that can
# upload documents to the RAG knowledge base.
DAILY_MESSAGE_LIMIT = int(os.environ.get("DAILY_MESSAGE_LIMIT", "20"))

# --- RAG ---
RAG_CHUNK_SIZE = int(os.environ.get("RAG_CHUNK_SIZE", "2000"))
RAG_CHUNK_OVERLAP = int(os.environ.get("RAG_CHUNK_OVERLAP", "300"))
RAG_TOP_K = int(os.environ.get("RAG_TOP_K", "12"))
# Embedding model — uses the OpenAI Embeddings API (no local torch model).
# Defaults to text-embedding-3-small at 1536 dims; for cheaper/smaller
# vectors set RAG_EMBEDDING_DIM to e.g. 512.
RAG_EMBEDDING_MODEL = os.environ.get("RAG_EMBEDDING_MODEL", "text-embedding-3-small")
RAG_EMBEDDING_DIM = int(os.environ.get("RAG_EMBEDDING_DIM", "1536"))
# RAG_INDEX_DIR can be set to a Render persistent disk mount point so indexes
# survive deploys (e.g. "/var/data/rag_indices").
RAG_INDEX_DIR = os.environ.get("RAG_INDEX_DIR", str(BASE_DIR / "rag_indices"))
