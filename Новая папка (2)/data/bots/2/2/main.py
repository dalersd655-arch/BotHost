import os, asyncio
from aiogram import Bot, Dispatcher
from aiogram.filters import CommandStart
from aiogram.types import Message

dp = Dispatcher()

@dp.message(CommandStart())
async def start(m: Message):
    await m.answer("Привет! Я работаю на вашем хостинге 🎉")

@dp.message()
async def echo(m: Message):
    await m.answer(m.text or "👍")

async def main():
    token = os.environ.get("BOT_TOKEN")
    if not token:
        print("ERROR: BOT_TOKEN environment variable not set!", flush=True)
        return
    print("Bot started successfully on Telegram Bot Hosting!", flush=True)
    bot = Bot(token)
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
