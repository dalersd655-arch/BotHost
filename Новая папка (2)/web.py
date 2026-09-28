import os
import json
import logging
from pathlib import Path
from aiohttp import web
import jinja2

from config import (
    WEB_HOST, WEB_PORT, STATIC_DIR, TEMPLATES_DIR,
    CHANNEL_URL, REQUIRED_CHANNEL, PUBLIC_URL, ADMIN_IDS
)
import database
from docker_manager import docker_mgr
from bot import get_bot, check_user_subscription

logger = logging.getLogger(__name__)

# Setup Jinja2
jinja_env = jinja2.Environment(
    loader=jinja2.FileSystemLoader(str(TEMPLATES_DIR)),
    autoescape=jinja2.select_autoescape(["html", "xml"])
)

# In-memory sessions: session_token -> user_id
active_sessions = {}

def get_current_user_from_request(request: web.Request) -> dict:
    session_id = request.cookies.get("session_id")
    if not session_id or session_id not in active_sessions:
        return None
    user_id = active_sessions[session_id]
    return user_id

async def auth_middleware(app, handler):
    async def middleware(request: web.Request):
        session_id = request.cookies.get("session_id")
        user = None
        if session_id and session_id in active_sessions:
            uid = active_sessions[session_id]
            user = await database.get_user_by_id(uid)
            if user and user.get("is_blocked"):
                user = None
        request["user"] = user
        return await handler(request)
    return middleware

# Route handlers
async def handle_login(request: web.Request):
    token = request.query.get("token")
    next_url = request.query.get("next", "/")

    if not token:
        return web.HTTPFound("/login_info")

    telegram_id = await database.verify_and_use_login_token(token)
    if not telegram_id:
        return web.Response(text="Срок действия ссылки истек или токен недействителен. Получите новую ссылку в боте командой /start.", status=400)

    user = await database.get_user_by_telegram_id(telegram_id)
    if not user:
        return web.Response(text="Пользователь не найден.", status=404)

    if user.get("is_blocked"):
        return web.Response(text="Ваш аккаунт заблокирован администратором.", status=403)

    # Check subscription on login
    bot = get_bot()
    if bot:
        is_sub = await check_user_subscription(bot, telegram_id)
        if not is_sub:
            # Create session but redirect to blocked page
            import secrets
            session_id = secrets.token_hex(24)
            active_sessions[session_id] = user["id"]
            resp = web.HTTPFound("/blocked")
            resp.set_cookie("session_id", session_id, max_age=86400 * 7, httponly=True)
            return resp

    import secrets
    session_id = secrets.token_hex(24)
    active_sessions[session_id] = user["id"]

    resp = web.HTTPFound(next_url)
    resp.set_cookie("session_id", session_id, max_age=86400 * 7, httponly=True)
    return resp

async def handle_logout(request: web.Request):
    session_id = request.cookies.get("session_id")
    if session_id in active_sessions:
        del active_sessions[session_id]
    resp = web.HTTPFound("/login_info")
    resp.del_cookie("session_id")
    return resp

async def handle_login_info(request: web.Request):
    template = jinja_env.get_template("login_info.html")
    rendered = template.render(
        channel_url=CHANNEL_URL,
        required_channel=REQUIRED_CHANNEL
    )
    return web.Response(text=rendered, content_type="text/html")

async def handle_blocked(request: web.Request):
    user = request.get("user")
    if not user:
        return web.HTTPFound("/login_info")

    template = jinja_env.get_template("blocked.html")
    rendered = template.render(
        user=user,
        channel_url=CHANNEL_URL,
        required_channel=REQUIRED_CHANNEL
    )
    return web.Response(text=rendered, content_type="text/html")

async def handle_index(request: web.Request):
    user = request.get("user")
    if not user:
        return web.HTTPFound("/login_info")

    # Verify subscription
    bot = get_bot()
    if bot:
        is_sub = await check_user_subscription(bot, user["telegram_id"])
        if not is_sub:
            return web.HTTPFound("/blocked")

    user_bots = await database.get_bots_by_user_id(user["id"])
    docker_available = await docker_mgr.check_docker()

    template = jinja_env.get_template("index.html")
    rendered = template.render(
        user=user,
        bots=user_bots,
        docker_available=docker_available,
        channel_url=CHANNEL_URL,
        required_channel=REQUIRED_CHANNEL
    )
    return web.Response(text=rendered, content_type="text/html")

async def handle_admin(request: web.Request):
    user = request.get("user")
    if not user or not user.get("is_admin"):
        return web.HTTPFound("/")

    all_users = await database.get_all_users()
    all_bots = await database.get_all_bots()
    logs = await database.get_system_logs(limit=50)
    docker_available = await docker_mgr.check_docker()

    template = jinja_env.get_template("admin.html")
    rendered = template.render(
        user=user,
        users=all_users,
        bots=all_bots,
        logs=logs,
        docker_available=docker_available,
        channel_url=CHANNEL_URL,
        required_channel=REQUIRED_CHANNEL
    )
    return web.Response(text=rendered, content_type="text/html")

# API Endpoints
async def api_check_sub(request: web.Request):
    user = request.get("user")
    if not user:
        return web.json_response({"error": "Unauthorized"}, status=401)

    bot = get_bot()
    if not bot:
        return web.json_response({"is_subscribed": True, "message": "Бот не настроен (режим разработки)"})

    is_sub = await check_user_subscription(bot, user["telegram_id"])
    return web.json_response({"is_subscribed": is_sub})

async def api_get_bots(request: web.Request):
    user = request.get("user")
    if not user:
        return web.json_response({"error": "Unauthorized"}, status=401)

    bots = await database.get_bots_by_user_id(user["id"])
    return web.json_response({"bots": bots})

async def api_create_bot(request: web.Request):
    user = request.get("user")
    if not user:
        return web.json_response({"error": "Unauthorized"}, status=401)

    bot_instance = get_bot()
    if bot_instance:
        is_sub = await check_user_subscription(bot_instance, user["telegram_id"])
        if not is_sub:
            return web.json_response({"error": f"Требуется активная подписка на канал {REQUIRED_CHANNEL}!"}, status=403)

    user_bots = await database.get_bots_by_user_id(user["id"])
    if len(user_bots) >= user.get("bots_limit", 3):
        return web.json_response({"error": f"Превышен лимит ботов ({user.get('bots_limit', 3)}). Обратитесь к администратору для увеличения лимита."}, status=400)

    try:
        data = await request.json()
    except Exception:
        return web.json_response({"error": "Invalid JSON"}, status=400)

    name = data.get("name", "").strip()
    bot_token = data.get("bot_token", "").strip()
    env_vars = data.get("env_vars", {})

    if not name or len(name) < 2:
        return web.json_response({"error": "Укажите корректное имя бота (минимум 2 символа)"}, status=400)

    if not bot_token or ":" not in bot_token:
        return web.json_response({"error": "Укажите корректный Telegram Bot Token (полученный у @BotFather)"}, status=400)

    new_bot = await database.create_bot(user["id"], name, bot_token, env_vars)
    # Initialize directory with default template
    docker_mgr.ensure_default_files(user["id"], new_bot["id"])
    await database.add_system_log(f"User {user['telegram_id']} created bot '{name}' (ID: {new_bot['id']})", new_bot["id"])

    return web.json_response({"success": True, "bot": new_bot})

async def api_start_bot(request: web.Request):
    user = request.get("user")
    if not user:
        return web.json_response({"error": "Unauthorized"}, status=401)

    bot_instance = get_bot()
    if bot_instance:
        is_sub = await check_user_subscription(bot_instance, user["telegram_id"])
        if not is_sub:
            return web.json_response({"error": f"Доступ заблокирован: вы отписались от {REQUIRED_CHANNEL}!"}, status=403)

    bot_id = int(request.match_info["id"])
    bot_obj = await database.get_bot_by_id(bot_id)

    if not bot_obj:
        return web.json_response({"error": "Бот не найден"}, status=404)

    if bot_obj["user_id"] != user["id"] and not user.get("is_admin"):
        return web.json_response({"error": "Доступ запрещен"}, status=403)

    success, msg = await docker_mgr.start_bot(bot_obj)
    updated = await database.get_bot_by_id(bot_id)
    return web.json_response({"success": success, "message": msg, "bot": updated})

async def api_stop_bot(request: web.Request):
    user = request.get("user")
    if not user:
        return web.json_response({"error": "Unauthorized"}, status=401)

    bot_id = int(request.match_info["id"])
    bot_obj = await database.get_bot_by_id(bot_id)

    if not bot_obj:
        return web.json_response({"error": "Бот не найден"}, status=404)

    if bot_obj["user_id"] != user["id"] and not user.get("is_admin"):
        return web.json_response({"error": "Доступ запрещен"}, status=403)

    success, msg = await docker_mgr.stop_bot(bot_obj)
    updated = await database.get_bot_by_id(bot_id)
    return web.json_response({"success": success, "message": msg, "bot": updated})

async def api_restart_bot(request: web.Request):
    user = request.get("user")
    if not user:
        return web.json_response({"error": "Unauthorized"}, status=401)

    bot_instance = get_bot()
    if bot_instance:
        is_sub = await check_user_subscription(bot_instance, user["telegram_id"])
        if not is_sub:
            return web.json_response({"error": f"Доступ заблокирован: вы отписались от {REQUIRED_CHANNEL}!"}, status=403)

    bot_id = int(request.match_info["id"])
    bot_obj = await database.get_bot_by_id(bot_id)

    if not bot_obj:
        return web.json_response({"error": "Бот не найден"}, status=404)

    if bot_obj["user_id"] != user["id"] and not user.get("is_admin"):
        return web.json_response({"error": "Доступ запрещен"}, status=403)

    success, msg = await docker_mgr.restart_bot(bot_obj)
    updated = await database.get_bot_by_id(bot_id)
    return web.json_response({"success": success, "message": msg, "bot": updated})

async def api_get_logs(request: web.Request):
    user = request.get("user")
    if not user:
        return web.json_response({"error": "Unauthorized"}, status=401)

    bot_id = int(request.match_info["id"])
    bot_obj = await database.get_bot_by_id(bot_id)

    if not bot_obj:
        return web.json_response({"error": "Бот не найден"}, status=404)

    if bot_obj["user_id"] != user["id"] and not user.get("is_admin"):
        return web.json_response({"error": "Доступ запрещен"}, status=403)

    logs = await docker_mgr.get_logs(bot_obj)
    return web.json_response({"logs": logs})

async def api_delete_bot(request: web.Request):
    user = request.get("user")
    if not user:
        return web.json_response({"error": "Unauthorized"}, status=401)

    bot_id = int(request.match_info["id"])
    bot_obj = await database.get_bot_by_id(bot_id)

    if not bot_obj:
        return web.json_response({"error": "Бот не найден"}, status=404)

    if bot_obj["user_id"] != user["id"] and not user.get("is_admin"):
        return web.json_response({"error": "Доступ запрещен"}, status=403)

    await docker_mgr.cleanup_bot(bot_obj)
    await database.delete_bot(bot_id)
    await database.add_system_log(f"Bot {bot_id} deleted by user {user['telegram_id']}", bot_id)
    return web.json_response({"success": True})

async def api_get_files(request: web.Request):
    user = request.get("user")
    if not user:
        return web.json_response({"error": "Unauthorized"}, status=401)

    bot_id = int(request.match_info["id"])
    bot_obj = await database.get_bot_by_id(bot_id)

    if not bot_obj:
        return web.json_response({"error": "Бот не найден"}, status=404)

    if bot_obj["user_id"] != user["id"] and not user.get("is_admin"):
        return web.json_response({"error": "Доступ запрещен"}, status=403)

    files = await docker_mgr.list_files(bot_obj["user_id"], bot_id)
    return web.json_response({"files": files})

async def api_upload_file(request: web.Request):
    user = request.get("user")
    if not user:
        return web.json_response({"error": "Unauthorized"}, status=401)

    bot_id = int(request.match_info["id"])
    bot_obj = await database.get_bot_by_id(bot_id)

    if not bot_obj:
        return web.json_response({"error": "Бот не найден"}, status=404)

    if bot_obj["user_id"] != user["id"] and not user.get("is_admin"):
        return web.json_response({"error": "Доступ запрещен"}, status=403)

    reader = await request.multipart()
    saved = 0
    while True:
        field = await reader.next()
        if field is None:
            break
        if field.name == "file":
            filename = field.filename or "uploaded.txt"
            content = await field.read()
            await docker_mgr.save_uploaded_files(bot_obj["user_id"], bot_id, filename, content)
            saved += 1

    return web.json_response({"success": True, "saved_files": saved})

# Admin APIs
async def api_admin_block_user(request: web.Request):
    user = request.get("user")
    if not user or not user.get("is_admin"):
        return web.json_response({"error": "Forbidden"}, status=403)

    target_user_id = int(request.match_info["id"])
    data = await request.json()
    is_blocked = bool(data.get("is_blocked"))

    await database.update_user_block_status(target_user_id, is_blocked)
    # If blocked, stop their bots
    if is_blocked:
        bots = await database.get_bots_by_user_id(target_user_id)
        for b in bots:
            await docker_mgr.stop_bot(b)

    await database.add_system_log(f"Admin {user['telegram_id']} updated block status of user {target_user_id} to {is_blocked}")
    return web.json_response({"success": True})

async def api_admin_set_limit(request: web.Request):
    user = request.get("user")
    if not user or not user.get("is_admin"):
        return web.json_response({"error": "Forbidden"}, status=403)

    target_user_id = int(request.match_info["id"])
    data = await request.json()
    limit = int(data.get("limit", 3))

    await database.update_user_limit(target_user_id, limit)
    await database.add_system_log(f"Admin {user['telegram_id']} changed bot limit of user {target_user_id} to {limit}")
    return web.json_response({"success": True})

async def api_admin_stop_bot(request: web.Request):
    user = request.get("user")
    if not user or not user.get("is_admin"):
        return web.json_response({"error": "Forbidden"}, status=403)

    bot_id = int(request.match_info["id"])
    bot_obj = await database.get_bot_by_id(bot_id)
    if not bot_obj:
        return web.json_response({"error": "Бот не найден"}, status=404)

    success, msg = await docker_mgr.stop_bot(bot_obj)
    await database.add_system_log(f"Admin {user['telegram_id']} forced stop on bot {bot_id}")
    return web.json_response({"success": success, "message": msg})

def create_web_app() -> web.Application:
    app = web.Application(middlewares=[auth_middleware], client_max_size=50 * 1024 * 1024)

    # Routes
    app.router.add_get("/", handle_index)
    app.router.add_get("/login", handle_login)
    app.router.add_get("/logout", handle_logout)
    app.router.add_get("/login_info", handle_login_info)
    app.router.add_get("/blocked", handle_blocked)
    app.router.add_get("/admin", handle_admin)

    # API routes
    app.router.add_get("/api/check-sub", api_check_sub)
    app.router.add_get("/api/bots", api_get_bots)
    app.router.add_post("/api/bots", api_create_bot)
    app.router.add_post("/api/bots/{id}/start", api_start_bot)
    app.router.add_post("/api/bots/{id}/stop", api_stop_bot)
    app.router.add_post("/api/bots/{id}/restart", api_restart_bot)
    app.router.add_get("/api/bots/{id}/logs", api_get_logs)
    app.router.add_delete("/api/bots/{id}", api_delete_bot)
    app.router.add_get("/api/bots/{id}/files", api_get_files)
    app.router.add_post("/api/bots/{id}/upload", api_upload_file)

    # Admin API
    app.router.add_post("/api/admin/users/{id}/block", api_admin_block_user)
    app.router.add_post("/api/admin/users/{id}/limit", api_admin_set_limit)
    app.router.add_post("/api/admin/bots/{id}/stop", api_admin_stop_bot)

    # Static assets
    if STATIC_DIR.exists():
        app.router.add_static("/static", str(STATIC_DIR))

    return app
