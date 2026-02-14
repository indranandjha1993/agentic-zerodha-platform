from pathlib import Path

import environ

env = environ.Env(DEBUG=(bool, False))

BASE_DIR = Path(__file__).resolve().parents[3]

SECRET_KEY = env("DJANGO_SECRET_KEY", default="change-me")
DEBUG = env.bool("DJANGO_DEBUG", default=False)
ALLOWED_HOSTS = env.list("DJANGO_ALLOWED_HOSTS", default=["localhost", "127.0.0.1"])

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "rest_framework",
    "apps.core",
    "apps.accounts",
    "apps.broker_kite",
    "apps.agents",
    "apps.approvals",
    "apps.risk",
    "apps.execution",
    "apps.market_data",
    "apps.audit",
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
        "DIRS": [BASE_DIR / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    }
]

WSGI_APPLICATION = "config.wsgi.application"
ASGI_APPLICATION = "config.asgi.application"

DATABASES = {
    "default": env.db(
        "DATABASE_URL",
        default=f"sqlite:///{BASE_DIR / 'db.sqlite3'}",
    )
}

AUTH_PASSWORD_VALIDATORS = [
    {
        "NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator",
    },
    {
        "NAME": "django.contrib.auth.password_validation.MinimumLengthValidator",
    },
    {
        "NAME": "django.contrib.auth.password_validation.CommonPasswordValidator",
    },
    {
        "NAME": "django.contrib.auth.password_validation.NumericPasswordValidator",
    },
]

LANGUAGE_CODE = "en-us"
TIME_ZONE = "Asia/Kolkata"
USE_I18N = True
USE_TZ = True

STATIC_URL = "/static/"
STATIC_ROOT = BASE_DIR / "staticfiles"
MEDIA_URL = "/media/"
MEDIA_ROOT = BASE_DIR / "media"

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

REST_FRAMEWORK = {
    "DEFAULT_PERMISSION_CLASSES": ["rest_framework.permissions.IsAuthenticated"],
    "DEFAULT_AUTHENTICATION_CLASSES": [
        "rest_framework.authentication.SessionAuthentication",
        "rest_framework.authentication.BasicAuthentication",
    ],
}

CELERY_BROKER_URL = env(
    "CELERY_BROKER_URL",
    default="redis://localhost:6379/0",
)
CELERY_RESULT_BACKEND = env(
    "CELERY_RESULT_BACKEND",
    default="redis://localhost:6379/1",
)
CELERY_TASK_TRACK_STARTED = True
CELERY_TASK_TIME_LIMIT = env.int("CELERY_TASK_TIME_LIMIT", default=60)
CELERY_TASK_SOFT_TIME_LIMIT = env.int("CELERY_TASK_SOFT_TIME_LIMIT", default=45)
CELERY_BEAT_SCHEDULE = {
    "process-expired-approval-requests-every-minute": {
        "task": "apps.approvals.tasks.process_expired_approval_requests_task",
        "schedule": 60.0,
    },
}

OPENROUTER_BASE_URL = env("OPENROUTER_BASE_URL", default="https://openrouter.ai/api/v1")
OPENROUTER_API_KEY = env("OPENROUTER_API_KEY", default="")
OPENROUTER_DEFAULT_MODEL = env("OPENROUTER_DEFAULT_MODEL", default="openai/gpt-4o-mini")
OPENROUTER_HTTP_REFERER = env("OPENROUTER_HTTP_REFERER", default="")
OPENROUTER_APP_TITLE = env("OPENROUTER_APP_TITLE", default="")
OPENROUTER_ANALYST_MAX_STEPS = env.int("OPENROUTER_ANALYST_MAX_STEPS", default=6)
AGENT_ANALYSIS_ASYNC_DEFAULT = env.bool("AGENT_ANALYSIS_ASYNC_DEFAULT", default=True)
ANALYSIS_WEBHOOK_REQUEST_TIMEOUT_SECONDS = env.int(
    "ANALYSIS_WEBHOOK_REQUEST_TIMEOUT_SECONDS",
    default=10,
)
ANALYSIS_WEBHOOK_RESPONSE_MAX_CHARS = env.int(
    "ANALYSIS_WEBHOOK_RESPONSE_MAX_CHARS",
    default=1500,
)
ANALYSIS_WEBHOOK_MAX_ATTEMPTS = env.int("ANALYSIS_WEBHOOK_MAX_ATTEMPTS", default=3)
ANALYSIS_WEBHOOK_RETRY_BASE_SECONDS = env.int(
    "ANALYSIS_WEBHOOK_RETRY_BASE_SECONDS",
    default=30,
)
ANALYSIS_WEBHOOK_RETRY_MAX_SECONDS = env.int(
    "ANALYSIS_WEBHOOK_RETRY_MAX_SECONDS",
    default=900,
)
KITE_API_BASE_URL = env("KITE_API_BASE_URL", default="https://api.kite.trade")
KITE_API_KEY = env("KITE_API_KEY", default="")
KITE_ACCESS_TOKEN = env("KITE_ACCESS_TOKEN", default="")
ENCRYPTION_KEY = env("ENCRYPTION_KEY", default="")
TELEGRAM_BOT_TOKEN = env("TELEGRAM_BOT_TOKEN", default="")
TELEGRAM_WEBHOOK_SECRET = env("TELEGRAM_WEBHOOK_SECRET", default="")
TELEGRAM_API_BASE_URL = env("TELEGRAM_API_BASE_URL", default="https://api.telegram.org")
SERPER_API_KEY = env("SERPER_API_KEY", default="")
GOOGLE_CSE_API_KEY = env("GOOGLE_CSE_API_KEY", default="")
GOOGLE_CSE_ENGINE_ID = env("GOOGLE_CSE_ENGINE_ID", default="")
WEB_TOOL_USER_AGENT = env(
    "WEB_TOOL_USER_AGENT",
    default="agentic-zerodha-platform/0.1 (+https://openrouter.ai/)",
)
