import httpx
from . import config as C

_OK = {"member", "administrator", "creator"}
_URL = f"https://api.telegram.org/bot{C.GATE_BOT_TOKEN}/getChatMember"

def _parse(r) -> bool | None:
    j = r.json()
    if not j.get("ok"): return False      # не найден участник / нет доступа
    res = j["result"]
    return res["status"] in _OK or (res["status"] == "restricted" and res.get("is_member", False))

def check_sync(uid: int) -> bool | None:
    """True/False, либо None при сетевой ошибке (тогда состояние не меняем)."""
    try:
        with httpx.Client(timeout=10) as c:
            return _parse(c.get(_URL, params={"chat_id": C.CHANNEL, "user_id": uid}))
    except Exception:
        return None

async def check_async(uid: int) -> bool | None:
    try:
        async with httpx.AsyncClient(timeout=10) as c:
            return _parse(await c.get(_URL, params={"chat_id": C.CHANNEL, "user_id": uid}))
    except Exception:
        return None
