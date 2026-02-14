import os
import sys
from pathlib import Path

from celery import Celery

base_dir = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(base_dir / "src"))
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")

app = Celery("agentic_zerodha_platform")
app.config_from_object("django.conf:settings", namespace="CELERY")
app.autodiscover_tasks()
