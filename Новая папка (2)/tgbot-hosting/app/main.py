import asyncio, re
from contextlib import asynccontextmanager
from datetime import timedelta
from pathlib import Path
from fastapi import FastAPI, Depends, HTTPException, Request, UploadFile, File, Form, BackgroundTasks
from fastapi.responses import FileResponse, RedirectResponse
from sqlalchemy import func
from sqlalchemy.orm import Session
from . import config as C, docker_mgr as D
from .db import Base, engine, SessionLocal, get_db, User, Bot, ActionLog, log_action, now
from .security import encrypt, decrypt, make_session, read_session, verify_telegram_login
from .subscription import check_sync

# ---------- фон: перепроверка подписок ----------
def recheck_all():
    with SessionLocal() as db:
        for u in db.query(User).filter(User.is_subscribed.is_(True)).all():
            r = check_sync(u.id)
            if r is False:
                u.is_subscribed = False
                stop_user_bots(db, u.id)
                log_action(db, u.id, "unsubscribed", "боты остановлены")
            if r is not None: u.checked_at = now()
            db.commit()
            import time; time.sleep(0.05)

async def _loop():
    while True:
        await asyncio.sleep(C.RECHECK_INTERVAL)
        try: await asyncio.to_thread(recheck_all)
        except Exception as e: print("recheck error:", e)

@asynccontextmanager
async def lifespan(app):
    Base.metadata.create_all(engine)
    D.ensure_network()
    t = asyncio.create_task(_loop())
    yield
    t.cancel()

app = FastAPI(lifespan=lifespan, docs_url=None, redoc_url=None)
STATIC = Path(__file__).parent / "static"

def stop_user_bots(db, uid):
    for b in db.query(Bot).filter(Bot.user_id == uid).all():
        try: D.stop(b.id)
        except Exception: pass

# ---------- зависимости ----------
def current_user(request: Request, db: Session = Depends(get_db)) -> User:
    uid = read_session(request.cookies.get("session"))
    u = db.get(User, uid) if uid else None
    if not u: raise HTTPException(401, "not_authenticated")
    if u.is_blocked: raise HTTPException(403, "blocked")
    age = (now() - u.checked_at).total_seconds()
    if age > (300 if u.is_subscribed else 10):
        r = check_sync(u.id)
        if r is not None:
            if u.is_subscribed and r is False:
                stop_user_bots(db, u.id)
                log_action(db, u.id, "unsubscribed", "боты остановлены")
            u.is_subscribed, u.checked_at = r, now()
            db.commit()
    if not u.is_subscribed: raise HTTPException(403, "not_subscribed")
    return u

def admin_user(u: User = Depends(current_user)) -> User:
    if u.id not in C.ADMIN_IDS: raise HTTPException(403, "forbidden")
    return u

def own_bot(bot_id: int, u: User, db: Session) -> Bot:
    b = db.get(Bot, bot_id)
    if not b or b.user_id != u.id: raise HTTPException(404, "Бот не найден")   # чужие боты = 404
    return b

# ---------- страницы и авторизация ----------
@app.get("/")
def index(): return FileResponse(STATIC / "index.html")

@app.get("/api/config")
def config(): return {"bot": C.GATE_BOT_USERNAME, "channel_url": C.CHANNEL_URL, "dev": C.DEV_MODE}

@app.get("/auth/telegram")
def auth_telegram(request: Request, db: Session = Depends(get_db)):
    data = dict(request.query_params)
    if not verify_telegram_login(data): raise HTTPException(400, "Неверная подпись Telegram")
    uid = int(data["id"])
    u = db.get(User, uid) or User(id=uid)
    u.username = data.get("username")
    db.add(u); db.commit()
    resp = RedirectResponse("/", status_code=302)
    resp.set_cookie("session", make_session(uid), httponly=True, samesite="lax",
                    secure=C.COOKIE_SECURE, max_age=7 * 86400)
    log_action(db, uid, "login")
    return resp

@app.get("/auth/dev")
def auth_dev(id: int, db: Session = Depends(get_db)):
    """Тестовый вход по Telegram ID. Работает только при DEV_MODE=1. Подписка на канал всё равно проверяется."""
    if not C.DEV_MODE: raise HTTPException(404)
    u = db.get(User, id) or User(id=id)
    db.add(u); db.commit()
    resp = RedirectResponse("/", status_code=302)
    resp.set_cookie("session", make_session(id), httponly=True, samesite="lax", secure=C.COOKIE_SECURE, max_age=7 * 86400)
    log_action(db, id, "dev_login")
    return resp

@app.post("/auth/logout")
def logout():
    resp = RedirectResponse("/", status_code=302); resp.delete_cookie("session"); return resp

# ---------- боты ----------
def bot_view(b: Bot):
    st = D.status(b.id) if b.state == "ready" else b.state
    return {"id": b.id, "name": b.name, "status": st, "error": b.error, "created": b.created_at.isoformat()}

@app.get("/api/me")
def me(u: User = Depends(current_user), db: Session = Depends(get_db)):
    bots = db.query(Bot).filter(Bot.user_id == u.id).all()
    running = sum(1 for b in bots if b.state == "ready" and D.status(b.id) == "running")
    return {"id": u.id, "username": u.username, "is_admin": u.id in C.ADMIN_IDS,
            "bots": len(bots), "max_bots": u.max_bots,
            "ram_used_mb": running * u.mem_mb, "ram_limit_mb": u.max_bots * u.mem_mb}

@app.get("/api/bots")
def list_bots(u: User = Depends(current_user), db: Session = Depends(get_db)):
    return [bot_view(b) for b in db.query(Bot).filter(Bot.user_id == u.id).order_by(Bot.id)]

def build_and_run(bot_id: int):
    with SessionLocal() as db:
        b = db.get(Bot, bot_id); u = db.get(User, b.user_id)
        try:
            D.build_image(bot_id)
            D.run(bot_id, u.id, decrypt(b.token_enc), u.mem_mb, u.cpu)
            b.state, b.error = "ready", None
        except Exception as e:
            b.state, b.error = "error", str(e)[:500]
        db.commit()
        log_action(db, u.id, "build", f"bot={bot_id} state={b.state}")

@app.post("/api/bots")
def create_bot(bg: BackgroundTasks, name: str = Form(...), token: str = Form(...),
               file: UploadFile = File(...), u: User = Depends(current_user),
               db: Session = Depends(get_db)):
    if not re.fullmatch(r"[\w\- ]{1,40}", name): raise HTTPException(400, "Название: до 40 символов, буквы/цифры/-/пробел")
    if not re.fullmatch(r"\d{5,}:[\w-]{30,}", token): raise HTTPException(400, "Похоже, токен неверный")
    if db.query(func.count(Bot.id)).filter(Bot.user_id == u.id).scalar() >= u.max_bots:
        raise HTTPException(400, f"Лимит ботов: {u.max_bots}")
    if not (file.filename or "").lower().endswith(".zip"): raise HTTPException(400, "Нужен .zip архив")
    data = file.file.read(C.MAX_UPLOAD + 1)
    if len(data) > C.MAX_UPLOAD: raise HTTPException(413, f"Файл больше {C.MAX_UPLOAD // 1024 // 1024} МБ")
    b = Bot(user_id=u.id, name=name, token_enc=encrypt(token))
    db.add(b); db.commit()
    try: D.safe_extract(data, D.bot_dir(b.id))
    except Exception as e:
        D.delete_all(b.id); db.delete(b); db.commit()
        raise HTTPException(400, f"Неверный проект: {e}")
    log_action(db, u.id, "create_bot", f"bot={b.id}")
    bg.add_task(build_and_run, b.id)
    return bot_view(b)

@app.post("/api/bots/{bot_id}/{action}")
def control(bot_id: int, action: str, u: User = Depends(current_user), db: Session = Depends(get_db)):
    b = own_bot(bot_id, u, db)
    if b.state != "ready": raise HTTPException(400, "Бот ещё собирается или собрался с ошибкой")
    if action == "stop": D.stop(b.id)
    elif action in ("start", "restart"):
        D.run(b.id, u.id, decrypt(b.token_enc), u.mem_mb, u.cpu)
    else: raise HTTPException(404)
    log_action(db, u.id, action, f"bot={b.id}")
    return bot_view(b)

@app.get("/api/bots/{bot_id}/logs")
def bot_logs(bot_id: int, u: User = Depends(current_user), db: Session = Depends(get_db)):
    b = own_bot(bot_id, u, db)
    txt = D.logs(b.id) if b.state == "ready" else (b.error or b.state)
    return {"logs": txt.replace(decrypt(b.token_enc), "***")}   # токен никогда не утекает в логи

@app.delete("/api/bots/{bot_id}")
def delete_bot(bot_id: int, u: User = Depends(current_user), db: Session = Depends(get_db)):
    b = own_bot(bot_id, u, db)
    D.delete_all(b.id); db.delete(b); db.commit()
    log_action(db, u.id, "delete_bot", f"bot={bot_id}")
    return {"ok": True}

# ---------- админка (API) ----------
@app.get("/api/admin/stats")
def admin_stats(a: User = Depends(admin_user), db: Session = Depends(get_db)):
    return {"users": db.query(func.count(User.id)).scalar(),
            "bots": db.query(func.count(Bot.id)).scalar(),
            "running_containers": D.running_count()}

@app.get("/api/admin/users")
def admin_users(a: User = Depends(admin_user), db: Session = Depends(get_db)):
    return [{"id": x.id, "username": x.username, "blocked": x.is_blocked, "subscribed": x.is_subscribed,
             "max_bots": x.max_bots, "mem_mb": x.mem_mb, "cpu": x.cpu} for x in db.query(User).all()]

@app.post("/api/admin/users/{uid}/block")
def admin_block(uid: int, blocked: bool = True, a: User = Depends(admin_user), db: Session = Depends(get_db)):
    u = db.get(User, uid)
    if not u: raise HTTPException(404)
    u.is_blocked = blocked; db.commit()
    if blocked: stop_user_bots(db, uid)
    log_action(db, a.id, "block" if blocked else "unblock", f"user={uid}")
    return {"ok": True}

@app.post("/api/admin/users/{uid}/limits")
def admin_limits(uid: int, max_bots: int | None = None, mem_mb: int | None = None, cpu: float | None = None,
                 a: User = Depends(admin_user), db: Session = Depends(get_db)):
    u = db.get(User, uid)
    if not u: raise HTTPException(404)
    if max_bots is not None: u.max_bots = max(0, min(max_bots, 50))
    if mem_mb is not None: u.mem_mb = max(32, min(mem_mb, 2048))
    if cpu is not None: u.cpu = max(0.05, min(cpu, 4))
    db.commit(); log_action(db, a.id, "limits", f"user={uid}")
    return {"ok": True}

@app.get("/api/admin/logs")
def admin_logs(a: User = Depends(admin_user), db: Session = Depends(get_db)):
    rows = db.query(ActionLog).order_by(ActionLog.id.desc()).limit(200).all()
    return [{"user": r.user_id, "action": r.action, "details": r.details, "at": r.at.isoformat()} for r in rows]
