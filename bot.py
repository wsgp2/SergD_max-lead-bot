"""Точка входа: запускает long-polling бота."""
from __future__ import annotations

import asyncio
import logging
import os

from maxapi import Bot, Dispatcher
from maxapi.types import BotCommand

import handlers
import notifier
import storage
from config import MAX_BOT_TOKEN, SEED_ADMINS

logging.basicConfig(
    level=logging.DEBUG if os.environ.get("DEBUG", "0") == "1" else logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
# Даже в DEBUG НЕ логируем SQL/HTTP с параметрами — там летят телефоны/ФИО.
# Держим эти модули на INFO независимо от общего уровня.
for _name in ("aiohttp", "aiosqlite", "asyncio"):
    logging.getLogger(_name).setLevel(logging.INFO)
log = logging.getLogger("bot")


async def main() -> None:
    await storage.init_db()
    await storage.seed_admins(SEED_ADMINS)
    if SEED_ADMINS:
        log.info("Засеяно админов: %s", ", ".join(a["name"] for a in SEED_ADMINS))

    bot = Bot(MAX_BOT_TOKEN)

    try:
        await bot.set_my_commands(
            BotCommand(name="start", description="Главное меню"),
            BotCommand(name="menu", description="Показать меню"),
            BotCommand(name="help", description="Помощь"),
        )
    except Exception as e:
        log.warning("set_my_commands failed: %s", e)

    me = await bot.get_me()
    log.info("Bot started: %s (id=%s)", getattr(me, "username", None) or getattr(me, "first_name", "?"), getattr(me, "user_id", "?"))

    dp = Dispatcher()
    dp.include_routers(handlers.router)

    digest_task = asyncio.create_task(notifier.digest_loop(bot))

    try:
        await dp.start_polling(bot)
    finally:
        digest_task.cancel()
        try:
            await digest_task
        except asyncio.CancelledError:
            pass
        await bot.close_session()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        log.info("Stopped by user")
