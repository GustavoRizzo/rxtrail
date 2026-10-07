"""Django settings."""

import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent

SECRET_KEY = os.environ.get("DJANGO_SECRET_KEY", "dev-only-not-a-secret")
DEBUG = os.environ.get("DJANGO_DEBUG", "1") == "1"
ALLOWED_HOSTS = os.environ.get("DJANGO_ALLOWED_HOSTS", "localhost,127.0.0.1").split(",")

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "records",
    "web",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "config.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
                "web.context_processors.rxtrail",
            ],
        },
    },
]

WSGI_APPLICATION = "config.wsgi.application"

# The off-chain store. The app connects with a user that owns the
# `transactional` schema and nothing else (see postgres/10-stores.sh).
DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.postgresql",
        "NAME": os.environ.get("POSTGRES_DB", "rxtrail"),
        "USER": os.environ.get("TRANSACTIONAL_DB_USER", "transactional"),
        "PASSWORD": os.environ.get("TRANSACTIONAL_DB_PASSWORD", "transactional"),
        "HOST": os.environ.get("POSTGRES_HOST", "db"),
        "PORT": os.environ.get("POSTGRES_INTERNAL_PORT", "5432"),
        "OPTIONS": {"options": "-c search_path=transactional"},
    }
}

LANGUAGE_CODE = "en-us"
TIME_ZONE = "UTC"
USE_I18N = True
USE_TZ = True
STATIC_URL = "static/"

LOGIN_URL = "/login/"
LOGIN_REDIRECT_URL = "/home/"
# Flash messages in a signed cookie: no database access while rendering.
MESSAGE_STORAGE = "django.contrib.messages.storage.cookie.CookieStorage"

# Demo mode: the login page lists the demo accounts (see `manage.py demo_data`).
RXTRAIL_DEMO_MODE = os.environ.get("RXTRAIL_DEMO_MODE", "1") == "1"
RXTRAIL_DEMO_PASSWORD = "rxtrail-demo"
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# --- Solana ------------------------------------------------------------------

SOLANA_ENDPOINTS = {
    # The validator container, reached over the compose network.
    "localnet": ("http://validator:8899", "ws://validator:8900"),
    "devnet": ("https://api.devnet.solana.com", "wss://api.devnet.solana.com"),
}
SOLANA_NETWORK = os.environ.get("SOLANA_NETWORK", "localnet")
SOLANA_RPC_URL = os.environ.get("SOLANA_RPC_URL") or SOLANA_ENDPOINTS[SOLANA_NETWORK][0]
SOLANA_WS_URL = os.environ.get("SOLANA_WS_URL") or SOLANA_ENDPOINTS[SOLANA_NETWORK][1]
# The local validator as the *browser* reaches it, for explorer links.
SOLANA_EXPLORER_LOCAL_RPC = f"http://localhost:{os.environ.get('LOCALNET_RPC_PORT', '59899')}"

# Keypair files, one per named participant (mounted from the repo's .keys/,
# which is not versioned). The operator pays every fee and rent deposit.
SOLANA_KEYS_DIR = Path(os.environ.get("SOLANA_KEYS_DIR", "/keys"))
SOLANA_OPERATOR = "operator"
