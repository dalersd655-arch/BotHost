import os, json, secrets

def _int(name, default): return int(os.environ.get(name, default))

GATE_BOT_TOKEN = os.environ.get("GATE_BOT_TOKEN", "")
GATE_BOT_USERNAME = os.environ.get("GATE_BOT_USERNAME", "")
CHANNEL = os.environ.get("CHANNEL", "")
CHANNEL_URL = os.environ.get("CHANNEL_URL", "")
PANEL_URL = os.environ.get("PANEL_URL", "http://localhost:8000")
ADMIN_IDS = {int(x) for x in os.environ.get("ADMIN_IDS", "").split(",") if x.strip()}
COOKIE_SECURE = os.environ.get("COOKIE_SECURE", "1") == "1"
DATABASE_URL = os.environ.get("DATABASE_URL", "sqlite:///./dev.db")

MAX_BOTS = _int("MAX_BOTS_PER_USER", 3)
BOT_MEM_MB = _int("BOT_MEM_MB", 128)
BOT_CPU = float(os.environ.get("BOT_CPU", "0.25"))
MAX_UPLOAD = _int("MAX_UPLOAD_MB", 10) * 1024 * 1024
MAX_UNPACKED = MAX_UPLOAD * 5
MAX_FILES = 500

DATA_DIR = os.environ.get("DATA_DIR", "/data")
BOT_NETWORK = "tgbot_net"
RECHECK_INTERVAL = 600   # сек, фоновая перепроверка подписок

DEV_MODE = os.environ.get("DEV_MODE", "0") == "1"   # вход по Telegram ID без домена/HTTPS (ТОЛЬКО для тестов!)

def _load_keys():
    """Если ключи не заданы в .env — генерируем один раз и храним в /data/.keys.json"""
    p = os.path.join(DATA_DIR, ".keys.json")
    try:
        if os.path.exists(p):
            return json.load(open(p))
        from cryptography.fernet import Fernet
        k = {"fernet": Fernet.generate_key().decode(), "secret": secrets.token_urlsafe(48)}
        os.makedirs(DATA_DIR, exist_ok=True)
        json.dump(k, open(p, "w")); os.chmod(p, 0o600)
        return k
    except Exception:
        return {}

_k = _load_keys() if not (os.environ.get("FERNET_KEY") and os.environ.get("SECRET_KEY")) else {}
FERNET_KEY = os.environ.get("FERNET_KEY") or _k.get("fernet", "")
SECRET_KEY = os.environ.get("SECRET_KEY") or _k.get("secret", "dev-secret")
