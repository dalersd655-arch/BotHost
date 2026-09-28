"""Бот-привратник: /start, меню (бургер) со ссылкой на сайт, проверка подписки."""
import asyncio
from aiogram import Bot, Dispatcher, F
from aiogram.filters import CommandStart, Command
from aiogram.types import (Message, CallbackQuery, BotCommand, MenuButtonCommands,
                           InlineKeyboardMarkup, InlineKeyboardButton as Btn)
from . import config as C
from .subscription import check_async

dp = Dispatcher()

HELP = ("Это бесплатный хостинг Telegram-ботов.\n\n"
        "1. Подпишитесь на канал\n2. Откройте сайт и войдите через Telegram\n"
        "3. Загрузите ZIP с ботом и укажите токен\n\n"
        "Отписка от канала = доступ закрыт.")

# Telegram не принимает localhost/127.0.0.1 и не-http ссылки в кнопках
SITE_OK = C.PANEL_URL.startswith("http") and not any(x in C.PANEL_URL for x in ("localhost", "127.0.0.1", "0.0.0.0"))

def site_row():
    return [[Btn(text="🚀 Открыть сайт", url=C.PANEL_URL)]] if SITE_OK else []

def kb_menu():
    rows = site_row()
    if C.CHANNEL_URL: rows.append([Btn(text="📢 Наш канал", url=C.CHANNEL_URL)])
    rows += [[Btn(text="✅ Проверить подписку", callback_data="check")],
             [Btn(text="ℹ️ Помощь", callback_data="help")]]
    return InlineKeyboardMarkup(inline_keyboard=rows)

def site_hint() -> str:
    return "" if SITE_OK else f"\n\n🌐 Сайт (тест): {C.PANEL_URL}"

async def status_text(uid: int) -> str:
    ok = await check_async(uid)
    if ok: return "✅ Подписка подтверждена. Доступ к хостингу открыт."
    return "❗ Подпишитесь на канал, чтобы получить доступ к хостингу."

@dp.message(CommandStart())
async def start(m: Message):
    await m.answer(await status_text(m.from_user.id) + site_hint(), reply_markup=kb_menu())

@dp.message(Command("panel"))
async def panel(m: Message):
    await m.answer("Панель управления ботами:" + site_hint(),
                   reply_markup=InlineKeyboardMarkup(inline_keyboard=site_row()) if SITE_OK else None)

@dp.message(Command("channel"))
async def channel(m: Message):
    await m.answer("Наш канал:",
                   reply_markup=InlineKeyboardMarkup(inline_keyboard=[[Btn(text="📢 Открыть канал", url=C.CHANNEL_URL)]]))

@dp.message(Command("help"))
async def help_cmd(m: Message):
    await m.answer(HELP, reply_markup=kb_menu())

@dp.callback_query(F.data == "check")
async def check(cb: CallbackQuery):
    ok = await check_async(cb.from_user.id)
    if ok:
        await cb.answer("Подписка подтверждена ✅", show_alert=True)
        await cb.message.edit_text("✅ Подписка подтверждена. Доступ к хостингу открыт.", reply_markup=kb_menu())
    else:
        await cb.answer("Подписка не найдена. Подпишитесь и нажмите ещё раз.", show_alert=True)

@dp.callback_query(F.data == "help")
async def help_cb(cb: CallbackQuery):
    await cb.answer()
    await cb.message.answer(HELP)

async def main():
    bot = Bot(C.GATE_BOT_TOKEN)
    # Кнопка-бургер «Меню» слева от поля ввода
    await bot.set_my_commands([
        BotCommand(command="start", description="🏠 Главное меню"),
        BotCommand(command="panel", description="🚀 Открыть сайт"),
        BotCommand(command="channel", description="📢 Наш канал"),
        BotCommand(command="help", description="ℹ️ Помощь"),
    ])
    await bot.set_chat_menu_button(menu_button=MenuButtonCommands())
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
