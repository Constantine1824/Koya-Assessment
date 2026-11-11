import os
from pathlib import Path

import dj_database_url
from corsheaders.defaults import default_headers

BASE_DIR = Path(__file__).resolve().parent.parent

SECRET_KEY = os.environ.get(
    "DJANGO_SECRET_KEY", "django-insecure-dev-key-change-in-production"
)

DEBUG = os.environ.get("DJANGO_DEBUG", "1") == "1"

ALLOWED_HOSTS = [
    h.strip()
    for h in os.environ.get("DJANGO_ALLOWED_HOSTS", "localhost,127.0.0.1,0.0.0.0").split(",")
    if h.strip()
]

# Render sets this automatically on every service; trusting it means manual
# dashboard deploys work without remembering to extend DJANGO_ALLOWED_HOSTS.
_render_host = os.environ.get("RENDER_EXTERNAL_HOSTNAME")
if _render_host and _render_host not in ALLOWED_HOSTS:
    ALLOWED_HOSTS.append(_render_host)

INSTALLED_APPS = [
    "django.contrib.staticfiles",
    "rest_framework",
    "corsheaders",
    "booking",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "corsheaders.middleware.CorsMiddleware",
    "booking.middleware.ApiKeyMiddleware",
    "django.middleware.common.CommonMiddleware",
]

ROOT_URLCONF = "clinic.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "frontend" / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
            ],
        },
    },
]

WSGI_APPLICATION = "clinic.wsgi.application"

# ---------------------------------------------------------------------------
# Database: PostgreSQL via DATABASE_URL (recommended for deployment).
# Falls back to SQLite for local development when DATABASE_URL is not set.
# ---------------------------------------------------------------------------

DATABASE_URL = os.environ.get("DATABASE_URL", "").strip()

if DATABASE_URL:
    DATABASES = {
        "default": dj_database_url.parse(
            DATABASE_URL,
            conn_max_age=600,
            conn_health_checks=True,
        )
    }
else:
    DATABASES = {
        "default": {
            "ENGINE": "django.db.backends.sqlite3",
            "NAME": BASE_DIR / "db.sqlite3",
            # IMMEDIATE transactions + generous timeout serialize concurrent
            # writers safely, which level 3 relies on for the race test.
            "OPTIONS": {
                "transaction_mode": "IMMEDIATE",
                "timeout": 20,
            },
            # Real file (not shared-cache memory) so tests exercise the same
            # locking semantics as the production server.
            "TEST": {"NAME": BASE_DIR / "test_db.sqlite3", "OPTIONS": {
                "transaction_mode": "IMMEDIATE",
                "timeout": 20,
            }},
        }
    }

# API key required on every JSON API request (level 2). Choose your own key.
X_API_KEY = os.environ.get("CLINIC_API_KEY", "clinic-demo-key")

# Origin of the API as baked into the served page (only needed when the API
# itself lives on a different origin than this Django server).
CLINIC_API_BASE = os.environ.get("CLINIC_API_BASE", "").rstrip("/")

# Rate limiting knobs (level 5): attempts per email per rolling window.
RATE_LIMIT_MAX_ATTEMPTS = int(os.environ.get("RATE_LIMIT_MAX_ATTEMPTS", "5"))
RATE_LIMIT_WINDOW_SECONDS = int(os.environ.get("RATE_LIMIT_WINDOW_SECONDS", "60"))
RATE_LIMIT_EMAILS_TTL_HOURS = int(os.environ.get("RATE_LIMIT_TTL_HOURS", "24"))

# Rolling demo-slot refresh (booking/demo_slots.py): how long the database
# must have been quiet before stale demo slots are re-rolled, and how long
# an explicit POST /reset payload stays untouchable afterwards.
DEMO_SLOT_QUIET_HOURS = int(os.environ.get("DEMO_SLOT_QUIET_HOURS", "24"))
DEMO_SLOT_RESET_GRACE_DAYS = int(os.environ.get("DEMO_SLOT_RESET_GRACE_DAYS", "7"))

APPEND_SLASH = False

REST_FRAMEWORK = {
    "DEFAULT_RENDERER_CLASSES": ["rest_framework.renderers.JSONRenderer"],
    "DEFAULT_PARSER_CLASSES": ["rest_framework.parsers.JSONParser"],
    "DEFAULT_AUTHENTICATION_CLASSES": [],
    "DEFAULT_PERMISSION_CLASSES": [],
    "UNAUTHENTICATED_USER": None,
    "EXCEPTION_HANDLER": "booking.exceptions.custom_exception_handler",
    "DEFAULT_PAGINATION_CLASSES": [],
}

AUTH_PASSWORD_VALIDATORS = []

LANGUAGE_CODE = "en-us"
TIME_ZONE = "UTC"
USE_I18N = True
USE_TZ = True

STATIC_URL = "/static/"
STATICFILES_DIRS = [BASE_DIR / "frontend" / "static"]
STATIC_ROOT = BASE_DIR / "staticfiles"

WHITENOISE_USE_FINDERS = True
WHITENOISE_AUTOREFRESH = DEBUG

SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")

# ---------------------------------------------------------------------------
# CORS: the web page may be hosted anywhere (same server, S3, GitHub
# Pages...), so browsers can call this API cross-origin. Preflights must
# allow the app's custom headers.
# ---------------------------------------------------------------------------
CORS_ALLOW_ALL_ORIGINS = os.environ.get("CORS_ALLOW_ALL_ORIGINS", "1") == "1"
_cors_origins = [
    origin.strip()
    for origin in os.environ.get("CORS_ALLOWED_ORIGINS", "").split(",")
    if origin.strip()
]
if _cors_origins:
    CORS_ALLOWED_ORIGINS = _cors_origins
    CORS_ALLOW_ALL_ORIGINS = False
CORS_ALLOW_HEADERS = default_headers + ("x-api-key", "idempotency-key")
