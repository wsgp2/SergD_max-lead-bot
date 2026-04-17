"""Обработчики событий бота.

Воронка v2 (короткая): телефон ПЕРВЫМ, остальное опционально.
  /start → приветствие + кнопка «📞 Получить скидку»
  → контакт → сохранён! промокод + «Напишите ФИО и школу»
  → (опционально) ФИО/школа → PDF + канал + меню А/Б/В
"""
from __future__ import annotations

import asyncio
import logging
import re
from typing import Optional

from maxapi import Router, F
from maxapi.context import MemoryContext
from maxapi.context.state_machine import State, StatesGroup
from maxapi.filters.command import Command, CommandStart
from maxapi.types import (
    BotStarted,
    MessageCallback,
    MessageCreated,
)
from maxapi.types.attachments.contact import Contact
from maxapi.types.input_media import InputMediaBuffer, InputMedia
from maxapi.enums.parse_mode import TextFormat

import keyboards as kb
import notifier
import storage
import texts
from config import (
    BRANCH_DISCOUNT,
    BRANCH_PARTNERSHIP,
    BRANCH_IDEAS,
    DOGOVOR_PATH,
    METHODICHKA_PATH,
    SEED_ADMIN_IDS,
)

log = logging.getLogger("handlers")
router = Router("pryanik")


class Form(StatesGroup):
    phone = State()       # шаг 1: ждём контакт (телефон)
    extra_info = State()  # шаг 2: опциональный ввод ФИО/школы


PHONE_RE = re.compile(r"[\d\s\-\+\(\)]{7,}")


def _first_name(full: str) -> str:
    parts = (full or "").split()
    if len(parts) >= 2:
        return parts[1]
    return parts[0] if parts else "друг"


_MD_ESCAPE_RE = re.compile(r"([\\*_`\[\]()~>#+\-=|{}.!])")


def _md_escape(s: str) -> str:
    return _MD_ESCAPE_RE.sub(r"\\\1", s or "")


def _log_task_result(task: asyncio.Task) -> None:
    if task.cancelled():
        return
    exc = task.exception()
    if exc is not None:
        log.exception("Ошибка в фоновой задаче %s: %r", task.get_name(), exc)


def _extract_phone_from_contact(event: MessageCreated) -> Optional[str]:
    atts = event.message.body.attachments or []
    for a in atts:
        if isinstance(a, Contact):
            phone = a.payload.vcf.phone if a.payload else None
            if phone:
                return phone
    return None


def _extract_phone_from_text(text: str) -> Optional[str]:
    m = PHONE_RE.search(text or "")
    if not m:
        return None
    raw = re.sub(r"\D", "", m.group(0))
    if len(raw) < 10:
        return None
    if len(raw) == 10:
        raw = "7" + raw
    return "+" + raw


async def _send_file_safely(event: MessageCreated, path, caption: str | None) -> None:
    try:
        if not path.exists():
            log.warning("File %s missing, skipping send", path)
            return
        await event.message.answer(
            text=caption,
            attachments=[InputMedia(path=str(path))],
        )
    except Exception as e:
        log.exception("Failed to send file %s: %s", path, e)


async def _notify_admins(bot, contact: dict) -> None:
    notify_task = asyncio.create_task(
        notifier.notify_new_contact(bot, contact),
        name=f"notify_admins:{contact.get('user_id', '?')}",
    )
    notify_task.add_done_callback(_log_task_result)


# ──────────────────────────────────────────────────────────
#  СТАРТ: короткое приветствие + кнопка «Получить скидку»
# ──────────────────────────────────────────────────────────

@router.bot_started()
async def on_bot_started(event: BotStarted) -> None:
    await event.bot.send_message(
        chat_id=event.chat_id,
        text=texts.WELCOME_SHORT,
        attachments=kb.get_discount_contact(),
    )


@router.message_created(CommandStart())
async def on_start(event: MessageCreated, context: MemoryContext) -> None:
    await context.set_state(Form.phone)
    await context.set_data({})
    await event.message.answer(
        text=texts.WELCOME_SHORT,
        attachments=kb.get_discount_contact(),
    )


@router.message_created(Command("menu"))
async def on_menu(event: MessageCreated, context: MemoryContext) -> None:
    await context.set_state(None)
    await event.message.answer(
        text="Что ещё вам интересно? 👇",
        attachments=kb.main_menu(),
    )


# ──────────────────────────────────────────────────────────
#  ШАГ 1: получаем телефон (контакт или текстом)
# ──────────────────────────────────────────────────────────

@router.message_created(states=[Form.phone])
async def step_phone(event: MessageCreated, context: MemoryContext) -> None:
    phone = _extract_phone_from_contact(event)
    if not phone:
        phone = _extract_phone_from_text(event.message.body.text or "")
    if not phone:
        await event.message.answer(
            text=texts.PHONE_RETRY,
            attachments=kb.get_discount_contact(),
        )
        return

    # Сохраняем сразу — минимальный контакт (телефон).
    sender = event.message.sender
    chat_id = event.message.recipient.chat_id if event.message.recipient else None
    contact = {
        "user_id": sender.user_id,
        "chat_id": chat_id,
        "branch": BRANCH_DISCOUNT,
        "name": "",
        "city": "",
        "school": "",
        "phone": phone,
        "username": getattr(sender, "username", None),
    }
    await storage.save_contact(**contact)
    await _notify_admins(event.bot, contact)

    # Промокод сразу — даже если уйдёт, телефон у нас.
    await event.message.answer(
        text=texts.PROMO_INSTANT,
        format=TextFormat.MARKDOWN,
    )

    # Просим ФИО/школу (но необязательно)
    await context.update_data(phone=phone)
    await context.set_state(Form.extra_info)
    await event.message.answer(
        text=texts.ASK_EXTRA_INFO,
    )


# ──────────────────────────────────────────────────────────
#  ШАГ 2 (опциональный): ФИО и/или школа одним сообщением
# ──────────────────────────────────────────────────────────

@router.message_created(states=[Form.extra_info])
async def step_extra_info(event: MessageCreated, context: MemoryContext) -> None:
    text = (event.message.body.text or "").strip()
    if len(text) < 2:
        # Не стал вводить — ок, показываем финал
        await _send_finish(event, context)
        return

    # Пытаемся разобрать: «Иванова Мария, Школа 7, Пермь» или просто ФИО
    data = await context.get_data()
    parts = [p.strip() for p in re.split(r"[,\n;]", text) if p.strip()]

    name = parts[0] if len(parts) >= 1 else text
    school = parts[1] if len(parts) >= 2 else ""
    city = parts[2] if len(parts) >= 3 else ""

    # Обновляем запись в БД (upsert)
    sender = event.message.sender
    chat_id = event.message.recipient.chat_id if event.message.recipient else None
    await storage.save_contact(
        user_id=sender.user_id,
        chat_id=chat_id,
        branch=BRANCH_DISCOUNT,
        name=name,
        city=city,
        school=school,
        phone=data.get("phone", ""),
        username=getattr(sender, "username", None),
    )

    await _send_finish(event, context, name=name)


async def _send_finish(
    event: MessageCreated,
    context: MemoryContext,
    name: str = "",
) -> None:
    """Финальный блок: PDF + скрипт + канал + меню."""
    await context.set_state(None)
    first = _md_escape(_first_name(name)) if name else ""

    if first:
        await event.message.answer(
            f"Спасибо, {first}! Закрепил скидку за вами.",
        )

    await _send_file_safely(event, METHODICHKA_PATH, caption=texts.PDF_CAPTION)
    await event.message.answer(
        text=texts.SCRIPT_FOR_DIRECTOR,
        attachments=kb.after_discount(),
    )
    await event.message.answer(
        text=texts.FINAL_CHANNEL_INVITE,
        attachments=kb.channel_only(),
    )
    await event.message.answer(
        text="Что ещё вам интересно? 👇",
        attachments=kb.main_menu(),
    )


# ──────────────────────────────────────────────────────────
#  МЕНЮ: ветки Б и В (после основной воронки)
# ──────────────────────────────────────────────────────────

@router.message_callback(F.callback.payload == "menu:A")
async def cb_menu_a(event: MessageCallback, context: MemoryContext) -> None:
    """Повторный вход в скидку — если ещё не давал контакт, спросим."""
    await context.set_state(Form.phone)
    await event.bot.send_message(
        user_id=event.from_user.user_id,
        text=texts.BRANCH_A_INTRO,
        attachments=kb.get_discount_contact(),
    )


@router.message_callback(F.callback.payload == "menu:B")
async def cb_menu_b(event: MessageCallback, context: MemoryContext) -> None:
    await context.set_state(Form.phone)
    await context.update_data(branch=BRANCH_PARTNERSHIP)
    await event.bot.send_message(
        user_id=event.from_user.user_id,
        text=texts.BRANCH_B_INTRO,
        attachments=kb.get_discount_contact(),
    )


@router.message_callback(F.callback.payload == "menu:C")
async def cb_menu_c(event: MessageCallback, context: MemoryContext) -> None:
    await context.set_state(None)
    await event.bot.send_message(
        user_id=event.from_user.user_id,
        text=texts.BRANCH_C_TEXT,
        attachments=kb.branch_c_menu(),
    )


@router.message_callback(F.callback.payload == "recipe")
async def cb_recipe(event: MessageCallback) -> None:
    await event.bot.send_message(
        user_id=event.from_user.user_id,
        text=texts.KOZULI_RECIPE,
        attachments=kb.channel_only(),
    )


# ──────────────────────────────────────────────────────────
#  АДМИН
# ──────────────────────────────────────────────────────────

def _is_admin(event: MessageCreated) -> bool:
    return event.message.sender.user_id in SEED_ADMIN_IDS


@router.message_created(Command("export"))
async def cmd_export(event: MessageCreated) -> None:
    if not _is_admin(event):
        await event.message.answer(texts.NOT_ADMIN)
        return
    data = await storage.export_csv()
    buf = InputMediaBuffer(buffer=data, filename="contacts.csv")
    await event.message.answer(text="Выгрузка контактов", attachments=[buf])


@router.message_created(Command("stats"))
async def cmd_stats(event: MessageCreated) -> None:
    if not _is_admin(event):
        await event.message.answer(texts.NOT_ADMIN)
        return
    s = await storage.stats()
    lines = [f"{k}: {v}" for k, v in s.items()]
    await event.message.answer("📊 Статистика\n" + "\n".join(lines))


@router.message_created(Command("digest"))
async def cmd_digest(event: MessageCreated) -> None:
    if not _is_admin(event):
        await event.message.answer(texts.NOT_ADMIN)
        return
    await event.message.answer("Отправляю дайджест…")
    await notifier.send_digest_now(event.bot)


@router.message_created(Command("help"))
async def cmd_help(event: MessageCreated) -> None:
    if _is_admin(event):
        await event.message.answer(texts.ADMIN_HELP)
    else:
        await event.message.answer("Напишите /start чтобы начать заново.")


# ──────────────────────────────────────────────────────────
#  FALLBACK
# ──────────────────────────────────────────────────────────

_FORGET_RE = re.compile(
    r"удал[ияеть]+\s+(?:все\s+|всю\s+|мо[ияе]+\s+|полностью\s+){0,3}данны[ех]",
    re.IGNORECASE,
)


@router.message_created()
async def fallback(event: MessageCreated, context: MemoryContext) -> None:
    text = (event.message.body.text or "").strip()

    if _FORGET_RE.search(text):
        removed = await storage.forget_user(event.message.sender.user_id)
        await context.set_state(None)
        await context.set_data({})
        if removed:
            await event.message.answer(
                f"✅ Удалил все ваши данные из системы ({removed} записей).\n"
                "Если захотите вернуться — напишите /start."
            )
        else:
            await event.message.answer(
                "У меня нет ваших данных. Напишите /start, чтобы начать."
            )
        return

    state = await context.get_state()
    if state is not None:
        return

    # Если пишет произвольный текст — предлагаем контакт или меню
    await event.message.answer(
        text=texts.WELCOME_SHORT,
        attachments=kb.get_discount_contact(),
    )
