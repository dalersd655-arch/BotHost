import logging
import asyncio
from typing import Optional
from aiogram import Bot, Dispatcher, F
from aiogram.filters import CommandStart, Command
from aiogram.types import (
    Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton,
    ReplyKeyboardMarkup, KeyboardButton, WebAppInfo, BotCommand,
    MenuButtonCommands, MenuButtonWebApp
)
from aiogram.exceptions import TelegramBadRequest

from config import BOT_TOKEN, REQUIRED_CHANNEL, CHANNEL_URL, PUBLIC_URL, ADMIN_IDS
import time
import database

logger = logging.getLogger(__name__)

dp = Dispatcher()
_bot_instance: Optional[Bot] = None

# Cache subscription status: user_id -> (is_sub: bool, timestamp: float)
_sub_cache = {}

def get_bot() -> Optional[Bot]:
    return _bot_instance

async def check_user_subscription(bot: Bot, telegram_id: int) -> bool:
    """Check if the user is a member/admin/owner of the required channel."""
    # Admins always bypass channel check
    if telegram_id in ADMIN_IDS:
        await database.update_user_subscription(telegram_id, True)
        return True

    # Check cache (valid for 60 seconds)
    now = time.time()
    if telegram_id in _sub_cache:
        cached_sub, cached_at = _sub_cache[telegram_id]
        if now - cached_at < 60:
            return cached_sub

    channel = REQUIRED_CHANNEL
    try:
        member = await bot.get_chat_member(chat_id=channel, user_id=telegram_id)
        is_sub = member.status in ("member", "administrator", "creator")
        _sub_cache[telegram_id] = (is_sub, now)
        await database.update_user_subscription(telegram_id, is_sub)
        return is_sub
    except TelegramBadRequest as e:
        logger.warning(f"TelegramBadRequest checking subscription for {telegram_id}: {e}")
        # If user left or kicked
        if "user not found" in str(e).lower() or "chat not found" in str(e).lower():
            _sub_cache[telegram_id] = (False, now)
            await database.update_user_subscription(telegram_id, False)
            return False
        _sub_cache[telegram_id] = (False, now)
        await database.update_user_subscription(telegram_id, False)
        return False
    except Exception as e:
        logger.error(f"Error checking subscription for {telegram_id}: {e}")
        return False

def get_sub_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📢 Подписаться на Astrix Studio", url=CHANNEL_URL)],
        [InlineKeyboardButton(text="✅ Проверить подписку", callback_data="check_subscription")]
    ])

def get_main_menu_keyboard(is_admin: bool = False) -> ReplyKeyboardMarkup:
    keyboard = [
        [KeyboardButton(text="🚀 Мой хостинг")],
        [KeyboardButton(text="🤖 Мои боты"), KeyboardButton(text="📊 Статистика")],
        [KeyboardButton(text="ℹ️ Справка")]
    ]
    if is_admin:
        keyboard.append([KeyboardButton(text="👑 Админ-панель")])
    return ReplyKeyboardMarkup(keyboard=keyboard, resize_keyboard=True)

async def setup_bot_commands(bot: Bot):
    commands = [
        BotCommand(command="start", description="🚀 Главное меню хостинга"),
        BotCommand(command="panel", description="🌐 Веб-панель управления"),
        BotCommand(command="bots", description="🤖 Мои активные боты"),
        BotCommand(command="help", description="ℹ️ Инструкция и поддержка")
    ]
    try:
        await bot.set_my_commands(commands)
    except Exception as e:
        logger.warning(f"Could not set bot commands: {e}")

@dp.message(CommandStart())
async def handle_start(message: Message, bot: Bot):
    user_id = message.from_user.id
    username = message.from_user.username
    first_name = message.from_user.first_name

    user = await database.get_or_create_user(user_id, username, first_name)
    if user.get("is_blocked"):
        await message.answer("⛔ Ваш аккаунт заблокирован администратором хостинга.")
        return

    is_subscribed = await check_user_subscription(bot, user_id)
    if not is_subscribed:
        await message.answer(
            f"👋 Здравствуйте, {first_name or 'пользователь'}!\n\n"
            f"Для использования бесплатного облачного хостинга ботов "
            f"необходимо подписаться на официальный канал разработчиков:\n"
            f"👉 {REQUIRED_CHANNEL}\n\n"
            f"После подписки нажмите кнопку «✅ Проверить подписку».",
            reply_markup=get_sub_keyboard()
        )
        return

    is_admin = bool(user.get("is_admin"))
    await message.answer(
        f"🎉 Добро пожаловать в **Telegram Bot Hosting**!\n\n"
        f"Здесь вы можете легко запускать своих ботов 24/7 в изолированных Docker-контейнерах.\n\n"
        f"Ваш лимит ботов: **{user.get('bots_limit', 3)}**\n"
        f"Статус подписки: **Активна ✅**\n\n"
        f"Нажмите «🚀 Мой хостинг», чтобы открыть веб-панель управления ботами.",
        reply_markup=get_main_menu_keyboard(is_admin),
        parse_mode="Markdown"
    )

@dp.callback_query(F.data == "check_subscription")
async def handle_check_sub_callback(callback: CallbackQuery, bot: Bot):
    user_id = callback.from_user.id
    is_subscribed = await check_user_subscription(bot, user_id)

    if is_subscribed:
        user = await database.get_user_by_telegram_id(user_id)
        is_admin = bool(user.get("is_admin")) if user else False
        await callback.message.delete()
        await callback.message.answer(
            "✅ Подписка успешно подтверждена!\n\n"
            "Вам открыт полный доступ к хостингу ботов. Выберите действие в меню ниже:",
            reply_markup=get_main_menu_keyboard(is_admin)
        )
        await callback.answer("Подписка подтверждена! 🎉")
    else:
        await callback.answer(
            f"⚠️ Подписка не обнаружена!\nПожалуйста, вступите в канал {REQUIRED_CHANNEL} и повторите попытку.",
            show_alert=True
        )

@dp.message(F.text.func(lambda t: bool(t and any(k in t.lower() for k in ("хостинг", "panel", "панель")))))
async def handle_open_hosting(message: Message, bot: Bot):
    logger.info(f"User {message.from_user.id} requested hosting panel: {message.text!r}")
    user_id = message.from_user.id
    user = await database.get_user_by_telegram_id(user_id)
    if not user:
        user = await database.get_or_create_user(user_id, message.from_user.username, message.from_user.first_name)

    if user.get("is_blocked"):
        await message.answer("⛔ Доступ заблокирован администратором.")
        return

    is_subscribed = await check_user_subscription(bot, user_id)
    if not is_subscribed:
        await message.answer(
            "⚠️ Доступ к веб-панели заблокирован!\n"
            f"Вы отписались от обязательного канала {REQUIRED_CHANNEL}.\n"
            "Пожалуйста, восстановите подписку:",
            reply_markup=get_sub_keyboard()
        )
        return

    # Generate one-time login token
    token = await database.create_login_token(user_id, ttl_minutes=15)
    login_url = f"{PUBLIC_URL}/login?token={token}"

    text = (
        "🔐 <b>Авторизация в панели хостинга</b>\n\n"
        "Нажмите на ссылку ниже для безопасного входа в веб-панель управления ботами:\n"
        f"👉 <a href=\"{login_url}\"><b>Войти в панель управления</b></a>\n\n"
        f"Прямая ссылка для браузера:\n<code>{login_url}</code>\n\n"
        "⏱ Ссылка действительна 15 минут."
    )

    if not ("localhost" in PUBLIC_URL or "127.0.0.1" in PUBLIC_URL):
        try:
            web_kb = InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="🚀 Войти в панель", url=login_url)]
            ])
            await message.answer(text, reply_markup=web_kb, parse_mode="HTML")
            return
        except Exception:
            pass

    await message.answer(text, parse_mode="HTML", disable_web_page_preview=True)

@dp.message(F.text.func(lambda t: bool(t and any(k in t.lower() for k in ("бот", "bot")))))
async def handle_list_bots(message: Message, bot: Bot):
    logger.info(f"User {message.from_user.id} requested bots list: {message.text!r}")
    user_id = message.from_user.id
    user = await database.get_user_by_telegram_id(user_id)
    if not user:
        user = await database.get_or_create_user(user_id, message.from_user.username, message.from_user.first_name)

    is_subscribed = await check_user_subscription(bot, user_id)
    if not is_subscribed:
        await message.answer(
            f"⚠️ Требуется подписка на {REQUIRED_CHANNEL}:",
            reply_markup=get_sub_keyboard()
        )
        return

    bots = await database.get_bots_by_user_id(user["id"])
    token = await database.create_login_token(user_id, ttl_minutes=15)
    login_url = f"{PUBLIC_URL}/login?token={token}"

    if not bots:
        await message.answer(
            "У вас пока нет созданных ботов.\n\n"
            f"👉 <a href=\"{login_url}\"><b>Открыть веб-панель для создания бота</b></a>",
            reply_markup=get_main_menu_keyboard(bool(user.get("is_admin"))),
            parse_mode="HTML"
        )
        return

    text = "📋 <b>Ваши боты на хостинге:</b>\n\n"
    for b in bots:
        status_icon = "🟢" if b["status"] == "RUNNING" else ("🔴" if b["status"] == "ERROR" else "⚪")
        text += f"{status_icon} <b>{b['name']}</b> (ID: <code>{b['id']}</code>)\n"
        text += f"   Статус: <code>{b['status']}</code>\n\n"

    text += f"👉 <a href=\"{login_url}\"><b>Управлять ботами в веб-панели</b></a>"
    await message.answer(text, parse_mode="HTML", disable_web_page_preview=True)

@dp.message(F.text.func(lambda t: bool(t and any(k in t.lower() for k in ("стат", "stat")))))
async def handle_stats(message: Message, bot: Bot):
    logger.info(f"User {message.from_user.id} requested stats: {message.text!r}")
    user_id = message.from_user.id
    user = await database.get_user_by_telegram_id(user_id)
    if not user:
        user = await database.get_or_create_user(user_id, message.from_user.username, message.from_user.first_name)

    bots = await database.get_bots_by_user_id(user["id"])
    active_count = sum(1 for b in bots if b["status"] == "RUNNING")

    text = (
        "📊 <b>Ваша статистика хостинга:</b>\n\n"
        f"👤 Пользователь: <code>{user.get('first_name', '')} (@{user.get('username', 'none')})</code>\n"
        f"🆔 Telegram ID: <code>{user_id}</code>\n"
        f"🤖 Всего ботов: <b>{len(bots)} / {user.get('bots_limit', 3)}</b>\n"
        f"🟢 Активных сейчас: <b>{active_count}</b>\n"
        f"📢 Статус подписки: <b>Подписан ✅</b>\n"
    )
    await message.answer(text, parse_mode="HTML")

@dp.message(F.text.func(lambda t: bool(t and any(k in t.lower() for k in ("справ", "помощ", "help", "инфо")))))
async def handle_help(message: Message):
    logger.info(f"User {message.from_user.id} requested help: {message.text!r}")
    text = (
        "ℹ️ <b>О хостинге Telegram ботов:</b>\n\n"
        "• Каждый бот запускается в полностью изолированном окружении (Docker).\n"
        "• Поддерживаются боты на Python (aiogram, telebot, python-telegram-bot и др.).\n"
        "• Вы можете загружать свои файлы (включая requirements.txt и zip-архивы).\n"
        "• Просмотр логов в реальном времени прямо из браузера.\n"
        f"• Обязательное условие бесплатного хостинга: быть подписчиком {REQUIRED_CHANNEL}.\n\n"
        "По вопросам поддержки: @AstrixStudio"
    )
    await message.answer(text, parse_mode="HTML")

@dp.message(F.text.func(lambda t: bool(t and any(k in t.lower() for k in ("админ", "admin")))))
async def handle_admin(message: Message):
    logger.info(f"User {message.from_user.id} requested admin panel: {message.text!r}")
    user_id = message.from_user.id
    user = await database.get_user_by_telegram_id(user_id)
    if not user or not user.get("is_admin"):
        await message.answer("⛔ Доступ запрещен. Вы не являетесь администратором.")
        return

    all_users = await database.get_all_users()
    all_bots = await database.get_all_bots()
    running_bots = sum(1 for b in all_bots if b["status"] == "RUNNING")

    token = await database.create_login_token(user_id, ttl_minutes=15)
    admin_url = f"{PUBLIC_URL}/login?token={token}&next=/admin"

    text = (
        "👑 <b>Административная панель хостинга</b>\n\n"
        f"👥 Всего пользователей: <b>{len(all_users)}</b>\n"
        f"🤖 Всего ботов в системе: <b>{len(all_bots)}</b> (из них активно: <b>{running_bots}</b>)\n\n"
        f"👉 <a href=\"{admin_url}\"><b>Войти в админ-панель хостинга</b></a>\n\n"
        f"Прямая ссылка для браузера:\n<code>{admin_url}</code>"
    )

    if not ("localhost" in PUBLIC_URL or "127.0.0.1" in PUBLIC_URL):
        try:
            kb = InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="🛡 Открыть веб-админку", url=admin_url)]
            ])
            await message.answer(text, reply_markup=kb, parse_mode="HTML")
            return
        except Exception:
            pass

    await message.answer(text, parse_mode="HTML", disable_web_page_preview=True)

# Universal fallback handler for ANY message
@dp.message()
async def handle_unknown_message(message: Message):
    logger.info(f"Fallback received: {message.from_user.id} sent {message.text!r}")
    user_id = message.from_user.id
    user = await database.get_user_by_telegram_id(user_id)
    is_admin = bool(user.get("is_admin")) if user else (user_id in ADMIN_IDS)
    await message.answer(
        "👋 Выберите действие в меню ниже или отправьте /start:",
        reply_markup=get_main_menu_keyboard(is_admin)
    )

async def start_telegram_bot() -> Optional[Bot]:
    global _bot_instance
    if not BOT_TOKEN:
        logger.warning("BOT_TOKEN is empty! Telegram bot polling will not start.")
        return None

    bot = Bot(token=BOT_TOKEN)
    _bot_instance = bot
    await setup_bot_commands(bot)
    logger.info("Starting Telegram bot polling...")
    # Polling without dropping updates
    asyncio.create_task(dp.start_polling(bot, drop_pending_updates=False))
    return bot
