from django.core.exceptions import ImproperlyConfigured

from .base import *  # noqa: F401,F403

DEBUG = False

SESSION_COOKIE_SECURE = True
CSRF_COOKIE_SECURE = True
SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
SECURE_HSTS_SECONDS = 60 * 60 * 24 * 365
SECURE_HSTS_INCLUDE_SUBDOMAINS = True
SECURE_HSTS_PRELOAD = True

_required_runtime_secret_keys = tuple(globals().get("REQUIRED_RUNTIME_SECRET_KEYS", ()))
_missing_runtime_secrets = [
    key
    for key in _required_runtime_secret_keys
    if str(globals().get(key, "")).strip() == ""
]
if _missing_runtime_secrets:
    joined = ", ".join(sorted(_missing_runtime_secrets))
    raise ImproperlyConfigured(
        "Missing required runtime environment variables for production startup: "
        f"{joined}"
    )
