import hashlib, hmac, time
from cryptography.fernet import Fernet
from itsdangerous import URLSafeTimedSerializer
from . import config as C

_fernet = Fernet(C.FERNET_KEY.encode()) if C.FERNET_KEY else None
_ser = URLSafeTimedSerializer(C.SECRET_KEY)

def encrypt(s: str) -> str:
    if not _fernet: raise RuntimeError("FERNET_KEY не задан")
    return _fernet.encrypt(s.encode()).decode()

def decrypt(s: str) -> str:
    return _fernet.decrypt(s.encode()).decode()

def make_session(uid: int) -> str:
    return _ser.dumps(uid)

def read_session(token: str | None):
    if not token: return None
    try: return _ser.loads(token, max_age=7 * 86400)
    except Exception: return None

def verify_telegram_login(data: dict) -> bool:
    """Проверка подписи Telegram Login Widget."""
    d = dict(data)
    h = d.pop("hash", None)
    if not h: return False
    check = "\n".join(f"{k}={d[k]}" for k in sorted(d))
    key = hashlib.sha256(C.GATE_BOT_TOKEN.encode()).digest()
    calc = hmac.new(key, check.encode(), hashlib.sha256).hexdigest()
    try: fresh = time.time() - int(d.get("auth_date", 0)) < 86400
    except ValueError: return False
    return hmac.compare_digest(calc, h) and fresh
