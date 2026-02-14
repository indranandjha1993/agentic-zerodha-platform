import os

environment = os.getenv("DJANGO_ENV", "local").lower()

if environment in {"prod", "production"}:
    from .prod import *  # noqa: F401,F403
else:
    from .local import *  # noqa: F401,F403
