"""Уведомления админам: о новой регистрации и ежедневный дайджест."""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta, timezone
from typing import TYPE_CHECKING
from zoneinfo import ZoneInfo

import storage
from config import DIGEST_HOUR, DIGEST_MINUTE, DIGEST_TZ

if TYPE_CHECKING:
    from maxapi import Bot

log = logging.getLogger("notifier")

BRANCH_LABEL = {"A": "🎁 Скидка (А)", "B": "💰 Партнёрство (Б)", "C": "📖 Идеи (В)"}


async def notify_new_contact(bot: "Bot", contact: dict) -> None:
    """Шлёт всем админам уведомление о новой анкете."""
    admins = await storage.list_admins()
    if not admins:
        return
    branch_lbl = BRANCH_LABEL.get(contact["branch"], contact["branch"])
    text = (
        f"🆕 Новая анкета в боте!\n\n"
        f"{branch_lbl}\n"
        f"👤 {contact['name']}\n"
        f"🏙 {contact['city']}\n"
        f"🏫 {contact['school']}\n"
        f"📞 {contact['phone']}"
    )
    for a in admins:
        cid = a.get("chat_id")
        if not cid:
            continue
        try:
            await bot.send_message(chat_id=cid, text=text, notify=True)
        except Exception as e:
            log.warning("Не смог уведомить админа %s (%s): %s", a["name"], cid, e)


def _build_digest_text(tz_name: str, day_rows: list[dict]) -> str:
    header = f"📊 Дайджест за вчера ({tz_name})"
    if not day_rows:
        return f"{header}\n\n— Новых анкет нет."

    by_branch: dict[str, int] = {}
    for r in day_rows:
        by_branch[r["branch"]] = by_branch.get(r["branch"], 0) + 1
    parts = [header, f"\n👥 Всего новых: {len(day_rows)}"]
    for b in ("A", "B", "C"):
        if b in by_branch:
            parts.append(f"  {BRANCH_LABEL[b]}: {by_branch[b]}")

    parts.append("\nКонтакты:")
    for r in day_rows[:30]:
        parts.append(
            f"• [{r['branch']}] {r['name']} — {r['city']} — {r['school']} — {r['phone']}"
        )
    if len(day_rows) > 30:
        parts.append(f"… и ещё {len(day_rows) - 30}. Полная выгрузка: /export")
    return "\n".join(parts)


async def _send_digest_once(bot: "Bot") -> None:
    tz = ZoneInfo(DIGEST_TZ)
    now_tz = datetime.now(tz)
    # вчера 00:00…сегодня 00:00 в локальном TZ → в UTC ISO
    today_start_local = now_tz.replace(hour=0, minute=0, second=0, microsecond=0)
    yesterday_start_local = today_start_local - timedelta(days=1)
    # в БД мы пишем UTC (datetime.utcnow().isoformat)
    start_iso = yesterday_start_local.astimezone(timezone.utc).replace(tzinfo=None).isoformat(timespec="seconds")
    end_iso = today_start_local.astimezone(timezone.utc).replace(tzinfo=None).isoformat(timespec="seconds")

    rows = await storage.contacts_for_period(start_iso, end_iso)
    text = _build_digest_text(DIGEST_TZ, rows)

    admins = await storage.list_admins()
    for a in admins:
        cid = a.get("chat_id")
        if not cid:
            continue
        try:
            await bot.send_message(chat_id=cid, text=text)
        except Exception as e:
            log.warning("Не смог отправить дайджест %s (%s): %s", a["name"], cid, e)
    log.info("Дайджест отправлен: %s новых, %s админов", len(rows), len(admins))


async def _sleep_until_next_digest() -> None:
    tz = ZoneInfo(DIGEST_TZ)
    now = datetime.now(tz)
    target = now.replace(hour=DIGEST_HOUR, minute=DIGEST_MINUTE, second=0, microsecond=0)
    if target <= now:
        target += timedelta(days=1)
    delta = (target - now).total_seconds()
    log.info("Следующий дайджест: %s (через %.0f мин)", target.isoformat(), delta / 60)
    await asyncio.sleep(delta)


async def digest_loop(bot: "Bot") -> None:
    """Бесконечный цикл: каждый день в DIGEST_HOUR:DIGEST_MINUTE по DIGEST_TZ."""
    log.info("Запущен планировщик дайджестов: %02d:%02d %s", DIGEST_HOUR, DIGEST_MINUTE, DIGEST_TZ)
    while True:
        try:
            await _sleep_until_next_digest()
            await _send_digest_once(bot)
        except asyncio.CancelledError:
            raise
        except Exception as e:
            log.exception("Ошибка в digest_loop: %s", e)
            await asyncio.sleep(60)


async def send_digest_now(bot: "Bot") -> None:
    """Ручной вызов дайджеста (по команде /digest)."""
    await _send_digest_once(bot)
