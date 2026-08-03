import os
from pathlib import Path
from typing import Final

import dj_database_url
from django.core.exceptions import ImproperlyConfigured
from dotenv import load_dotenv


# =========================================================
# Base directory and environment loading
# =========================================================

BASE_DIR: Final[Path] = Path(__file__).resolve().parent.parent

ENV_FILE: Final[Path] = BASE_DIR / ".env"

# System-level environment variables take precedence over .env values.
load_dotenv(dotenv_path=ENV_FILE, override=False)


# =========================================================
# Environment helper functions
# =========================================================

def get_required_env(name: str) -> str:
    """
    Return a required environment variable.

    Django startup fails immediately if the variable is missing
    or contains only whitespace.
    """
    value = os.getenv(name)

    if value is None or not value.strip():
        raise ImproperlyConfigured(
            f"Required environment variable '{name}' is missing or empty."
        )

    return value.strip()


def get_optional_env(name: str, default: str = "") -> str:
    """
    Return an optional environment variable.
    """
    return os.getenv(name, default).strip()


def get_bool_env(name: str, default: bool = False) -> bool:
    """
    Parse a boolean environment variable safely.
    """
    raw_value = os.getenv(name)

    if raw_value is None:
        return default

    normalized_value = raw_value.strip().lower()

    true_values = {"1", "true", "yes", "on"}
    false_values = {"0", "false", "no", "off"}

    if normalized_value in true_values:
        return True

    if normalized_value in false_values:
        return False

    raise ImproperlyConfigured(
        f"Environment variable '{name}' must be one of: "
        f"{', '.join(sorted(true_values | false_values))}."
    )


def get_list_env(name: str, default: str = "") -> list[str]:
    """
    Parse a comma-separated environment variable into a list.
    """
    raw_value = os.getenv(name, default)

    return [
        item.strip()
        for item in raw_value.split(",")
        if item.strip()
    ]


# =========================================================
# Core Django settings
# =========================================================

SECRET_KEY = get_required_env("DJANGO_SECRET_KEY")

DEBUG = get_bool_env("DJANGO_DEBUG", default=False)

ALLOWED_HOSTS = get_list_env(
    "DJANGO_ALLOWED_HOSTS",
    default="127.0.0.1,localhost",
)


# =========================================================
# Application definition
# =========================================================

INSTALLED_APPS = [
    # Django applications
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",

    # Third-party applications
    "rest_framework",
    "corsheaders",
    "django_celery_beat",

    # Local applications
    "apps.research_engine.apps.ResearchEngineConfig",
]


MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",

    # Must appear before CommonMiddleware.
    "corsheaders.middleware.CorsMiddleware",

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
        "DIRS": [
            BASE_DIR / "templates",
        ],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]


WSGI_APPLICATION = "config.wsgi.application"

ASGI_APPLICATION = "config.asgi.application"


# =========================================================
# Database
# =========================================================

DATABASE_URL = get_optional_env("DATABASE_URL")

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
        }
    }


# =========================================================
# Password validation
# =========================================================

AUTH_PASSWORD_VALIDATORS = [
    {
        "NAME": (
            "django.contrib.auth.password_validation."
            "UserAttributeSimilarityValidator"
        ),
    },
    {
        "NAME": (
            "django.contrib.auth.password_validation."
            "MinimumLengthValidator"
        ),
    },
    {
        "NAME": (
            "django.contrib.auth.password_validation."
            "CommonPasswordValidator"
        ),
    },
    {
        "NAME": (
            "django.contrib.auth.password_validation."
            "NumericPasswordValidator"
        ),
    },
]


# =========================================================
# Reddit API configuration
# =========================================================

REDDIT_CLIENT_ID = get_required_env("REDDIT_CLIENT_ID")

REDDIT_CLIENT_SECRET = get_required_env("REDDIT_CLIENT_SECRET")

REDDIT_USER_AGENT = get_required_env("REDDIT_USER_AGENT")


# =========================================================
# Google Gemini API configuration
# =========================================================

GEMINI_API_KEY = get_required_env("GEMINI_API_KEY")


# =========================================================
# Celery configuration
# =========================================================

CELERY_BROKER_URL = get_optional_env(
    "CELERY_BROKER_URL",
    default="redis://127.0.0.1:6379/0",
)

CELERY_RESULT_BACKEND = get_optional_env(
    "CELERY_RESULT_BACKEND",
    default="redis://127.0.0.1:6379/1",
)

CELERY_ACCEPT_CONTENT = ["json"]

CELERY_TASK_SERIALIZER = "json"

CELERY_RESULT_SERIALIZER = "json"

CELERY_TIMEZONE = "Asia/Dhaka"

CELERY_TASK_TRACK_STARTED = True

CELERY_TASK_TIME_LIMIT = 30 * 60

CELERY_TASK_SOFT_TIME_LIMIT = 25 * 60


# =========================================================
# Django REST Framework
# =========================================================

REST_FRAMEWORK = {
    "DEFAULT_AUTHENTICATION_CLASSES": [
        "rest_framework.authentication.SessionAuthentication",
    ],
    "DEFAULT_PERMISSION_CLASSES": [
        "rest_framework.permissions.IsAuthenticated",
    ],
    "DEFAULT_RENDERER_CLASSES": [
        "rest_framework.renderers.JSONRenderer",
        "rest_framework.renderers.BrowsableAPIRenderer",
    ],
    "DEFAULT_PAGINATION_CLASS": (
        "rest_framework.pagination.PageNumberPagination"
    ),
    "PAGE_SIZE": 20,
}


# =========================================================
# CORS and CSRF
# =========================================================

CORS_ALLOWED_ORIGINS = [
    "http://127.0.0.1:3000",
    "http://localhost:3000",
]

CSRF_TRUSTED_ORIGINS = [
    "http://127.0.0.1:3000",
    "http://localhost:3000",
]

CORS_ALLOW_CREDENTIALS = True


# =========================================================
# Internationalization
# =========================================================

LANGUAGE_CODE = "en-us"

TIME_ZONE = "Asia/Dhaka"

USE_I18N = True

USE_TZ = True


# =========================================================
# Static and media files
# =========================================================

STATIC_URL = "/static/"

STATIC_ROOT = BASE_DIR / "staticfiles"

STATICFILES_DIRS = [
    BASE_DIR / "static",
]


MEDIA_URL = "/media/"

MEDIA_ROOT = BASE_DIR / "media"


# =========================================================
# Logging
# =========================================================

LOG_DIR = BASE_DIR / "var" / "logs"

LOG_DIR.mkdir(parents=True, exist_ok=True)


LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {
        "verbose": {
            "format": (
                "{levelname} {asctime} {name} "
                "{module} {process:d} {thread:d} {message}"
            ),
            "style": "{",
        },
        "simple": {
            "format": "{levelname} {asctime} {name}: {message}",
            "style": "{",
        },
    },
    "handlers": {
        "console": {
            "class": "logging.StreamHandler",
            "formatter": "simple",
        },
        "research_file": {
            "class": "logging.handlers.RotatingFileHandler",
            "filename": LOG_DIR / "research_engine.log",
            "maxBytes": 5 * 1024 * 1024,
            "backupCount": 5,
            "formatter": "verbose",
        },
    },
    "loggers": {
        "django": {
            "handlers": ["console"],
            "level": "INFO",
            "propagate": False,
        },
        "apps.research_engine": {
            "handlers": ["console", "research_file"],
            "level": "INFO",
            "propagate": False,
        },
    },
}


# =========================================================
# Security settings
# =========================================================

SESSION_COOKIE_HTTPONLY = True

CSRF_COOKIE_HTTPONLY = True

X_FRAME_OPTIONS = "DENY"

SECURE_CONTENT_TYPE_NOSNIFF = True

SECURE_REFERRER_POLICY = "same-origin"


if not DEBUG:
    SECURE_SSL_REDIRECT = True

    SESSION_COOKIE_SECURE = True

    CSRF_COOKIE_SECURE = True

    SECURE_HSTS_SECONDS = 31536000

    SECURE_HSTS_INCLUDE_SUBDOMAINS = True

    SECURE_HSTS_PRELOAD = True

    SECURE_PROXY_SSL_HEADER = (
        "HTTP_X_FORWARDED_PROTO",
        "https",
    )


# =========================================================
# Default primary key
# =========================================================

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"