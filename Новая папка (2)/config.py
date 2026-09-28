import os
from pathlib import Path

# Load .env if present
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "data"
BOTS_DIR = DATA_DIR / "bots"
TEMPLATES_DIR = BASE_DIR / "templates"
STATIC_DIR = BASE_DIR / "static"
DB_PATH = DATA_DIR / "hosting.db"
DEFAULT_BOT_TEMPLATE = TEMPLATES_DIR / "default_bot"

# Ensure runtime directories exist
DATA_DIR.mkdir(parents=True, exist_ok=True)
BOTS_DIR.mkdir(parents=True, exist_ok=True)

# Bot & Web Settings
BOT_TOKEN = os.getenv("BOT_TOKEN", "").strip()

# Admin IDs (comma separated telegram user IDs)
raw_admins = os.getenv("ADMIN_IDS", "").split(",")
ADMIN_IDS = [int(x.strip()) for x in raw_admins if x.strip().isdigit()]

# Subscription Channel
REQUIRED_CHANNEL = os.getenv("REQUIRED_CHANNEL", "@AstrixStudio").strip()
CHANNEL_URL = os.getenv("CHANNEL_URL", "https://t.me/AstrixStudio").strip()

# Web Server Settings
WEB_HOST = os.getenv("WEB_HOST", "0.0.0.0")
WEB_PORT = int(os.getenv("WEB_PORT", "8080"))
PUBLIC_URL = os.getenv("PUBLIC_URL", f"http://localhost:{WEB_PORT}").rstrip("/")

# Default Limits
DEFAULT_BOTS_LIMIT = int(os.getenv("DEFAULT_BOTS_LIMIT", "3"))

# Secret for session tokens
SECRET_KEY = os.getenv("SECRET_KEY", "super-secret-telegram-hosting-key-2026")
