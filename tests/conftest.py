import os
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

os.environ.setdefault("BOT_TOKEN", "test-token")
os.environ.setdefault("ADMIN_ID", "1")
os.environ.setdefault("ADMIN_IDS", "1")
os.environ.setdefault("TRIBUTE_API_KEY", "test-secret")
os.environ.setdefault("TRIBUTE_WEBHOOK_NOTIFY", "0")
