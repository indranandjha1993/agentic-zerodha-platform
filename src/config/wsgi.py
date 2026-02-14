import os
import sys
from pathlib import Path

from django.core.wsgi import get_wsgi_application

base_dir = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(base_dir / "src"))

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")

application = get_wsgi_application()
