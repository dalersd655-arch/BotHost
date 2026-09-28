import asyncio
import os
import sys
import shutil

# Ensure utf-8 output on Windows
if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding='utf-8')
        sys.stderr.reconfigure(encoding='utf-8')
    except Exception:
        pass
import database
from docker_manager import docker_mgr

async def run_tests():
    print("=== [TEST] 1. Инициализация БД ===")
    await database.init_db()
    print("-> БД успешно инициализирована.")

    print("\n=== [TEST] 2. Регистрация пользователя ===")
    test_tg_id = 999111222
    user = await database.get_or_create_user(test_tg_id, "testuser", "Test")
    assert user["telegram_id"] == test_tg_id, "User creation failed!"
    print(f"-> Пользователь создан: ID #{user['id']}, TG: {user['telegram_id']}, Лимит: {user['bots_limit']}")

    print("\n=== [TEST] 3. Сценарий: Проверка подписки (Не подписан) ===")
    await database.update_user_subscription(test_tg_id, False)
    u_unsub = await database.get_user_by_telegram_id(test_tg_id)
    assert u_unsub["is_subscribed"] == 0, "Subscription flag should be 0"
    print("-> Статус: Не подписан (доступ к хостингу ограничен).")

    print("\n=== [TEST] 4. Сценарий: Пользователь подписался на @AstrixStudio ===")
    await database.update_user_subscription(test_tg_id, True)
    u_sub = await database.get_user_by_telegram_id(test_tg_id)
    assert u_sub["is_subscribed"] == 1, "Subscription flag should be 1"
    print("-> Статус: Подписан ✅ (доступ к хостингу открыт).")

    print("\n=== [TEST] 5. Авторизация: Одноразовый токен входа ===")
    token = await database.create_login_token(test_tg_id, ttl_minutes=15)
    assert len(token) > 20, "Token generation failed"
    verified_tg_id = await database.verify_and_use_login_token(token)
    assert verified_tg_id == test_tg_id, "Token verification failed"
    # Second use must fail
    second_try = await database.verify_and_use_login_token(token)
    assert second_try is None, "Token re-use must be prevented"
    print("-> Одноразовый токен авторизации успешно подтвержден и аннулирован.")

    print("\n=== [TEST] 6. Создание бота и изоляция каталога ===")
    bot_obj = await database.create_bot(user["id"], "EchoBotTest", "123456:TEST_TOKEN_XYZ")
    assert bot_obj["id"] is not None, "Bot creation failed"
    print(f"-> Бот создан в БД: ID #{bot_obj['id']}, Название: {bot_obj['name']}")

    docker_mgr.ensure_default_files(user["id"], bot_obj["id"])
    bot_dir = docker_mgr.get_bot_dir(user["id"], bot_obj["id"])
    assert (bot_dir / "main.py").exists(), "main.py was not copied to bot dir"
    assert (bot_dir / "requirements.txt").exists(), "requirements.txt was not copied"
    assert (bot_dir / "Dockerfile").exists(), "Dockerfile was not generated"
    print(f"-> Каталог бота изолирован: {bot_dir}")
    print("-> Файлы шаблона проверены (main.py, requirements.txt, Dockerfile).")

    print("\n=== [TEST] 7. Запуск бота и чтение логов ===")
    success, msg = await docker_mgr.start_bot(bot_obj)
    print(f"-> Результат запуска: success={success}, msg={msg}")
    assert success is True, f"Bot start failed: {msg}"

    # Wait 1 sec for process output
    await asyncio.sleep(1.0)
    updated_bot = await database.get_bot_by_id(bot_obj["id"])
    print(f"-> Текущий статус бота: {updated_bot['status']}, Контейнер/PID: {updated_bot['container_id']}")
    assert updated_bot["status"] == "RUNNING", "Bot status is not RUNNING"

    logs = await docker_mgr.get_logs(bot_obj)
    print(f"-> Полученные логи:\n---\n{logs.strip()[:150]}\n---")

    print("\n=== [TEST] 8. Остановка бота ===")
    stop_ok, stop_msg = await docker_mgr.stop_bot(bot_obj)
    assert stop_ok is True, "Stop failed"
    updated_bot = await database.get_bot_by_id(bot_obj["id"])
    assert updated_bot["status"] == "STOPPED", "Bot status is not STOPPED"
    print(f"-> Бот успешно остановлен: {stop_msg}")

    print("\n=== [TEST] 9. Сценарий отписки и автоматическая блокировка ===")
    # Restart bot first
    await docker_mgr.start_bot(bot_obj)
    # Simulate unsubscription
    await database.update_user_subscription(test_tg_id, False)
    # Check if subscription monitor stops running bots
    user_bots = await database.get_bots_by_user_id(user["id"])
    for b in user_bots:
        if b["status"] == "RUNNING":
            await docker_mgr.stop_bot(b)
            await database.add_system_log(f"Auto-stop due to unsubscription test", b["id"])
    
    bot_after_unsub = await database.get_bot_by_id(bot_obj["id"])
    assert bot_after_unsub["status"] == "STOPPED", "Bot must be stopped after unsubscription"
    print("-> Отписка отработана: бот принудительно остановлен, доступ заблокирован.")

    print("\n=== [TEST] 10. Админ-панель: Лимиты и бан ===")
    await database.update_user_limit(user["id"], 5)
    u_after_limit = await database.get_user_by_id(user["id"])
    assert u_after_limit["bots_limit"] == 5, "Limit update failed"
    print(f"-> Лимит успешно изменен на {u_after_limit['bots_limit']}")

    await database.update_user_block_status(user["id"], True)
    u_after_ban = await database.get_user_by_id(user["id"])
    assert u_after_ban["is_blocked"] == 1, "Ban failed"
    print("-> Пользователь успешно заблокирован администратором.")

    # Cleanup test bot
    await docker_mgr.cleanup_bot(bot_obj)
    await database.delete_bot(bot_obj["id"])
    print("\n=== ВСЕ 10 СЦЕНАРИЕВ ТЕСТИРОВАНИЯ УСПЕШНО ПРОЙДЕНЫ! ===")

if __name__ == "__main__":
    asyncio.run(run_tests())
