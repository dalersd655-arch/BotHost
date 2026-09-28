import asyncio
import logging
import sys
from aiohttp import web

# Ensure utf-8 output on Windows
if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding='utf-8')
        sys.stderr.reconfigure(encoding='utf-8')
    except Exception:
        pass

from config import (
    BOT_TOKEN, WEB_HOST, WEB_PORT, PUBLIC_URL,
    REQUIRED_CHANNEL, CHANNEL_URL
)
import database
from docker_manager import docker_mgr
from bot import start_telegram_bot, check_user_subscription, get_bot
from web import create_web_app

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)]
)
logger = logging.getLogger("hosting_core")

async def subscription_and_health_monitor():
    """Background worker to monitor subscriptions and bot statuses."""
    logger.info("Background subscription & health monitor started.")
    while True:
        try:
            await asyncio.sleep(60)
            bot = get_bot()
            if not bot:
                continue

            all_users = await database.get_all_users()
            for user in all_users:
                # Admins bypass check
                if user.get("is_admin"):
                    continue

                tg_id = user["telegram_id"]
                is_sub = await check_user_subscription(bot, tg_id)

                # If user unsubscribed from channel: enforce suspension
                if not is_sub and user.get("is_subscribed"):
                    logger.warning(f"User {tg_id} unsubscribed from {REQUIRED_CHANNEL}! Suspending active bots...")
                    user_bots = await database.get_bots_by_user_id(user["id"])
                    for b in user_bots:
                        if b["status"] == "RUNNING":
                            await docker_mgr.stop_bot(b)
                            await database.add_system_log(
                                f"Bot #{b['id']} automatically stopped due to unsubscription from {REQUIRED_CHANNEL}",
                                b["id"], "WARNING"
                            )

        except asyncio.CancelledError:
            break
        except Exception as e:
            logger.error(f"Error in monitor worker: {e}")
            await asyncio.sleep(10)

async def main():
    print("=" * 60)
    print("🚀 Telegram Bot Hosting Server v2.0")
    print(f"📢 Required Channel: {REQUIRED_CHANNEL} ({CHANNEL_URL})")
    print(f"🌐 Web Panel URL:   {PUBLIC_URL}")
    print("=" * 60)

    # 1. Initialize SQLite Database
    logger.info("Initializing database...")
    await database.init_db()

    # 2. Check Docker availability
    docker_status = await docker_mgr.check_docker()
    if docker_status:
        logger.info("🐳 Docker Daemon detected and ready for isolated containers.")
    else:
        logger.info("⚡ Docker Daemon not detected. Using safe Process Isolation runner fallback.")

    # 3. Create Web Application
    app = create_web_app()
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, WEB_HOST, WEB_PORT)
    await site.start()
    logger.info(f"🌐 Web Server is running at http://{WEB_HOST}:{WEB_PORT}")

    # 4. Start Telegram Bot Polling
    if BOT_TOKEN:
        logger.info("Starting Telegram Bot with menu-button and channel subscription check...")
        bot = await start_telegram_bot()
    else:
        logger.warning(
            "⚠️ BOT_TOKEN is not set in environment or .env!\n"
            "   Create a .env file with BOT_TOKEN=your_token from @BotFather to enable Telegram interactions.\n"
            "   The web interface is running and accessible."
        )

    # 5. Launch Background Monitor
    monitor_task = asyncio.create_task(subscription_and_health_monitor())

    try:
        # Keep running
        while True:
            await asyncio.sleep(3600)
    except (asyncio.CancelledError, KeyboardInterrupt):
        logger.info("Shutting down Telegram Bot Hosting...")
    finally:
        monitor_task.cancel()
        await runner.cleanup()
        logger.info("Server stopped.")

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        pass
